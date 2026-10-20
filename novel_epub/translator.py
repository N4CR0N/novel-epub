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

CJK_RE = re.compile(r"[぀-ヿ㐀-鿿가-힯]")


class TranslationError(RuntimeError):
    pass


class QuotaExhausted(TranslationError):
    """Günlük kota bitti; beklemek anlamsız (saatler sürer)."""


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

    def _call(self, payload: dict) -> dict:
        """Kota dolarsa sıradaki modele geçer; hepsi dolmuşsa QuotaExhausted fırlatır."""
        while True:
            try:
                return self._call_model(payload)
            except QuotaExhausted:
                rest = self.models[self.models.index(self.model) + 1:]
                if not rest:
                    raise
                self.log(f"  {self.model} günlük kotası doldu → {rest[0]} modeline geçiliyor")
                self.model = rest[0]

    def _call_model(self, payload: dict) -> dict:
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT.format(target=self.target),
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
            temperature=0.6,
        )
        delay = 10.0
        for attempt in range(self.max_retries):
            try:
                resp = self.client.models.generate_content(
                    model=self.model, contents=json.dumps(payload, ensure_ascii=False), config=config)
                data = json.loads(resp.text or "{}")
                if not isinstance(data.get("paragraphs"), list):
                    raise ValueError("yanıtta paragraphs yok")
                return data
            except errors.APIError as e:
                code = getattr(e, "code", 0) or 0
                if code == 404:
                    raise TranslationError(f"Model bulunamadı: {self.model}. Ayarlar'dan başka model seç.") from e
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
                if attempt < self.max_retries - 1:
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
