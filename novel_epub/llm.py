"""Hafif yapay zekâ istemcisi (LiteLLM'in kullandığımız küçük kısmı; ek paket yok, HTTP için curl_cffi).

- OpenAI uyumlu sohbet ucu: OpenAI, DeepSeek, OpenRouter, Groq, xAI, Cerebras, Fireworks, Together, Mistral, Ollama.
- Gemini: generateContent (JSON şeması, düşünme seviyesi).
- Anthropic Claude: messages (JSON, şema talimatla).

`completion()` LiteLLM ile aynı biçimde yanıt döndürür (choices[0].message.content, finish_reason, usage) ve hata
sınıflarının adları/`status_code` alanı da aynıdır; çevirmen ikisini ayırt etmez.
"""
from __future__ import annotations

import json
import re
from types import SimpleNamespace

from .providers import BY_PREFIX, provider_of

OPENAI_BASE = {
    "openai": "https://api.openai.com/v1", "deepseek": "https://api.deepseek.com/v1",
    "openrouter": "https://openrouter.ai/api/v1", "groq": "https://api.groq.com/openai/v1",
    "xai": "https://api.x.ai/v1", "cerebras": "https://api.cerebras.ai/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1", "together": "https://api.together.xyz/v1",
    "mistral": "https://api.mistral.ai/v1",
}
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


# --- hata sınıfları (adları LiteLLM'inkilerle aynı; çevirmenin _classify'ı ada ve koda bakar) ---
class APIError(Exception):
    status_code: int | None = None

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code


class BadRequestError(APIError): status_code = 400
class AuthenticationError(APIError): status_code = 401
class PaymentRequiredError(APIError): status_code = 402
class PermissionDeniedError(APIError): status_code = 403
class NotFoundError(APIError): status_code = 404
class UnprocessableEntityError(APIError): status_code = 422
class RateLimitError(APIError): status_code = 429
class InternalServerError(APIError): status_code = 500
class ServiceUnavailableError(APIError): status_code = 503
class APIConnectionError(APIError): pass


_BY_CODE = {400: BadRequestError, 401: AuthenticationError, 402: PaymentRequiredError, 403: PermissionDeniedError,
            404: NotFoundError, 422: UnprocessableEntityError, 429: RateLimitError, 503: ServiceUnavailableError}


def _raise_for(status: int, text: str, model: str) -> None:
    cls = _BY_CODE.get(status) or (InternalServerError if status >= 500 else APIError)
    raise cls(f"{model}: HTTP {status}: {text[:2000]}", status)


# --- model özellikleri (ada göre sezgi) ---
def split(model: str) -> tuple[str, str]:
    """'gemini/x' → ('gemini', 'x'); sağlayıcı kimliği (prefix değil) döner."""
    p = provider_of(model)
    name = model.split("/", 1)[1] if "/" in model and model.split("/", 1)[0] in BY_PREFIX else model
    return p.id, name


def max_output_tokens(model: str) -> int:
    pid, name = split(model)
    n = name.lower()
    if pid == "gemini":
        return 65536
    if pid == "anthropic":
        return 8192 if re.search(r"claude-3-(5-)?(haiku|sonnet)|claude-3-opus", n) else 64000
    if pid == "openai":
        if re.match(r"o\d|gpt-5", n):
            return 100000
        return 32768 if "gpt-4.1" in n else 16384
    if pid == "deepseek":
        return 32768 if "reasoner" in n else 8192
    if pid == "openrouter":
        return 32768
    return 8192


def supports_schema(model: str) -> bool:
    """Yanıtı JSON şemasına bağlamayı yerel olarak destekliyor mu (yoksa şema talimata yazılır)."""
    return split(model)[0] in ("gemini", "openai", "xai")


def supports_reasoning(model: str) -> bool:
    pid, name = split(model)
    n = name.lower()
    return pid == "gemini" or (pid == "openai" and bool(re.match(r"o\d|gpt-5", n))) or (pid == "xai" and "mini" in n)


# --- istek kurma ---
def _gemini_schema(s):
    """JSON şeması → Gemini şeması (tür adları büyük harf)."""
    if isinstance(s, dict):
        out = {}
        for k, v in s.items():
            if k == "type" and isinstance(v, str):
                out[k] = v.upper()
            elif k == "properties":
                out[k] = {pk: _gemini_schema(pv) for pk, pv in v.items()}
            else:
                out[k] = _gemini_schema(v)
        return out
    if isinstance(s, list):
        return [_gemini_schema(x) for x in s]
    return s


