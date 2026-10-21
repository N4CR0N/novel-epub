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
# Otomatik paketleme: bölümler, tahmini Türkçe çıktı token'ı bu bütçeye sığana kadar tek isteğe konur.
# Modelin yanıt tavanı ~65k token; düşünme payı ve güvenlik için hedef daha düşük tutulur. Kesik yanıtta
# bütçe küçülür, başarılı yanıtlarda yavaşça büyür.
OUTPUT_CAP = 65536
START_BUDGET = 24000
MIN_BUDGET = 8000
MAX_BUDGET = 40000
MAX_AUTO_CHAPTERS = 12
# Kaynak birimi başına Türkçe çıktı token'ı (başlangıç tahmini; gerçek kullanımdan öğrenilir).
# latin: İngilizce kelime başına, cjk: Çince/Japonca/Korece karakter başına.
START_RATIO = {"latin": 2.0, "cjk": 1.1}

CJK_RE = re.compile(r"[぀-ヿ㐀-鿿가-힯]")


class TranslationError(RuntimeError):
    pass


class QuotaExhausted(TranslationError):
    """Günlük kota bitti; beklemek anlamsız (saatler sürer)."""


class FatalError(TranslationError):
    """Devam etmenin anlamı yok (ör. geçersiz API anahtarı)."""


