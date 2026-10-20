"""Gemini ile edebi çeviri.

- Bölüm, paragraf sınırları korunarak parçalara bölünür; her parça JSON (paragraf dizisi) olarak döner.
- Terim sözlüğü (isimler, kültivasyon kademeleri, teknikler) her parçada verilir ve model yeni
  terimleri bildirdikçe büyür; böylece aynı terim kitap boyunca aynı kalır.
- Önceki parçanın son paragrafları bağlam olarak verilir (zamir/özne sürekliliği için).
"""
from __future__ import annotations

import json
import re
import time
from typing import Callable

from .models import Chapter

DEFAULT_MODEL = "gemini-flash-latest"
# Ücretsiz katmanda günlük kota model başına ayrı sayılır; biri dolunca sıradakine geçilir.
DEFAULT_MODELS = "gemini-flash-latest, gemini-flash-lite-latest"

SYSTEM_PROMPT = """Sen web novel (Çin xianxia/xuanhuan/wuxia, Japon light novel, Kore web romanı) ve fantastik edebiyat konusunda uzman, yayınevi kalitesinde çalışan bir edebi çevirmensin. Verilen paragrafları {target} diline çevir.

Kurallar:
1. Akıcı, doğal, edebi bir {target} kullan; kelime kelime değil, anlamı ve üslubu aktar. Cümleler {target} söz dizimine uysun.
2. Hiçbir şeyi atlama, özetleme, ekleme ya da yorumlama. Çevirmen notu yazma.
3. Kişi ve yer adlarını çevirme; Çince adları pinyin olarak, Japonca adları Hepburn romanizasyonuyla yaz. İngilizce kaynaktaki adları aynen bırak.
4. Japonca hitap eklerini (-san, -sama, -kun, senpai) koru. Çince unvanları (Shizun, Shixiong vb.) sözlükte nasılsa öyle kullan.
5. Kültivasyon kademeleri, teknik/yetenek/hazine adları, mezhep adları gibi özel terimleri anlamlı ve tutarlı biçimde çevir. "glossary" alanındaki karşılıkları MUTLAKA aynen kullan.
6. Öznesi düşük (Çince/Japonca) cümlelerde özneyi "context" ve akıştan çıkar; Türkçe şahıs ekleriyle doğru kur.
7. Diyalogları doğal, karaktere uygun konuşma diliyle çevir; tırnakları koru.
8. Her girdi paragrafı için TAM OLARAK bir çıktı paragrafı üret, sıra aynı kalsın. "paragraphs" dizisinin uzunluğu girdidekiyle eşit olmalı.
9. Metinde geçen ve sözlükte olmayan yeni özel terimleri (kişi adları hariç; unvan, kademe, teknik, eşya, mezhep, yer adı) "new_terms" listesinde kaynak hâli ve seçtiğin karşılıkla bildir. Yoksa boş liste ver.
10. Metindeki site reklamı/filigran satırlarını boş dize olarak döndür.
11. Bölüm başlıklarında "Book N Chapter M" / "Volume N" kalıbını hep "Cilt N Bölüm M" biçiminde çevir.
12. Girdide "chapters" listesi varsa her bölümü aynı sırayla ayrı bir çıktı bölümü olarak ver; bölümleri birleştirme, bölme ya da atlama. Her bölümde kural 8 ayrıca geçerlidir.
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "paragraphs": {"type": "array", "items": {"type": "string"}},
        "new_terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"source": {"type": "string"}, "target": {"type": "string"}},
                "required": ["source", "target"],
            },
        },
    },
    "required": ["title", "paragraphs", "new_terms"],
}

_TERMS_SCHEMA = RESPONSE_SCHEMA["properties"]["new_terms"]
BATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "chapters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "paragraphs": {"type": "array", "items": {"type": "string"}}},
                "required": ["title", "paragraphs"],
            },
        },
        "new_terms": _TERMS_SCHEMA,
    },
    "required": ["chapters", "new_terms"],
}
# Tek istekte gönderilecek en fazla kaynak karakter (çıktı token sınırı ~65k; Türkçe çıktı + düşünme payı).
BATCH_CHAR_LIMIT = {"latin": 60000, "cjk": 20000}

CJK_RE = re.compile(r"[぀-ヿ㐀-鿿가-힯]")


class TranslationError(RuntimeError):
    pass


class QuotaExhausted(TranslationError):
    """Günlük kota bitti; beklemek anlamsız (saatler sürer)."""


class ModelUnusable(QuotaExhausted):
    """Model yok ya da bu iş için gereken özelliği (JSON şeması, sistem talimatı) desteklemiyor."""


def parse_models(spec: str) -> list[str]:
    models = [m.strip() for m in (spec or "").replace(";", ",").split(",") if m.strip()]
    return list(dict.fromkeys(models)) or [DEFAULT_MODEL]


def is_daily_quota(err: Exception) -> bool:
    text = str(err)
    if "PerDay" in text or "per day" in text.lower():
        return True
    m = re.search(r"retryDelay'?\"?:\s*'?\"?(\d+)s", text)
    return bool(m and int(m.group(1)) > 600)


def chunk_paragraphs(paragraphs: list[str], budget: int) -> list[list[str]]:
    chunks, cur, size = [], [], 0
    for p in paragraphs:
        if cur and size + len(p) > budget:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(p)
        size += len(p)
    if cur:
        chunks.append(cur)
    return chunks


def relevant_glossary(glossary: dict[str, str], text: str, limit: int = 300) -> dict[str, str]:
    low = text.lower()
    hits = {k: v for k, v in glossary.items() if k.lower() in low}
    return dict(list(hits.items())[:limit])


class GeminiTranslator:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, target: str = "Türkçe",
                 log: Callable[[str], None] = print, max_retries: int = 6):
        from google import genai  # geç içe aktarma: çeviri kapalıyken gerekmez

        if not api_key:
            raise TranslationError("Gemini API anahtarı yok. Ayarlar'dan gir (aistudio.google.com/apikey).")
        self.client = genai.Client(api_key=api_key)
        self.models = parse_models(model or DEFAULT_MODELS)
        self.model = self.models[0]
        self.target = target
        self.log = log
        self.max_retries = max_retries
        self.thinking = True

    def _call(self, payload: dict, schema: dict = RESPONSE_SCHEMA, bad_retries: int | None = None) -> dict:
        """Kota dolarsa sıradaki modele geçer; hepsi dolmuşsa QuotaExhausted fırlatır."""
        while True:
            try:
                return self._call_model(payload, schema, bad_retries)
            except QuotaExhausted as e:
                rest = self.models[self.models.index(self.model) + 1:]
                if not rest:
                    raise
                why = "kullanılamıyor" if isinstance(e, ModelUnusable) else "günlük kotası doldu"
                self.log(f"  {self.model} {why} → {rest[0]} modeline geçiliyor")
                self.model = rest[0]

    def _config(self, schema: dict):
        from google.genai import types

        kw = dict(system_instruction=SYSTEM_PROMPT.format(target=self.target), response_mime_type="application/json",
                  response_schema=schema, temperature=0.6, max_output_tokens=65536)
        if self.thinking:
            # Düşünme token'ları çıktı sınırından yer; çeviride az düşünme yeterli.
            kw["thinking_config"] = types.ThinkingConfig(thinking_level="low")
        return types.GenerateContentConfig(**kw)

    def _call_model(self, payload: dict, schema: dict = RESPONSE_SCHEMA, bad_retries: int | None = None) -> dict:
        from google.genai import errors

        key = "chapters" if schema is BATCH_SCHEMA else "paragraphs"
        bad_left = self.max_retries - 1 if bad_retries is None else bad_retries
        delay = 10.0
        for attempt in range(self.max_retries):
            try:
                resp = self.client.models.generate_content(
                    model=self.model, contents=json.dumps(payload, ensure_ascii=False), config=self._config(schema))
                data = json.loads(resp.text or "{}")
                if not isinstance(data.get(key), list):
                    raise ValueError(f"yanıtta {key} yok")
                return data
            except errors.APIError as e:
                code = getattr(e, "code", 0) or 0
                if code == 400 and self.thinking and "think" in str(e).lower():
                    self.thinking = False  # bu model düşünme ayarını desteklemiyor
                    continue
                if code == 404:
                    raise ModelUnusable(f"Model bulunamadı: {self.model}") from e
                if code == 400 and re.search(r"not (supported|enabled|available)|unsupported", str(e), re.I):
                    raise ModelUnusable(f"{self.model} bu işi desteklemiyor: {str(e)[:160]}") from e
                if code in (400, 401, 403) and "API key" in str(e):
                    raise TranslationError("API anahtarı geçersiz.") from e
                if code == 429 and is_daily_quota(e):
                    raise QuotaExhausted(f"{self.model} günlük ücretsiz kotası doldu") from e
                if code in (429, 500, 503, 504) and attempt < self.max_retries - 1:
                    m = re.search(r"retry in ([\d.]+)s", str(e), re.I)
                    wait = float(m.group(1)) + 1 if m else delay
                    self.log(f"  API sınırı/yoğunluk ({code}), {wait:.0f} sn bekleniyor…")
                    time.sleep(wait)
                    delay = min(delay * 2, 120)
                    continue
                raise TranslationError(f"Gemini hatası: {e}") from e
            except (ValueError, json.JSONDecodeError) as e:
                if bad_left > 0:
                    bad_left -= 1
                    self.log(f"  Bozuk yanıt, yeniden deneniyor ({e})")
                    time.sleep(3)
                    continue
                raise TranslationError(f"Yanıt çözülemedi: {e}") from e
        raise TranslationError("Çeviri denemeleri tükendi")

    def translate_chapter(self, ch: Chapter, glossary: dict[str, str], context: list[str]) -> tuple[Chapter, dict[str, str]]:
        """Bölümü çevirir; (çevrilmiş bölüm, yeni terimler) döndürür. `context` önceki çeviri paragraflarıdır."""
        # Büyük parça = az istek (ücretsiz kota istek sayısıyla ölçülür). Tipik İngilizce bölüm tek istekte gider.
        budget = 8000 if CJK_RE.search(" ".join(ch.paragraphs[:5])) else 24000
        chunks = chunk_paragraphs(ch.paragraphs, budget)
        out_paras: list[str] = []
        new_terms: dict[str, str] = {}
        title = ch.title
        ctx = list(context[-4:])
        for i, chunk in enumerate(chunks):
            text = " ".join(chunk)
            gl = {**relevant_glossary(glossary, text + " " + ch.title), **relevant_glossary(new_terms, text)}
            payload = {
                "chapter_title": ch.title if i == 0 else "",
                "glossary": gl,
                "context": ctx,
                "paragraphs": chunk,
            }
            data = self._call(payload)
            paras = [str(p).strip() for p in data["paragraphs"]]
            if len(paras) != len(chunk):
                # Paragraf sayısı tutmadı; metin boyu makulse kabul et, değilse bir kez daha dene.
                ratio = sum(map(len, paras)) / max(1, len(text))
                if ratio < 0.5:
                    self.log(f"  Parça {i + 1}: eksik çeviri sezildi, yeniden deneniyor")
                    data = self._call(payload)
                    paras = [str(p).strip() for p in data["paragraphs"]]
            if i == 0 and data.get("title"):
                title = data["title"].strip()
            for t in data.get("new_terms") or []:
                s, tr = (t.get("source") or "").strip(), (t.get("target") or "").strip()
                if s and tr and s not in glossary and len(s) <= 60:
                    new_terms[s] = tr
            paras = [p for p in paras if p]
            out_paras.extend(paras)
            ctx = (ctx + paras)[-4:]
        return Chapter(ch.index, title, ch.url, out_paras), new_terms

    def batch_limit(self, ch: Chapter) -> int:
        return BATCH_CHAR_LIMIT["cjk" if CJK_RE.search(" ".join(ch.paragraphs[:5])) else "latin"]

    def translate_batch(self, chs: list[Chapter], glossary: dict[str, str], context: list[str]) -> tuple[list[Chapter], dict[str, str]]:
        """Birden çok bölümü tek istekte çevirir (ücretsiz kota istek sayısıyla ölçülür).

        Yanıt kesik/eksik gelirse bölümler tek tek çevrilir; kota yine de boşa gitmez sayılır.
        """
        if len(chs) == 1:
            out, terms = self.translate_chapter(chs[0], glossary, context)
            return [out], terms
        text = " ".join(" ".join(c.paragraphs) for c in chs)
        payload = {
            "glossary": relevant_glossary(glossary, text + " " + " ".join(c.title for c in chs)),
            "context": list(context[-4:]),
            "chapters": [{"chapter_title": c.title, "paragraphs": c.paragraphs} for c in chs],
        }
        try:
            data = self._call(payload, BATCH_SCHEMA, bad_retries=0)
            outs = data["chapters"]
            if len(outs) != len(chs):
                raise ValueError(f"{len(chs)} bölüm gitti, {len(outs)} döndü")
            result = []
            for c, o in zip(chs, outs):
                paras = [p for p in (str(x).strip() for x in o.get("paragraphs") or []) if p]
                if sum(map(len, paras)) < 0.5 * c.char_count:
                    raise ValueError(f"{c.index}. bölüm eksik çevrilmiş")
                result.append(Chapter(c.index, (o.get("title") or c.title).strip(), c.url, paras))
        except QuotaExhausted:
            raise
        except (TranslationError, ValueError) as e:
            self.log(f"  Toplu çeviri olmadı ({e}); bölümler tek tek çevriliyor")
            result, terms, ctx = [], {}, context
            for c in chs:
                out, t = self.translate_chapter(c, {**glossary, **terms}, ctx)
                result.append(out)
                terms.update(t)
                ctx = out.paragraphs[-4:]
            return result, terms
        terms = {}
        for t in data.get("new_terms") or []:
            src, tgt = (t.get("source") or "").strip(), (t.get("target") or "").strip()
            if src and tgt and src not in glossary and len(src) <= 60:
                terms[src] = tgt
        return result, terms


def list_models(api_key: str) -> list[str]:
    from google import genai

    client = genai.Client(api_key=api_key)
    names = []
    for m in client.models.list():
        actions = getattr(m, "supported_actions", None) or []
        name = (m.name or "").removeprefix("models/")
        if "gemini" in name and (not actions or "generateContent" in actions):
            names.append(name)
    return sorted(set(names))