def build_request(model: str, messages: list[dict], api_key: str | None = None, api_base: str | None = None,
                  temperature: float | None = None, max_tokens: int | None = None,
                  response_format: dict | None = None, reasoning_effort: str | None = None) -> tuple[str, dict, dict]:
    """(url, başlıklar, gövde)."""
    pid, name = split(model)
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    chat = [m for m in messages if m["role"] != "system"]
    headers = {"Content-Type": "application/json"}
    if pid == "gemini":
        cfg: dict = {"maxOutputTokens": max_tokens or 8192}
        if temperature is not None:
            cfg["temperature"] = temperature
        if response_format and response_format.get("type") in ("json_schema", "json_object"):
            cfg["responseMimeType"] = "application/json"
            if response_format["type"] == "json_schema":
                cfg["responseSchema"] = _gemini_schema(response_format["json_schema"]["schema"])
        if reasoning_effort:
            cfg["thinkingConfig"] = {"thinkingLevel": reasoning_effort}
        body = {"contents": [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                             for m in chat], "generationConfig": cfg}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        headers["x-goog-api-key"] = api_key or ""
        return GEMINI_URL.format(model=name), headers, body
    if pid == "anthropic":
        body = {"model": name, "max_tokens": max_tokens or 8192, "messages": chat}
        if system:
            body["system"] = system
        if temperature is not None:
            body["temperature"] = min(1.0, temperature)
        headers.update({"x-api-key": api_key or "", "anthropic-version": "2023-06-01"})
        return ANTHROPIC_URL, headers, body
    # OpenAI uyumlu
    base = (api_base.rstrip("/") + "/v1") if pid == "ollama" else OPENAI_BASE.get(pid, OPENAI_BASE["openai"])
    body = {"model": name, "messages": messages}
    body["max_completion_tokens" if pid == "openai" else "max_tokens"] = max_tokens or 8192
    if temperature is not None and not (pid == "openai" and re.match(r"o\d|gpt-5", name.lower())):
        body["temperature"] = temperature  # o/gpt-5 serisi yalnız varsayılan sıcaklığı kabul eder
    if response_format:
        body["response_format"] = response_format
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if pid == "openrouter":
        headers.update({"HTTP-Referer": "https://github.com/N4CR0N/novel-epub", "X-Title": "WebNovel Downloader & Translator"})
    return base + "/chat/completions", headers, body


def _parse(pid: str, data: dict):
    """Sağlayıcı yanıtı → (metin, bitiş nedeni, toplam çıktı token'ı, düşünme token'ı)."""
    if pid == "gemini":
        cands = data.get("candidates") or []
        if not cands:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "boş yanıt")
            raise ValueError(f"yanıt yok ({reason})")
        c = cands[0]
        text = "".join(p.get("text", "") for p in (c.get("content") or {}).get("parts") or [] if not p.get("thought"))
        fr = c.get("finishReason", "")
        um = data.get("usageMetadata") or {}
        thought = um.get("thoughtsTokenCount", 0) or 0
        return text, ("length" if fr == "MAX_TOKENS" else "stop"), (um.get("candidatesTokenCount", 0) or 0) + thought, thought
    if pid == "anthropic":
        text = "".join(b.get("text", "") for b in data.get("content") or [] if b.get("type") == "text")
        fr = "length" if data.get("stop_reason") == "max_tokens" else "stop"
        return text, fr, (data.get("usage") or {}).get("output_tokens", 0) or 0, 0
    ch = (data.get("choices") or [{}])[0]
    usage = data.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    return ((ch.get("message") or {}).get("content") or ""), ch.get("finish_reason") or "stop", \
        usage.get("completion_tokens", 0) or 0, details.get("reasoning_tokens", 0) or 0


def _post(url: str, headers: dict, body: dict, timeout: float):
    from curl_cffi import requests

    return requests.post(url, headers=headers, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), timeout=timeout)


def completion(model: str, messages: list[dict], api_key: str | None = None, api_base: str | None = None,
               temperature: float | None = None, max_tokens: int | None = None, response_format: dict | None = None,
               reasoning_effort: str | None = None, timeout: float = 900, post=None, **_ignored):
    """Tek istek; LiteLLM ModelResponse biçiminde nesne döndürür. Hata HTTP koduna göre sınıflanır."""
    pid, _ = split(model)
    url, headers, body = build_request(model, messages, api_key, api_base, temperature, max_tokens,
                                       response_format, reasoning_effort)
    try:
        r = (post or _post)(url, headers, body, timeout)
    except Exception as e:
        raise APIConnectionError(f"{model}: bağlantı hatası: {type(e).__name__}: {e}") from e
    if r.status_code >= 400:
        _raise_for(r.status_code, r.text, model)
    try:
        data = r.json()
    except ValueError as e:
        raise ValueError(f"yanıt JSON değil: {r.text[:200]}") from e
    text, finish, total, thought = _parse(pid, data)
    msg = SimpleNamespace(content=text)
    usage = SimpleNamespace(completion_tokens=total, completion_tokens_details=SimpleNamespace(reasoning_tokens=thought))
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish)], usage=usage, model=model)
