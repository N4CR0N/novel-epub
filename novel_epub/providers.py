"""Yapay zekâ sağlayıcıları: API anahtarından sağlayıcıyı tanıma, erişilen modelleri listeleme, sıralama.

Model adları "<önek>/<model>" biçimindedir (LiteLLM ile aynı adlandırma; ör. "gemini/gemini-3.8-flash",
"openai/gpt-5", "anthropic/claude-sonnet-4-5"). Önek olmayan eski adlar Gemini sayılır.

Kullanıcı yalnız anahtarı yapıştırır: biçiminden sağlayıcı tahmin edilir, belirsizse (ör. "sk-..." hem OpenAI hem
DeepSeek olabilir) adayların model listesi uçları sırayla denenir; anahtarı kabul eden sağlayıcı seçilir.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Provider:
    id: str  # ayar/kasa anahtarı
    name: str  # arayüz adı
    prefix: str  # model adı öneki ("gemini/…")
    patterns: tuple[str, ...]  # anahtar biçimleri (regex, tam eşleşme)
    models_url: str  # model listesi ucu ("" = liste yok)
    auth: str = "bearer"  # bearer | x-api-key | goog | none
    key_url: str = ""  # anahtarın alındığı sayfa
    base_url: str = ""  # yerel sunucular için (Ollama)


PROVIDERS: tuple[Provider, ...] = (
    Provider("gemini", "Google Gemini", "gemini", (r"AIza[\w-]{30,}", r"AQ\.[\w.-]{20,}"),
             "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000", "goog",
             "https://aistudio.google.com/apikey"),
    Provider("anthropic", "Anthropic Claude", "anthropic", (r"sk-ant-[\w-]{20,}",),
             "https://api.anthropic.com/v1/models?limit=1000", "x-api-key", "https://console.anthropic.com/settings/keys"),
    Provider("openrouter", "OpenRouter", "openrouter", (r"sk-or-[\w-]{20,}",),
             "https://openrouter.ai/api/v1/models/user", "bearer", "https://openrouter.ai/keys"),
    Provider("openai", "OpenAI", "openai", (r"sk-(?:proj|svcacct|admin)-[\w-]{20,}", r"sk-[A-Za-z0-9]{40,}"),
             "https://api.openai.com/v1/models", "bearer", "https://platform.openai.com/api-keys"),
    Provider("deepseek", "DeepSeek", "deepseek", (r"sk-[a-f0-9]{32}",),
             "https://api.deepseek.com/models", "bearer", "https://platform.deepseek.com/api_keys"),
    Provider("groq", "Groq", "groq", (r"gsk_[A-Za-z0-9]{20,}",),
             "https://api.groq.com/openai/v1/models", "bearer", "https://console.groq.com/keys"),
    Provider("xai", "xAI Grok", "xai", (r"xai-[A-Za-z0-9]{20,}",),
             "https://api.x.ai/v1/models", "bearer", "https://console.x.ai"),
    Provider("cerebras", "Cerebras", "cerebras", (r"csk-[a-z0-9]{20,}",),
             "https://api.cerebras.ai/v1/models", "bearer", "https://cloud.cerebras.ai"),
    Provider("fireworks", "Fireworks AI", "fireworks_ai", (r"fw_[A-Za-z0-9]{16,}",),
             "https://api.fireworks.ai/inference/v1/models", "bearer", "https://fireworks.ai/account/api-keys"),
    Provider("together", "Together AI", "together_ai", (r"tgp_v1_[\w-]{20,}", r"[a-f0-9]{64}"),
             "https://api.together.xyz/v1/models", "bearer", "https://api.together.ai/settings/api-keys"),
    Provider("mistral", "Mistral", "mistral", (r"[A-Za-z0-9]{32}",),
             "https://api.mistral.ai/v1/models", "bearer", "https://console.mistral.ai/api-keys"),
    Provider("ollama", "Ollama (bu PC)", "ollama_chat", (r"ollama", r"https?://[\w.:-]+:11434/?"),
             "/api/tags", "none", "https://ollama.com/download", "http://localhost:11434"),
)
BY_ID = {p.id: p for p in PROVIDERS}
# Komut satırı/sunucu kullanımı: ortam değişkeninden anahtar.
ENV_KEYS = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
            "openrouter": "OPENROUTER_API_KEY", "deepseek": "DEEPSEEK_API_KEY", "groq": "GROQ_API_KEY",
            "xai": "XAI_API_KEY", "cerebras": "CEREBRAS_API_KEY", "fireworks": "FIREWORKS_API_KEY",
            "together": "TOGETHER_API_KEY", "mistral": "MISTRAL_API_KEY", "ollama": "OLLAMA_API_BASE"}
BY_PREFIX = {p.prefix: p for p in PROVIDERS}

# Çeviri için işe yaramayan model türleri (adlarına göre).
_SKIP = re.compile(
    r"embed|tts|whisper|transcri|audio|realtime|speech|image|imagen|dall-e|veo|moderation|search|aqa|"
    r"nano-banana|computer-use|customtools|robotics|native-audio|live|guard|rerank|vision-only|sora|codex|babbage|davinci|"
    r"text-similarity|clip|ocr|-instruct$|^o1-mini|omni-moderation|learnlm|gemma-?\d*-?\d*b?-it$",
    re.I)


class KeyError_(RuntimeError):
    """Anahtar hiçbir sağlayıcıda çalışmadı."""


def guess(key: str) -> list[Provider]:
    """Anahtar biçimine uyan sağlayıcılar (en özgülden genele). Hiçbiri uymazsa boş: anahtar rastgele
    sağlayıcılara gönderilmez, kullanıcı hangisine ait olduğunu seçer."""
    key = key.strip()
    return [p for p in PROVIDERS if any(re.fullmatch(pat, key) for pat in p.patterns)]


class UnknownFormat(Exception):
    """Anahtarın biçimi hiçbir sağlayıcıya uymuyor: arayüz sağlayıcı seçtirir."""


def _headers(p: Provider, key: str) -> dict:
    if p.auth == "bearer":
        return {"Authorization": f"Bearer {key}"}
    if p.auth == "x-api-key":
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    if p.auth == "goog":
        return {"x-goog-api-key": key}
    return {}


def _base(p: Provider, key: str) -> str:
    if p.id == "ollama":
        return key.rstrip("/") if key.startswith("http") else p.base_url
    return ""


HttpGet = Callable[[str, dict], tuple[int, dict]]


def _http_get(url: str, headers: dict) -> tuple[int, dict]:
    from . import net

    r = net.get(url, headers=headers, timeout=20)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}


def _names(p: Provider, data: dict) -> list[str]:
    if p.id == "gemini":
        out = []
        for m in data.get("models") or []:
            acts = m.get("supportedGenerationMethods") or []
            name = (m.get("name") or "").removeprefix("models/")
            if "gemini" in name and (not acts or "generateContent" in acts):
                out.append(name)
        return out
    if p.id == "ollama":
        return [m.get("name", "") for m in data.get("models") or []]
    items = data.get("data") if isinstance(data.get("data"), list) else data.get("models") or []
    return [str(m.get("id") or m.get("name") or "") for m in items if isinstance(m, dict)]


def list_models(p: Provider, key: str, get: HttpGet | None = None) -> list[str]:
    """Sağlayıcının bu anahtarla erişilen sohbet modelleri, LiteLLM adlarıyla ve en iyiden kötüye sıralı.

    Anahtar geçersizse KeyError_ yükseltir.
    """
    url = (_base(p, key) + p.models_url) if p.id == "ollama" else p.models_url
    status, data = (get or _http_get)(url, _headers(p, key))
    if status in (401, 403) or (p.id == "gemini" and status == 400):
        raise KeyError_(f"{p.name} anahtarı kabul etmedi ({status})")
    if status >= 400:
        raise KeyError_(f"{p.name} model listesi alınamadı ({status})")
    names = [n for n in dict.fromkeys(_names(p, data)) if n and not _SKIP.search(n)]
    return rank([f"{p.prefix}/{n}" for n in names])


def detect(key: str, get: HttpGet | None = None, provider: str = "") -> tuple[Provider, list[str]]:
    """Anahtarın sağlayıcısını bulur ve erişilen modelleri döndürür. `provider` verilirse yalnız ona sorulur."""
    errors = []
    if provider:
        if provider not in BY_ID:
            raise KeyError_(f"Bilinmeyen sağlayıcı: {provider}")
        candidates = [BY_ID[provider]]
    else:
        candidates = guess(key)
        if not candidates:
            raise UnknownFormat("Anahtarın biçimi tanınmadı; hangi sağlayıcıya ait olduğunu seç.")
    for p in candidates:
        try:
            models = list_models(p, key, get)
        except KeyError_ as e:
            errors.append(str(e))
            continue
        except Exception as e:  # ağ hatası: sıradaki adayı dene
            errors.append(f"{p.name}: {type(e).__name__}")
            continue
        return p, models
    raise KeyError_("Anahtar tanınmadı ya da hiçbir sağlayıcıda çalışmadı. " + "; ".join(errors[:4]))


def provider_of(model: str) -> Provider:
    """'gemini/x' → Gemini; önek yoksa (eski ayarlar) Gemini."""
    prefix = model.split("/", 1)[0] if "/" in model else "gemini"
    return BY_PREFIX.get(prefix, BY_ID["gemini"])


def parse_or_empty(spec: str) -> list[str]:
    return [full_name(m.strip()) for m in (spec or "").replace(";", ",").split(",") if m.strip()]


def full_name(model: str) -> str:
    return model if "/" in model and model.split("/", 1)[0] in BY_PREFIX else f"gemini/{model}"


# --- sıralama: en iyiden en kötüye (ad sezgisi; arayüzde kullanıcı elle de sıralayabilir) ---
_TIERS = (  # (desen, puan) — ilk eşleşen
    (r"opus|argon|ultra|-pro\b|pro-|\bpro$|grok-\d+(?:\.\d+)?$|gpt-\d+(?:\.\d+)?$|^o\d$|-large|max\b|reasoner|405b", 8),
    (r"sonnet|carbon|gpt-\d+o\b|gpt-4\.1$|-medium|deepseek-chat|deepseek-v\d|70b|72b|plus|hydrogen|gpt-oss-120b", 6),
    (r"lite|nano|tiny|instant|\b[1-8]b\b|-[1-8]b-|small|haiku-3|mini-", 1),
    (r"haiku|mini|flash|turbo|small|fast|gpt-oss", 3),
)


def _version(name: str) -> float:
    m = re.search(r"(?:gemini|claude|gpt|grok|llama|qwen|mistral|deepseek|gemma|sonnet|opus|haiku|o)[-_ ]?(\d+(?:[.-]\d)?)",
                  name.lower())
    if not m:
        m = re.search(r"(\d+(?:\.\d+)?)", name)
    try:
        return float(m.group(1).replace("-", ".")) if m else 0.0
    except ValueError:
        return 0.0


def score(model: str) -> float:
    name = model.split("/", 1)[-1].lower()
    tier = next((pts for pat, pts in _TIERS if re.search(pat, name)), 4)
    s = _version(name) * 4 + tier  # sürüm önemli ama alt sınıf yeni sürüm üst sınıf eskiyi hep geçmesin
    if re.search(r"preview|exp|beta|alpha", name):
        s -= 0.5
    if re.search(r"latest", name):
        s -= 0.2  # takma ad: aynı sürümün sabit adı önde
    return s


def rank(models: list[str]) -> list[str]:
    """Sağlayıcı sırası korunur (ilk eklenen önce); her sağlayıcının modelleri en iyiden kötüye."""
    order = list(dict.fromkeys(provider_of(m).id for m in models))
    return sorted(models, key=lambda m: (order.index(provider_of(m).id), -score(m), m))