class TransientFailure(TranslationError):
    """Geçici hata (ağ, yoğunluk, bozuk yanıt) bekleyip denemelere rağmen sürdü."""


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
                 log: Callable[[str], None] = print, max_retries: int = 10):
        from google import genai  # geç içe aktarma: çeviri kapalıyken gerekmez

        if not api_key:
            raise FatalError("Gemini API anahtarı yok. Ayarlar'dan gir (aistudio.google.com/apikey).")
        self.client = genai.Client(api_key=api_key)
        self.models = parse_models(model or DEFAULT_MODELS)
        self.model = self.models[0]
        self.target = target
        self.log = log
        self.max_retries = max_retries
        self.sleep: Callable[[float], None] = time.sleep  # iş tarafı iptal edilebilir bekleme koyar
        self.thinking = True
        self.budget = START_BUDGET
        self.ratio = dict(START_RATIO)
        self.thought_tokens = 2000.0  # düşünme token'ı ortalaması (yanıt tavanından yer)
        self.last_usage: tuple[int, int] | None = None

    def _call(self, payload: dict, schema: dict = RESPONSE_SCHEMA, bad_retries: int | None = None) -> dict:
        """Her istek, kotası bitmemiş en iyi modelle başlar.

        Günlük kota dolan ya da kullanılamayan model listeden çıkar; hepsi biterse QuotaExhausted.
        Geçici hata bekleyip denemelere rağmen sürerse aynı istek sıradaki modelle denenir.
        """
        self.model = self.models[0]
        tried: set[str] = set()
        while True:
            try:
                return self._call_model(payload, schema, bad_retries)
            except QuotaExhausted as e:
                why = "kullanılamıyor" if isinstance(e, ModelUnusable) else "günlük kotası doldu"
                self.models.remove(self.model)
                if not self.models:
                    raise QuotaExhausted(f"Seçili modellerin hepsinin günlük kotası doldu (son: {e})") from e
                self.log(f"  {self.model} {why} → {self.models[0]} modeline geçiliyor")
                self.model = self.models[0]
            except TransientFailure:
                tried.add(self.model)
                others = [m for m in self.models if m not in tried]
                if not others:
                    raise
                self.log(f"  {self.model} ısrarla hata veriyor → bu istek {others[0]} ile deneniyor")
                self.model = others[0]

    def _config(self, schema: dict):
        from google.genai import types

        kw = dict(system_instruction=SYSTEM_PROMPT.format(target=self.target), response_mime_type="application/json",
                  response_schema=schema, temperature=0.6, max_output_tokens=65536)
        if self.thinking:
            # Düşünme token'ları çıktı sınırından yer; çeviride az düşünme yeterli.
            kw["thinking_config"] = types.ThinkingConfig(thinking_level="low")
        return types.GenerateContentConfig(**kw)

    def _call_model(self, payload: dict, schema: dict = RESPONSE_SCHEMA, bad_retries: int | None = None) -> dict:
        """Tek modelle istek. Geçici hatada bekler (en çok 60 sn) ve `max_retries` kez yeniden dener."""
        from google.genai import errors

        key = "chapters" if schema is BATCH_SCHEMA else "paragraphs"
        bad_left = 2 if bad_retries is None else bad_retries
        attempt = 0
        while True:
            reason, wait = "", None
            try:
                resp = self.client.models.generate_content(
                    model=self.model, contents=json.dumps(payload, ensure_ascii=False), config=self._config(schema))
                um = getattr(resp, "usage_metadata", None)
                self.last_usage = (getattr(um, "candidates_token_count", 0) or 0,
                                   getattr(um, "thoughts_token_count", 0) or 0) if um else None
                cands = getattr(resp, "candidates", None) or []
                if cands and "MAX_TOKENS" in str(getattr(cands[0], "finish_reason", "")):
                    raise ValueError("yanıt çıktı sınırında kesildi")
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
                if code in (400, 401, 403) and re.search(r"API.?key|permission|unauthenticated", str(e), re.I):
                    raise FatalError(f"API anahtarı geçersiz ya da yetkisiz: {str(e)[:160]}") from e
                if code == 429 and is_daily_quota(e):
                    raise QuotaExhausted(f"{self.model} günlük ücretsiz kotası doldu") from e
                if code == 400:
                    # Kalıcı olabilecek istek hatası: bozuk yanıt gibi say, birkaç kez dene.
                    if bad_left <= 0:
                        raise TransientFailure(f"Gemini 400: {str(e)[:200]}") from e
                    bad_left -= 1
                    reason, wait = f"istek hatası (400)", 10
                else:
                    m = re.search(r"retry in ([\d.]+)s", str(e), re.I)
                    wait = float(m.group(1)) + 1 if m else None
                    reason = f"API sınırı/yoğunluk ({code})"
            except (ValueError, json.JSONDecodeError) as e:
                if bad_left <= 0:
                    raise TransientFailure(f"Yanıt çözülemedi: {e}") from e
                bad_left -= 1
                reason, wait = f"bozuk yanıt ({e})", 5
            except Exception as e:  # ağ kopması, zaman aşımı vb.
                reason = f"bağlantı hatası ({type(e).__name__})"
            attempt += 1
            if attempt > self.max_retries:
                raise TransientFailure(f"{self.model}: {self.max_retries} denemede olmadı, son hata: {reason}")
            wait = min(60.0, wait if wait is not None else 10.0 * 2 ** (attempt - 1))
            self.log(f"  {reason} — {wait:.0f} sn bekleyip yeniden deneniyor ({attempt}/{self.max_retries})")
            self.sleep(wait)

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

    # --- otomatik paketleme ---
    @staticmethod
    def source_units(ch: Chapter) -> tuple[str, int]:
        """('latin', kelime sayısı) ya da ('cjk', CJK karakter sayısı)."""
        text = " ".join(ch.paragraphs)
        cjk = len(CJK_RE.findall(text))
        if cjk > len(text) * 0.3:
            return "cjk", cjk
        return "latin", len(text.split())

    def estimate_tokens(self, ch: Chapter) -> int:
        kind, n = self.source_units(ch)
        return int(n * self.ratio[kind]) + 60  # başlık + JSON payı

    def effective_budget(self) -> int:
        # Düşünme token'ları da yanıt tavanından yer; tavanı aşmayacak şekilde kırp.
        return int(min(self.budget, OUTPUT_CAP * 0.85 - self.thought_tokens))

    def plan_batch(self, pending: list[Chapter], max_chapters: int = 0) -> list[Chapter]:
        """Sıradaki ardışık bölümlerden tahmini çıktısı bütçeye sığanları seçer (en az 1)."""
        cap = max_chapters if max_chapters > 0 else MAX_AUTO_CHAPTERS
        budget = self.effective_budget()
        group, total = [pending[0]], self.estimate_tokens(pending[0])
        for ch in pending[1:cap]:
            est = self.estimate_tokens(ch)
            if ch.index != group[-1].index + 1 or total + est > budget:
                break
            group.append(ch)
            total += est
        self.log(f"  {group[0].index}–{group[-1].index}. bölümler tek istekte ({len(group)} bölüm, "
                 f"~{sum(self.source_units(c)[1] for c in group):,} kelime/karakter, tahmini ~{total:,} / {budget:,} token)")
        return group

    def learn(self, chs: list[Chapter], ok: bool) -> None:
        """Gerçek token kullanımından oranı ve bütçeyi günceller."""
        if not ok:
            self.budget = max(MIN_BUDGET, int(self.budget * 0.6))
            self.log(f"  istek bütçesi küçültüldü → {self.budget:,} token")
            return
        if self.last_usage:
            out_tok, thought = self.last_usage
            kind = self.source_units(chs[0])[0]
            units = sum(self.source_units(c)[1] for c in chs if self.source_units(c)[0] == kind)
            if units and out_tok:
                self.ratio[kind] = 0.7 * self.ratio[kind] + 0.3 * (out_tok / units)
            self.thought_tokens = 0.7 * self.thought_tokens + 0.3 * thought
        self.budget = min(MAX_BUDGET, int(self.budget * 1.1))

    def translate_batch(self, chs: list[Chapter], glossary: dict[str, str], context: list[str]) -> tuple[list[Chapter], dict[str, str]]:
        """Birden çok bölümü tek istekte çevirir (ücretsiz kota istek sayısıyla ölçülür).

        Yanıt kesik/eksik gelirse bölümler tek tek çevrilir; kota yine de boşa gitmez sayılır.
        """
        if len(chs) == 1:
            out, terms = self.translate_chapter(chs[0], glossary, context)
            self.learn(chs, ok=True)
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
                if sum(map(len, paras)) < 0.7 * c.char_count:
                    raise ValueError(f"{c.index}. bölüm eksik çevrilmiş")
                result.append(Chapter(c.index, (o.get("title") or c.title).strip(), c.url, paras))
        except (QuotaExhausted, FatalError):
            raise
        except (TranslationError, ValueError) as e:
            self.log(f"  Toplu çeviri olmadı ({e}); bölümler tek tek çevriliyor")
            self.learn(chs, ok=False)
            result, terms, ctx = [], {}, context
            for c in chs:
                try:
                    out, t = self.translate_chapter(c, {**glossary, **terms}, ctx)
                except QuotaExhausted:
                    if result:
                        return result, terms  # bitenler kaybolmasın; kota durumu sonraki istekte yine çıkar
                    raise
                except FatalError:
                    raise
                except TranslationError as e2:
                    self.log(f"  {c.index}. bölüm çevrilemedi, atlanıyor ({e2})")
                    continue
                result.append(out)
                terms.update(t)
                ctx = out.paragraphs[-4:]
            return result, terms
        self.learn(chs, ok=True)
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
