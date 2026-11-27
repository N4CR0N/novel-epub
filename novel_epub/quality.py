"""Çeviri kalite denetimi.

Çeviri bittikten (ve redakte edildikten) sonra her bölüme uygulanır; bitmiş kitaplar için "Çeviriyi denetle ve
düzelt" de aynısını yapar. İki tür düzeltme var:
- kesin kurallar (kodla): bölüm başlığı kalıbı ("Chapter 700 X" → "Bölüm 700: X"; uydurulmuş "Cilt" yok), seviye
  kısaltması ("Lv. 10" / "Sv. 10" → "Seviye 10");
- modelle onarılacak paragraflar: kaynak dilde kalmış kelime ("Dean Ming", "Spacetime Island"), sözlüğe uymayan terim,
  eski/ağdalı Türkçe ("talebe", "ekseriyet", "muvaffak olamaz"), kaynağa göre çok kısa kalmış (eksik) paragraf.
"""
from __future__ import annotations

import functools
import re

from .models import Chapter

QUALITY_VERSION = 2  # denetim kuralları değişince artır: bitmiş kitaplar yeniden denetlenebilir

# --- eski / ağdalı Türkçe ---------------------------------------------------------------------------------------
# Kalıp (kelime başı, ekleri kapsar) → bugünkü karşılık önerisi. Yalnız anlamı tek ve kesin eski olanlar; "vakit",
# "nihayet", "dehşet", "kudret" gibi bugün de doğal kullanılanlar yok.
ARCHAIC_TR: dict[str, str] = {
    r"talebe": "öğrenci",
    r"ekseriyet": "çoğunluk / çoğu",
    r"ekseriya": "çoğunlukla",
    r"muvaffak": "başarmak / başarılı",
    r"add(?:et|ed|eder|edil)": "saymak / sayılmak",
    r"icra (?:et|ed|eder|edil)": "yapmak / uygulamak",
    r"kaide(?:ler|si|leri|ye|yi)?\b": "kural",
    r"hakiki": "gerçek",
    r"tesir": "etki",
    r"vakıf(?:tı|tır|tım|tın|tık|olmak)": "iyi bilmek / hâkim olmak",
    r"takatsiz": "güçsüz / bitkin",
    r"idrak": "algı / kavrayış",
    r"fevkalade": "son derece / olağanüstü",
    r"k[âa]fi\b|k[âa]fi (?:derece|gel)": "yeterli",
    r"istirahat": "dinlenmek",
    r"gelgelelim": "ama / ne var ki",
    r"mütemadiyen": "sürekli",
    r"mukavemet": "direnç / dayanıklılık",
    r"ziyade(?:siyle)?\b": "fazla / daha çok",
    r"bilakis": "tersine",
    r"zira\b": "çünkü",
    r"binaenaleyh": "bu yüzden",
    r"keza\b": "aynı şekilde",
    r"vaziyet": "durum",
    r"ehemmiyet": "önem",
    r"mühim": "önemli",
    r"mahsus\b": "özel / ait",
    r"hususi": "özel",
    r"husus(?:ta|unda|u|lar)?\b": "konu",
    r"lüzum": "gerek",
    r"malumat": "bilgi",
    r"mevcudiyet": "varlık",
    r"muhtelif": "çeşitli",
    r"müteakip": "sonraki / ardından",
    r"kifayet": "yetmek / yeterlilik",
    r"sarih": "açık",
    r"mevzu": "konu",
    r"mektep": "okul",
    r"muallim": "öğretmen",
    r"şakirt": "öğrenci",
    r"lakin\b": "ama / ancak",
    r"velhasıl": "kısacası",
    r"maharet": "beceri / ustalık",
    r"beyhude": "boşuna",
    r"mamafih": "yine de",
    r"evvela": "önce",
    r"tatbik": "uygulamak",
    r"mesken": "ev / yuva",
    r"sükûnet|sükunet|sükût": "sessizlik / sakinlik",
    r"metanet": "dayanıklılık / soğukkanlılık",
    r"hiddet": "öfke",
    r"teşebbüs": "girişim",
    r"akılalmaz": "inanılmaz",
    r"çarçabuk": "hemen / çabucak",
    r"ahali": "halk",
    r"bihaber": "habersiz",
    r"haiz\b": "sahip",
    r"suretle\b|surette\b": "biçimde",
    r"nazaran": "göre",
    r"hasebiyle": "yüzünden / nedeniyle",
    r"iptidai": "ilkel",
}
_ARCHAIC = [(re.compile(r"(?<![\wçğıöşüâîû])" + k, re.I), v) for k, v in ARCHAIC_TR.items()]


def archaic_words(text: str) -> list[tuple[str, str]]:
    """Metindeki eski/ağdalı kelimeler: [(bulunan kelime, önerilen karşılık)]."""
    found: dict[str, str] = {}
    for rx, repl in _ARCHAIC:
        for m in rx.finditer(text):
            end = m.end()
            while end < len(text) and (text[end].isalpha()):
                end += 1
            found.setdefault(text[m.start():end], repl)
    return list(found.items())


# --- kaynak dilde (İngilizce) kalmış kelimeler -------------------------------------------------------------------
# Web novel adlarında/unvanlarında sık geçen sıradan İngilizce kelimeler (kaynakta yalnız büyük harfle geçseler de
# çevrilmeleri gerekir: "Dean Ming" → "Dekan Ming", "Spacetime Island" → "Uzay-Zaman Adası").
COMMON_EN = set("""
dean senior junior elder master lord lady king queen prince princess emperor empress duke marquis count baron
sir madam miss mister teacher student disciple patriarch matriarch matron butler steward guard general captain
commander soldier warrior gladiator hunter knight saint sage immortal god goddess devil demon demonic fiend ghost
monster beast dragon tiger phoenix snake python serpent wolf fox bear eagle hawk crane bird avian turtle spider
island isle lake mountain mountains hill peak cliff valley canyon river stream spring sea ocean bay coast shore
forest wood woods tree trees flower leaf lotus root city town village capital kingdom empire nation state province
district region zone sector territory dominion domain realm world worlds land lands earth sky heaven heavens
heavenly hell abyss abyssal void chaos origin primordial eternal ancient ancestral divine holy sacred
infinite myriad supreme grand great true false first second third fourth fifth one two three four five six seven
eight nine ten hundred thousand million star stars sun moon planet planetary galaxy universe cosmic cosmos space
spacetime time fire flame water wind thunder lightning ice frost snow cloud clouds rain mist storm light dark
darkness shadow shadows blood bone bones soul spirit heart mind body death life dream illusion black white red
blue green yellow purple golden gold silver iron steel jade crystal stone gem pearl sword blade spear saber
fist palm finger foot feet hand eye eyes art arts technique scripture sutra manual scroll pill elixir treasure
gate tower palace temple hall pavilion house building court academy school college university sect clan family
alliance league union group team army legion guild company society order church
battle war fight sparring duel kill kills killing slaughter hunt nest feather boat ship shield arrow bow
inch punch kick poking escaping hidden secret broken lost fallen rising flying dancing burning frozen
tempering refining cultivation cultivate cultivator realm stage level grade rank
connoisseur transcendent ultimate perfected entity lifeform being vast provoke bandit broker rapier
""".split())

# Türkçede de aynen kullanılan ya da Türkçe bir kelimeyle aynı yazılan kelimeler: kaynak dilde kalmış sayılmaz.
TR_SAME = set("""
normal modern test plan ideal metal program video alarm park pilot organ mutant transfer karma robot radar risk
platform form minimum maksimum oval mineral arena tsunami meteor veto internet viral tablet villa lotus aura kendo
yuan tael kcal general total final bonus mega ultra data atom proton elektron virus bakteri doktor profesör
salon film pasta pizza kanal ton kilo metre gram kalori modül model status avatar kart sistem enerji motor
size bile gene tire fare kale alan bale dere kara sade hala nine anne mama papa baba sana dana pare rota
lord
""".split())

# Unvan kelimeleri: ad öbeğinde geçse de çevrilir ("Dean Ming" → "Dekan Ming"). Unvan olmayan sıradan bir kelime bir
# karakter adının parçasıysa ("Tiger Fussen", robot "Five") ad sayılır ve aynen kalır.
TITLE_EN = set("""
dean senior junior elder master lord lady king queen prince princess emperor empress duke marquis count baron sir
madam miss mister teacher student disciple patriarch matriarch matron butler steward guard general captain commander
overlord saint sage old young little big first second third fourth fifth sixth seventh eighth ninth tenth
mr mrs ms dr
""".split())


def _is_person_name(key: str, target: str) -> bool:
    """Sözlükte aynen bırakılmış kişi adı mı ("Tiger Fussen" → "Tiger Fussen"): unvansız ve en az bir kelimesi
    sıradan İngilizce kelime değil. ("Feather Fire City" gibi tamamı sıradan kelime olan yer adları sayılmaz.)"""
    words = re.findall(r"[A-Za-z]{2,}", key)
    return (key == target and bool(words) and not any(w.lower() in TITLE_EN for w in words)
            and any(w.lower() not in COMMON_EN for w in words if len(w) >= 3))


def name_words(characters, glossary: dict[str, str] | None = None) -> set[str]:
    """Karakter adlarındaki (ve sözlükte aynen bırakılmış kişi adlarındaki) unvan olmayan kelimeler (küçük harf):
    bunlar kaynak dilde kalmış sayılmaz."""
    out = set()
    for k, v in (glossary or {}).items():
        if _is_person_name(k, v):
            out.update(w.lower() for w in re.findall(r"[A-Za-z]{3,}", k))
    for name in characters or ():
        words = re.findall(r"[A-Za-z]{3,}", str(name))
        if any(w.lower() in TITLE_EN for w in words):
            words = [w for w in words if w.lower() not in TITLE_EN and w.lower() not in COMMON_EN]
        out.update(w.lower() for w in words)
    return out


def restore_names(glossary: dict[str, str], characters) -> dict[str, str]:
    """Sözlükte yanlışlıkla çevrilmiş kişi adları ("Tiger Fussen" → "Kaplan Fussen"): adın aynen kalması gereken
    kayıtlar (unvansız, kaynakta karakter olarak geçen). {terim: ad} döndürür."""
    names = {str(n) for n in characters or ()}
    out = {}
    for k, v in glossary.items():
        words = re.findall(r"[A-Za-z]{2,}", k)
        if k in names and v != k and words and not any(w.lower() in TITLE_EN for w in words) \
                and any(w.lower() not in COMMON_EN for w in words) and any(w in v for w in words):
            out[k] = k
    return out


_WORD = re.compile(r"(?<![\wçğıöşüâîûÇĞİÖŞÜ'’])([A-Za-z]{3,})(?![\wçğıöşüâîûÇĞİÖŞÜ])")


def source_vocab(chapters: list[Chapter]) -> set[str]:
    """Kaynak metinde küçük harfle geçen kelimeler: sıradan (özel ad olmayan) kelimelerin listesi."""
    vocab: set[str] = set()
    for c in chapters:
        vocab.update(re.findall(r"\b[a-z]{3,}\b", " ".join(c.paragraphs)))
    return vocab


def _kept_words(glossary: dict[str, str], vocab: set[str]) -> set[str]:
    """Sözlük karşılıklarında bilerek aynen bırakılmış adlar (sıradan kelime olmayanlar)."""
    out = set()
    for v in glossary.values():
        for w in re.findall(r"[A-Za-z]{3,}", v):
            lw = w.lower()
            if lw not in COMMON_EN and lw not in vocab:
                out.add(lw)
    return out


_LAUGH = re.compile(r"^(?:h[aeiou]|[aeiou]h|hm+|mm+|u+h|o+h|a+h)+h?$", re.I)


def leftover_english(src_text: str, out_text: str, vocab: set[str], kept: set[str] = frozenset()) -> list[str]:
    """Çeviride kaynak dilde kalmış sıradan kelimeler. Bir kelime ya unvan/ad öbeklerinde sık geçen sıradan bir
    kelimedir (COMMON_EN: Dean, Island, Realm…) ve kaynakta geçer, ya da kaynakta küçük harfle sıradan kelime olarak
    geçer (dominion, sparring). Kaynakta yalnız büyük harfle geçen öteki kelimeler ad sayılır (Ming, Pang, Yang)."""
    src_low = src_text.lower()
    found = []
    for w in dict.fromkeys(m.group(1) for m in _WORD.finditer(out_text)):
        lw = w.lower()
        if lw in TR_SAME or lw in kept or _LAUGH.match(lw) or len(lw) < 4 and lw not in ("sea", "sky", "art", "war", "ice"):
            continue
        pat = r"(?<![A-Za-z])" + re.escape(lw) + r"(?![A-Za-z])"
        if lw in COMMON_EN and re.search(pat, src_low) or re.search(pat, src_text):
            found.append(w)
    return found


def suspicious_glossary(glossary: dict[str, str], vocab: set[str]) -> dict[str, str]:
    """Karşılığında İngilizce sıradan kelime kalmış sözlük kayıtları ("Feather Fire City", "Abyssal Ana Kan")."""
    bad = {}
    for k, v in glossary.items():
        if _is_person_name(k, v):  # kişi adı: aynen kalır
            continue
        kw = {w.lower() for w in re.findall(r"[A-Za-z]{3,}", k)}
        left = [w for w in re.findall(r"[A-Za-z]{3,}", v)
                if w.lower() in kw and w.lower() not in TR_SAME and (w.lower() in COMMON_EN or w.lower() in vocab)]
        if left or archaic_words(v):  # karşılığı eski kelimeyle kurulmuş terim de ("İptidai Yıldız") düzeltilir
            bad[k] = v
    return bad


def _stems(target: str) -> list[str]:
    """Sözlük karşılığının çekim ekinden bağımsız aranacak kökleri: 'Milyar Yıldız Adası' → milyar, yıldız, ada."""
    out = []
    for w in re.findall(r"[^\W\d_]+", target.replace("İ", "i").replace("I", "ı").lower()):
        if len(w) <= 3:
            continue
        out.append(w[: max(4, len(w) - 3)] if len(w) > 5 else w[:4])
    return out


def glossary_misses(src_par: str, out_par: str, glossary: dict[str, str]) -> list[tuple[str, str]]:
    """Kaynak paragrafta geçen sözlük terimleri çeviride sözlükteki karşılığıyla geçmiyorsa: [(terim, karşılık)]."""
    if not glossary:
        return []
    low_src = src_par.lower()
    low_out = out_par.replace("İ", "i").replace("I", "ı").lower()
    misses = []
    for k, v in glossary.items():
        if len(k) < 4 or k.lower() not in low_src:
            continue
        if not re.search(r"(?<![a-z])" + re.escape(k.lower()) + r"(?![a-z])", low_src):
            continue
        stems = _stems(v)
        if stems and not all(s in low_out for s in stems):
            misses.append((k, v))
    # uzun terim kısa terimi kapsıyorsa (ör. "North River Boat Master" ⊃ "North River Boat") yalnız uzunu yaz
    return [(k, v) for k, v in misses if not any(k != k2 and k.lower() in k2.lower() for k2, _ in misses)]


# --- kesin düzeltmeler ---------------------------------------------------------------------------------------------
_LEVEL = re.compile(r"(?<![\wçğıöşü])(?:Lv|LV|Lvl|Sv)\.?\s?(?=\d)|(?<![\wçğıöşü])Level\s(?=\d)")


def fix_levels(text: str) -> str:
    """'Lv. 10', 'Sv. 3', 'Level 5' → 'Seviye 10' (yalnız Türkçe çıktıda)."""
    return _LEVEL.sub("Seviye ", text)


TITLE_WORDS = {  # dil → (cilt, bölüm)
    "tr": ("Cilt", "Bölüm"), "en": ("Volume", "Chapter"), "de": ("Band", "Kapitel"), "fr": ("Tome", "Chapitre"),
    "es": ("Volumen", "Capítulo"), "it": ("Volume", "Capitolo"), "pt": ("Volume", "Capítulo"),
    "ru": ("Том", "Глава"), "uk": ("Том", "Розділ"), "pl": ("Tom", "Rozdział"), "nl": ("Deel", "Hoofdstuk"),
    "id": ("Jilid", "Bab"), "az": ("Cild", "Fəsil"),
}
_SRC_TITLE = re.compile(
    r"^\s*(?:(?:Book|Volume|Vol\.?)\s*(?P<vol>\d+)\s*[,:\-–—.]?\s*)?(?:Chapter|Ch\.?)\s*(?P<num>\d+)\s*[:\-–—.]?\s*(?P<rest>.*)$",
    re.I)
_SRC_TITLE_CJK = re.compile(r"^\s*第\s*(?P<num>\d+)\s*[章话話回]\s*[:：\-–—.]?\s*(?P<rest>.*)$")
_PREFIX_WORDS = {w.lower() for pair in TITLE_WORDS.values() for w in pair} | {
    "kitap", "book", "vol", "chapter", "ch", "bölüm"}


def _subtitle(title: str, num: str, vol: str | None) -> str:
    """Çevrilmiş başlıktan baştaki 'Cilt 7 Bölüm 709:' gibi numara kısmını atar; alt başlık kalır.
    Numara yalnız bölüm/cilt numarasıysa ya da 'Cilt/Kitap' kelimesinin hemen ardındaysa atılır ('100 Yıllık Kira' kalır)."""
    rest = re.sub(r"^((?:Cilt|Kitap|Volume|Book)\s*\d+)\s+(?:ve|and)\s+(?=(?:Bölüm|Chapter)\b)", r"\1 ", title.strip())
    rest = re.sub(r"^第\s*\d+\s*[章话話回]\s*", "", rest)
    after_vol_word = False
    while rest:
        m = re.match(r"^([^\W\d_]+\.?)\s*", rest)
        if m and m.group(1).lower().rstrip(".") in _PREFIX_WORDS | {"cilt", "volume", "tome", "band", "том"}:
            after_vol_word = m.group(1).lower().rstrip(".") in ("cilt", "kitap", "book", "volume", "vol", "tome", "band", "том", "tom", "deel", "jilid", "cild")
            rest = rest[m.end():]
            continue
        m = re.match(r"^(\d+|N(?=\s+(?:Bölüm|Cilt|Chapter)\b)|N(?=\s|$))\b\s*", rest)  # "Cilt N" yer tutucusu da atılır
        if m and (m.group(1) in (num, vol, "N") and (m.group(1) != "N" or after_vol_word or re.match(r"N\s+(?:Bölüm|Cilt|Chapter)\b", rest)) or after_vol_word):
            after_vol_word = False
            rest = rest[m.end():]
            continue
        m = re.match(r"^[:\-–—.,]\s*", rest)
        if m:
            rest = rest[m.end():]
            continue
        break
    return rest.strip()


def normalize_title(src_title: str, title: str, lang: str) -> str:
    """Bölüm başlığını kaynaktaki numarayla tek kalıba sokar: 'Bölüm 700: Felaket ve Nimet (1)'.
    Kaynakta cilt yoksa çeviride uydurulmuş 'Cilt N' atılır; kaynak tanınmazsa başlığa dokunulmaz."""
    words = TITLE_WORDS.get(lang)
    m = _SRC_TITLE.match(src_title or "") or _SRC_TITLE_CJK.match(src_title or "")
    if not words or not m:
        return title
    num, vol = m.group("num"), m.groupdict().get("vol")
    sub = _subtitle(title or "", num, vol)
    if not m.group("rest").strip():
        sub = ""  # kaynakta alt başlık yok: modelin eklediği bir şey varsa da atılır
    head = (f"{words[0]} {vol} " if vol else "") + f"{words[1]} {num}"
    return f"{head}: {sub}" if sub else head


def _title_line(text: str, index: int, title: str = "") -> bool:
    """Metnin içinde tekrar eden bölüm başlığı satırı mı ("580 Looming Shadow…", "Bölüm 580: …")."""
    t = text.strip()
    if len(t) > 160 or not re.match(rf"^(?:(?:Chapter|Bölüm|Kapitel|Capítulo|Глава)\s*)?{index}\b", t, re.I):
        return False
    rest = re.sub(rf"^(?:(?:Chapter|Bölüm|Kapitel|Capítulo|Глава)\s*)?{index}\s*[:\-–—.]?\s*", "", t, flags=re.I)
    if not rest:
        return True
    sub = re.sub(r"^.*?\d+\s*[:\-–—.]?\s*", "", title or "", count=1)
    from difflib import SequenceMatcher

    return not sub or SequenceMatcher(None, rest.lower(), sub.lower()).ratio() > 0.5


def _strip_title_prefix(text: str, index: int, title: str) -> str:
    """Paragrafın başına yapışmış bölüm başlığını atar: "514 Bölüm 514: Uzaylı Irklar (1) Genel Sekreter…" → "Genel
    Sekreter…". Başlık kısmı bölüm başlığına benzemiyorsa paragrafa dokunmaz."""
    m = re.match(rf"^\s*(?:{index}\s+)?(?:(?:Bölüm|Chapter|Cilt\s+\S+\s+Bölüm)\s*)?{index}\b\s*[:\-–—.]?\s*", text)
    if not m:
        return text
    rest = text[m.end():]
    sub = re.sub(r"^.*?\b\d+\s*[:\-–—.]?\s*", "", title or "", count=1).strip()
    if not sub:
        return text
    from difflib import SequenceMatcher

    best = None
    for w in re.finditer(r"\S+", rest[: len(sub) + 25]):
        cand = rest[: w.end()]
        after = rest[w.end():].lstrip(" .:-–—")
        starts = not after or after[0].isupper() or after[0] in "\"“‘'«-—–0123456789"
        r = SequenceMatcher(None, cand.lower().rstrip("."), sub.lower()).ratio()
        if (r > 0.72 or r > 0.5 and starts) and (best is None or r >= best[0]):
            best = (r, w.end())
    if not best:
        return text
    return rest[best[1]:].lstrip(" .:-–—").strip()


def fix_chapter(src: Chapter, out: Chapter, lang: str) -> Chapter:
    """Kesin kurallarla düzeltilmiş bölüm (başlık kalıbı; Türkçede seviye kısaltması; gövdenin ilk iki paragrafında
    başlığı tekrar eden satır ve art arda iki kez yazılmış paragraf atılır)."""
    title = normalize_title(src.title, out.title, lang)
    paras = [p for i, p in enumerate(out.paragraphs) if not (i < 2 and len(out.paragraphs) > 3
                                                              and _title_line(p, out.index, title))]
    paras = [_strip_title_prefix(p, out.index, title) if i < 2 else p for i, p in enumerate(paras)]
    paras = [p for p in paras if p]
    if lang == "tr":
        title = fix_levels(title)
        paras = [fix_levels(p) for p in paras]
    paras = drop_repeats(src, Chapter(out.index, title, out.url, paras))[0].paragraphs
    if title == out.title and paras == out.paragraphs:
        return out
    return Chapter(out.index, title, out.url, paras, out.next_url, out.edited, getattr(out, "checked", 0))


# --- kaynak ↔ çeviri paragraf eşleme --------------------------------------------------------------------------
def _cost(ls: int, lo: int, ratio: float) -> float:
    import math

    return 3.0 * abs(math.log((lo + 25) / (ls * ratio + 25)))


def align(src: list[str], out: list[str], ratio: float = 1.0) -> list[tuple[tuple[int, ...], tuple[int, ...]]]:
    """Kaynak ve çeviri paragraflarını uzunluklarına göre eşler (Gale–Church benzeri): 1–1, 2–1 (birleştirilmiş),
    1–2 (bölünmüş), atlanan kaynak (eksik çeviri ya da reklam) ve karşılıksız çeviri (tekrar ya da uydurma).
    ratio: çeviri/kaynak beklenen uzunluk oranı (Türkçe–İngilizce ~1)."""
    n, m = len(src), len(out)
    ls, lo = [len(x) for x in src], [len(x) for x in out]
    # Uzunluğun yanında çapa: çeviride aynen korunan sayılar ve Latin harfli adlar (Xu Jingming, 1.020). Yalnız
    # bölümün çevirisinde gerçekten geçen kaynak kelimeleri çapa sayılır ("Yes"/"Evet" gibi çevrilenler sayılmaz).
    anchor = re.compile(r"\d+|[A-Z][a-z]{2,}")
    out_tokens = set(anchor.findall(" ".join(out)))
    sa = [set(anchor.findall(x)) & out_tokens for x in src]
    oa = [set(anchor.findall(x)) for x in out]

    def lex(si: set, oi: set) -> float:
        if not si:
            return 0.0
        return 1.5 * (1 - len(si & oi) / len(si))

    INF = float("inf")
    cost = [[INF] * (m + 1) for _ in range(n + 1)]
    back: list[list[tuple[int, int] | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            c = cost[i][j]
            if c == INF:
                continue
            steps = []
            if i < n and j < m:
                steps.append((1, 1, _cost(ls[i], lo[j], ratio) + lex(sa[i], oa[j])))
            for k in range(2, 6):  # 2–5 kaynak paragrafı tek paragrafta birleştirilmiş (ör. durum ekranı satırları)
                if i + k <= n and j < m:
                    steps.append((k, 1, 1.7 * _cost(sum(ls[i:i + k]), lo[j], ratio) + 0.8 + 0.3 * (k - 2)
                                  + lex(set().union(*sa[i:i + k]), oa[j])))
            if i < n and j + 1 < m:
                steps.append((1, 2, 1.7 * _cost(ls[i], lo[j] + lo[j + 1], ratio) + 0.8 + lex(sa[i], oa[j] | oa[j + 1])))
            if i < n:  # yalnız çok kısa satırlar ("***", reklam kırıntısı) ucuza atlanır
                steps.append((1, 0, 2.4 if ls[i] >= 15 else 0.4))
            if j < m:
                steps.append((0, 1, 2.4 if lo[j] >= 15 else 0.4))
            for di, dj, k in steps:
                if c + k < cost[i + di][j + dj]:
                    cost[i + di][j + dj] = c + k
                    back[i + di][j + dj] = (di, dj)
    pairs = []
    i, j = n, m
    while i or j:
        di, dj = back[i][j]
        pairs.append((tuple(range(i - di, i)), tuple(range(j - dj, j))))
        i, j = i - di, j - dj
    return pairs[::-1]


_NUM = re.compile(r"\d[\d.,]*\d|\d")


def _numbers(text: str) -> list[str]:
    return [x.replace(",", "").replace(".", "") for x in _NUM.findall(text)]


_TR_ONES = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_TR_TENS = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]


def tr_number_words(n: int) -> str:
    """Sayının Türkçe yazılışı, boşluksuz (137 → yüzotuzyedi, 1500 → binbeşyüz); 0 ve 10^9 üstü için ''."""
    if n <= 0 or n >= 10**9:
        return ""

    def below_1000(x: int) -> str:
        h, r = divmod(x, 100)
        return ("" if h == 0 else ("yüz" if h == 1 else _TR_ONES[h] + "yüz")) + _TR_TENS[r // 10] + _TR_ONES[r % 10]

    out = ""
    m, r = divmod(n, 10**6)
    if m:
        out += below_1000(m) + "milyon"
    k, r = divmod(r, 1000)
    if k:
        out += ("" if k == 1 else below_1000(k)) + "bin"
    return out + below_1000(r)


def _written_numbers(text: str) -> str:
    """Metnin harf dizisi (boşluksuz, küçük harf): yazıyla yazılmış sayıları aramak için."""
    return re.sub(r"[^a-zçğıöşü]", "", text.lower().replace("I", "ı").replace("İ", "i"))


def _norm(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text.lower()).strip()


# --- kitap başı sözlük adayları (modelsiz) -----------------------------------------------------------------------
_CAP_PHRASE = re.compile(r"[A-Z][\w'’-]*(?:\s+(?:of\s+(?:the\s+)?)?[A-Z][\w'’-]*)*")
_LEAD_STOP = {
    "a", "an", "the", "i", "he", "she", "it", "they", "we", "you", "his", "her", "its", "their", "our", "your", "my",
    "this", "that", "these", "those", "but", "and", "or", "so", "if", "as", "in", "on", "at", "to", "for", "from",
    "with", "by", "after", "before", "when", "while", "then", "there", "here", "what", "why", "how", "who", "where",
    "yes", "no", "oh", "ah", "eh", "hmm", "huh", "ok", "okay", "mr", "mrs", "ms", "dr", "chapter", "volume", "book",
    "translator", "editor", "note", "tl", "ed", "not", "all", "now", "just", "even", "only", "also", "however",
    "although", "though", "since", "because", "until", "once", "every", "each", "some", "any", "one", "two",
}


def term_candidates(chapters: list[Chapter], glossary: dict[str, str], limit: int = 600,
                    min_count: int = 3) -> list[dict]:
    """Kitabın tamamından, her yerde aynı çevrilmesi gereken özel ad/terim adayları (Latin yazılı kaynak için):
    büyük harfle başlayan kelime öbekleri, en az `min_count` kez ve en az iki kez cümle ortasında geçenler.
    [{"source", "count", "context"}], sıklığa göre; sözlükte olanlar hariç."""
    count: dict[str, int] = {}
    mid: dict[str, int] = {}
    ctx: dict[str, str] = {}
    known = {k.lower() for k in glossary}
    for ch in chapters:
        for para in ch.paragraphs:
            for m in _CAP_PHRASE.finditer(para):
                words = m.group(0).split()
                start = m.start()
                while words and words[0].lower().strip("'’") in _LEAD_STOP:
                    start = para.find(words[1], start) if len(words) > 1 else start
                    words = words[1:]
                if not words or len(words) > 6:
                    continue
                term = re.sub(r"['’]s$", "", " ".join(words)).strip("'’-")  # iyelik eki: Wang Lin's → Wang Lin
                if (len(term) < 3 or term.lower() in known or term.isupper() and len(term) <= 3
                        or re.search(r"['’](?:ll|m|ve|re|d|t)\b", term, re.I)):  # I'll, It's, Don't
                    continue
                before = para[:start].rstrip()
                initial = not before or before[-1] in ".!?\"“”‘'(:…—–-"
                count[term] = count.get(term, 0) + 1
                if not initial:
                    mid[term] = mid.get(term, 0) + 1
                    if term not in ctx:
                        a = max(0, para.rfind(".", 0, start) + 1)
                        b = para.find(".", m.end())
                        ctx[term] = para[a:(b + 1 if b != -1 else len(para))].strip()[:200]
    # Çoğul biçimi tekile kat (Godfiends → Godfiend); karşılık çekim ekiyle zaten uyar.
    for t in list(count):
        if t.endswith("s") and t[:-1] in count:
            count[t[:-1]] += count.pop(t)
            mid[t[:-1]] = mid.get(t[:-1], 0) + mid.pop(t, 0)
    # Tek kelime olup metinde küçük harfle de sık geçen sıradan kelimeler (Therefore, Master, Matter) aday değil.
    singles = {t.lower() for t in count if " " not in t}
    lower: dict[str, int] = {}
    if singles:
        for ch in chapters:
            for w in re.findall(r"\b[a-z][a-z'’-]+\b", " ".join(ch.paragraphs)):
                if w in singles:
                    lower[w] = lower.get(w, 0) + 1
    picks = [t for t, n in count.items() if n >= min_count and mid.get(t, 0) >= 2
             and not (" " not in t and lower.get(t.lower(), 0) >= max(2, n // 3))]
    picks.sort(key=lambda t: (-count[t], t))
    return [{"source": t, "count": count[t], "context": ctx.get(t, "")} for t in picks[:limit]]


GLOSSARY_AUDIT_VERSION = 1  # denetim kuralları/istemi değişince artır (bitmiş kitaplar yeniden denetlenir)


# --- sözlük denetimi: terimin kitap genelinde değiştirilmesi (çekim ekiyle) ------------------------------------
_TR_VOW = "aeıioöuü"
_TR_BACK = "aıou"
_TR_HARD = "çfhkpsşt"


def _last_vowel(s: str) -> str:
    for ch in reversed(s.lower()):
        if ch in _TR_VOW:
            return ch
    return "e"


def tr_harmonize(suffix: str, old: str, new: str) -> str:
    """Eski kelimeye eklenmiş Türkçe eki yeni kelimeye uydurur: ses uyumu, ünsüz benzeşmesi, kaynaştırma harfi
    (Tribün'ün → Felaket'in, Dragon'u → Ejderha'yı, Bela'yı → Felaket'i, Tribünde → Felakette)."""
    if not suffix:
        return ""
    s = suffix

    def poss(w: str) -> bool:  # tamlama: "İblis Bedeni" → ekler n ile gelir (Bedeni'ni, Bedeni'nde)
        return " " in w.strip() and w[-1:].lower() in "ıiuü" and len(w.split()[-1]) > 3

    old_v, new_v = old[-1:].lower() in _TR_VOW, new[-1:].lower() in _TR_VOW
    if poss(new) and not poss(old):
        if old_v and len(s) >= 2 and s[0] in "yns" and s[1] in _TR_VOW:
            s = s[1:]
        if s[0] in _TR_VOW or s[0] in "dt":
            s = "n" + ("d" + s[1:] if s[0] == "t" else s)  # Komutan'ı → Komutanı'nı, Beden'de → Bedeni'nde
        elif s[0] in "l" and re.fullmatch(r"l[ae]", s):
            s = "y" + s  # Komutan'la → Komutanı'yla
        old_v = new_v
    elif poss(old) and not poss(new) and len(s) >= 2 and s[0] == "n" and s[1] in "dt" :
        s = s[1:]  # Bedeni'nde → Beden'de
    if old_v and not new_v and len(s) >= 2 and s[0] in "yns" and s[1] in _TR_VOW:
        s = s[1:]  # Bela-yı / Bela-nın / Bela-sı → Felaket-i / -in / -i
    elif new_v and not old_v and s[0] in _TR_VOW:
        s = ("n" + s) if re.fullmatch(r"[ıiuü]n.*", s) else ("y" + s)
    out, lv, end = [], _last_vowel(new), new[-1:].lower()
    for i, ch in enumerate(s):
        if ch in "ıiuü":
            ch = {"a": "ı", "ı": "ı", "e": "i", "i": "i", "o": "u", "u": "u", "ö": "ü", "ü": "ü"}[lv]
            lv = ch
        elif ch in "ae":
            ch = "a" if lv in _TR_BACK else "e"
            lv = ch
        elif i == 0 and ch in "dt":
            ch = "t" if end in _TR_HARD else "d"
        elif i == 0 and ch in "cç":
            ch = "ç" if end in _TR_HARD else "c"
        out.append(ch)
    return "".join(out)


def replace_term(text: str, old: str, new: str, lang: str = "tr") -> tuple[str, int]:
    """Metinde `old` geçen yerleri `new` ile değiştirir; Türkçede arkasındaki eki uydurur, cümle başındaki büyük
    harfli biçimi de değiştirir. (metin, değişen sayısı)."""
    if not old or old == new:
        return text, 0
    forms = {old: new}
    if old[:1].islower():
        forms[old[:1].upper() + old[1:]] = new[:1].upper() + new[1:]
    count = 0
    for o, n in forms.items():
        if lang == "tr":
            pat = re.compile(r"(?<![\wçğıöşüÇĞİÖŞÜ])" + re.escape(o) + r"(['’]?)([a-zçğıöşü]*)")

            def sub(m, o=o, n=n):
                apo, suf = m.group(1), m.group(2)
                return n + (apo if suf else "") + tr_harmonize(suf, o, n)
        else:
            pat = re.compile(r"(?<!\w)" + re.escape(o) + r"(?!\w)")

            def sub(m, n=n):
                return n
        text, k = pat.subn(sub, text)
        count += k
    return text, count


_ZW = re.compile("[\u200b-\u200d\u2060\ufeff]")


def plain_text(ch: Chapter) -> str:
    """Bölümün düz metni (eski indirmelerde kalmış sıfır genişlikli karakterler atılır; terim araması için)."""
    return _ZW.sub("", " ".join(ch.paragraphs))


def count_term(text: str, term: str) -> int:
    """`term`in kelime sınırlarıyla kaç kez geçtiği (str.find ile; uzun metinde regex'ten çok hızlı)."""
    n, pos, L = 0, text.find(term), len(term)
    while pos != -1:
        before = text[pos - 1] if pos else " "
        after = text[pos + L] if pos + L < len(text) else " "
        if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
            n += 1
        pos = text.find(term, pos + L)
    return n


def _term_re(term: str) -> re.Pattern:
    return re.compile(r"(?<![\w])" + re.escape(term) + r"(?![\w])")


def glossary_audit_items(source: dict[int, Chapter], results: dict[int, Chapter], glossary: dict[str, str],
                         top: int = 150, examples: int = 2) -> list[dict]:
    """Sözlük denetimi için en sık geçen terimler: kaynakta kaç kez geçtiği ve 2 örnek (kaynak cümlesi + o yerin
    çevirisi), modelin karşılığın gerçekte nasıl kullanıldığını görebilmesi için."""
    idx = [i for i in sorted(results) if i in source and results[i] is not source[i]]
    if not idx:
        return []
    step = max(1, len(idx) // 300)  # sıklık için örneklem (hız)
    plain = {i: plain_text(source[i]) for i in idx}
    sample = " \n".join(plain[i] for i in idx[::step])
    cand = [(k, v) for k, v in glossary.items() if k != v and len(k) >= 3]
    freq = {k: count_term(sample, k) * step for k, _ in cand}
    picks = [k for k in sorted(freq, key=lambda k: -freq[k]) if freq[k] >= 3][:top]
    out = []
    for k in picks:
        rx = _term_re(k)
        found = [i for i in idx if count_term(plain[i], k)]
        ex = []
        for i in [found[j * (len(found) - 1) // max(1, examples - 1)] for j in range(examples)] if found else []:
            S, T = [_ZW.sub("", p) for p in source[i].paragraphs], results[i].paragraphs
            si = next((n for n, p in enumerate(S) if rx.search(p)), None)
            if si is None:
                continue
            oi = next((o for s_, o_ in align(S, T, _len_ratio(S)) if si in s_ for o in o_), None)
            if oi is None:
                continue
            ex.append({"source": S[si][:400], "translation": T[oi][:500]})
        out.append({"source": k, "current": glossary[k], "count": freq[k], "examples": ex})
    return out


# --- tekrar temizliği (modelsiz, kesin kurallar) ---------------------------------------------------------------
@functools.lru_cache(maxsize=50000)
def _shingles(text: str, n: int = 3) -> frozenset[tuple[str, ...]]:
    w = re.findall(r"\w+", text.lower())
    return frozenset(tuple(w[i:i + n]) for i in range(max(1, len(w) - n + 1))) if w else frozenset()


def _contain(a: str, b: str) -> float:
    """Kısa olanın kelime üçlülerinin ne kadarı uzun olanda geçiyor (1.0 = biri ötekinin içinde)."""
    A, B = _shingles(a), _shingles(b)
    return len(A & B) / max(1, min(len(A), len(B)))


def _repeatable(p: str) -> bool:
    return len(p) >= 40 and len(p.split()) >= 6


def _src_repeats(src: list[str]) -> list[tuple[int, int]]:
    """Kaynakta birbirine çok benzeyen (yazarın bilerek tekrarladığı) yakın paragraf çiftleri."""
    pairs = []
    for j in range(len(src)):
        if not _repeatable(src[j]):
            continue
        for k in range(j + 1, min(len(src), j + 6)):
            if not _repeatable(src[k]):
                continue
            sj, sk = _stems5(src[j]), _stems5(src[k])
            if _contain(src[j], src[k]) >= 0.6 or (min(len(sj), len(sk)) >= 15
                                                     and len(sj & sk) >= 0.75 * min(len(sj), len(sk))):
                pairs.append((j, k))
    return pairs


@functools.lru_cache(maxsize=50000)
def _stems5(text: str) -> frozenset[str]:
    """Paragrafın içerik kelimelerinin ilk 5 harfi (çekim ekinden ve eş anlamlı küçük farklardan bağımsız)."""
    return frozenset(w[:5] for w in re.findall(r"[^\W\d_]{4,}", text.lower()))


def covered_by(text: str, others: list[str], share: float = 0.6) -> bool:
    """`text`in içerik kelimelerinin en az `share` kadarı komşu paragraflardan birinde var mı (aynı metnin çevirisi)."""
    a = _stems5(text)
    return len(a) >= 5 and any(len(a & _stems5(o)) >= share * len(a) for o in others if o)


_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")


def _len_ratio(src: list[str]) -> float:
    """Çeviri/kaynak beklenen karakter oranı: Çince/Japonca/Korece kaynak aynı anlamı ~üçte bir karakterle yazar."""
    sample = " ".join(src[:20])
    return 0.35 if sample and len(_CJK.findall(sample)) > 0.3 * len(sample) else 1.0


def drop_repeats(src: Chapter, out: Chapter, window: int = 3) -> tuple[Chapter, int]:
    """Çeviride art arda (en çok `window` paragraf arayla) iki kez yazılmış metni atar:
    (a) aynısı ya da biri ötekinin içinde (kısa olan ≥12 kelime) → kısa olan atılır;
    (b) aynı kaynak metnin ikinci, farklı kelimelerle çevirisi (paragraf, hemen önceki 1–3 paragrafın kelimelerini
        büyük ölçüde tekrar ediyor; ör. önce iki paragrafa bölünmüş, sonra tek paragraf olarak yeniden yazılmış) →
        sonraki atılır.
    (c) kısa bir paragrafın içerik kelimelerinin ≥%85'i 1–2 paragraf ötedeki daha uzun paragrafta var ve kısa olan
        kaynakta hiçbir paragrafa eşlenmiyor (denetimin "atlanmış" sanıp yeniden eklediği çeviri) → kısa olan atılır.
    Kaynakta da aynı yerde tekrar varsa (yazarın tekrarı) dokunmaz. (bölüm, atılan sayısı)."""
    T = out.paragraphs
    if len(T) < 2:
        return out, 0
    cands: list[tuple[tuple[int, ...], int, int]] = []  # (önceki blok, sonraki, atılacak)
    orphan: list[tuple[int, int]] = []  # (c) adayları: (kısa, uzun)
    for k in range(len(T)):
        for j in (k + 1, k + 2):
            if j >= len(T):
                break
            a, b = _stems5(T[k]), _stems5(T[j])
            short, other = (k, j) if len(a) <= len(b) else (j, k)
            sh, lo = (a, b) if short == k else (b, a)
            if len(sh) >= 8 and len(sh & lo) >= 0.85 * len(sh):
                orphan.append((short, other))
                break
    for k in range(1, len(T)):
        hit = False
        if _repeatable(T[k]):
            for j in range(max(0, k - window), k):
                if _repeatable(T[j]) and min(len(T[j].split()), len(T[k].split())) >= 12 \
                        and _contain(T[j], T[k]) >= 0.85:
                    cands.append(((j,), k, k if len(T[k]) <= len(T[j]) else j))
                    hit = True
                    break
        sk = _stems5(T[k])
        if hit or len(sk) < 15:
            continue
        for w in range(1, window + 1):
            if k - w < 0:
                break
            sb = frozenset().union(*(_stems5(p) for p in T[k - w:k]))
            o = len(sk & sb)
            # Sonraki paragraf öncekinin neredeyse tamamen yeniden yazımı (önceki daha uzun olabilir: ör. bir
            # cümle fazlası var) ya da önceki 1–3 paragrafın birleşik yeniden çevirisi.
            if sb and o >= 0.75 * len(sk) and (o >= 0.6 * len(sb) or (w == 1 and o >= 0.8 * len(sk))):
                cands.append((tuple(range(k - w, k)), k, k))
                break
    if not cands and not orphan:
        return out, 0  # eşleme pahalı: yalnız aday varsa yapılır
    S = [p for i, p in enumerate(src.paragraphs) if not (i < 2 and _title_line(p, src.index, src.title))]
    t2s: dict[int, tuple[int, ...]] = {}
    if S:
        for si, oi in align(S, T, _len_ratio(S)):
            for o in oi:
                t2s[o] = si
    reps = _src_repeats(S)

    def similar(x: str, y: str) -> bool:
        sx, sy = _stems5(x), _stems5(y)
        return _contain(x, y) >= 0.6 or (len(sx) >= 8 and len(sy) >= 8
                                          and len(sx & sy) >= 0.6 * min(len(sx), len(sy)))

    def legit(js: tuple[int, ...], k: int) -> bool:
        a = tuple(x for j in js for x in t2s.get(j, ()))
        b = t2s.get(k, ())
        if a and b and not set(b) <= set(a) and similar(" ".join(S[x] for x in a), " ".join(S[x] for x in b)):
            return True
        pos_a = min(a) if a else None
        pos_b = min(b) if b else None
        for x, y in reps:  # eşleme kayabilir: yakınında kaynak tekrarı varsa dokunma
            if (pos_a is None or abs(x - pos_a) <= 3) and (pos_b is None or abs(y - pos_b) <= 3):
                if pos_a is not None or pos_b is not None:
                    return True
        return False

    drop: set[int] = set()
    for js, k, victim in cands:
        if k in drop or any(j in drop for j in js):
            continue
        if not legit(js, k):
            drop.add(victim)
    for short, other in orphan:
        if short in drop or other in drop or not S or t2s.get(short):
            continue
        if not legit((min(short, other),), max(short, other)):
            drop.add(short)
    if not drop:
        return out, 0
    paras = [p for i, p in enumerate(T) if i not in drop]
    return Chapter(out.index, out.title, out.url, paras, out.next_url, out.edited, getattr(out, "checked", 0)), len(drop)


def drop_boundary_repeat(src: Chapter, out: Chapter, next_src: Chapter, next_out: Chapter,
                         tail: int = 3) -> tuple[Chapter, int]:
    """Bölümün sonuna sonraki bölümün ilk paragrafları da çevrilip eklenmişse (bağlam için verilen sonraki bölüm
    başı) onları atar. Kaynakta da bölüm sonu sonraki bölümün başında tekrar ediyorsa dokunmaz."""
    T, N = out.paragraphs, next_out.paragraphs[:tail + 1]
    if len(T) <= tail or not N:
        return out, 0
    s_end = [p for p in src.paragraphs[-(tail + 2):] if _repeatable(p)]
    s_beg = [p for p in next_src.paragraphs[:tail + 2] if _repeatable(p)]
    if any(_contain(a, b) >= 0.6 for a in s_end for b in s_beg):
        return out, 0
    drop = {i for i in range(len(T) - tail, len(T))
            if _repeatable(T[i]) and any(_repeatable(q) and _contain(T[i], q) >= 0.9 for q in N)}
    if not drop:
        return out, 0
    paras = [p for i, p in enumerate(T) if i not in drop]
    return Chapter(out.index, out.title, out.url, paras, out.next_url, out.edited, getattr(out, "checked", 0)), len(drop)


def next_chapter_span(src: Chapter, next_src: Chapter) -> tuple[int, int] | None:
    """Sitede bölüm sayfasına sonraki bölümün metni de eklenmişse (ör. 742. sayfada 742 + 743) o kısmın kaynak
    paragraf aralığı (baştan ya da sondan); yoksa None."""
    S, N = src.paragraphs, [p for p in next_src.paragraphs if _repeatable(p)]
    if len(N) < 5 or len(S) < len(N):
        return None
    whole = _shingles(" ".join(N))  # hızlı ön eleme: sonraki bölümün metni bu sayfada çoğunlukla yoksa çık
    if len(whole & _shingles(" ".join(S))) < 0.5 * len(whole):
        return None
    hit = [k for k, p in enumerate(S) if _repeatable(p) and any(_contain(p, x) >= 0.85 for x in N)]
    covered = sum(1 for x in N if any(_contain(x, S[k]) >= 0.85 for k in hit))
    if covered < 0.8 * len(N) or not hit:
        return None
    s0, s1 = hit[0], hit[-1]
    if s1 - s0 + 1 > 1.3 * len(hit) + 2:
        return None  # dağınık eşleşme: sayfa birleşmesi değil
    if s1 >= len(S) - 3:
        return s0, len(S) - 1
    if s0 <= 2:
        return 0, s1
    return None


def drop_next_chapter_copy(src: Chapter, out: Chapter, next_src: Chapter) -> tuple[Chapter, int]:
    """Kaynakta sonraki bölümün metni bu bölüme de eklenmişse çevirideki karşılığını atar (sonraki bölüm zaten
    kendi yerinde var)."""
    span = next_chapter_span(src, next_src)
    if not span or not out.paragraphs:
        return out, 0
    s0, s1 = span
    tail = s1 == len(src.paragraphs) - 1
    # Daha önce kesildiyse yeniden kesme: çeviri uzunluğu kaynağın yalnız kendi kısmı kadarsa çık.
    total = sum(len(p) for p in src.paragraphs) or 1
    own = sum(len(p) for i, p in enumerate(src.paragraphs) if not s0 <= i <= s1) / total
    ratio = _len_ratio(src.paragraphs)
    if sum(len(p) for p in out.paragraphs) * ratio / total < own + (1 - own) / 2:
        return out, 0
    pos: list[int] = []
    for si, oi in align(src.paragraphs, out.paragraphs, ratio):
        if si and oi and (s0 <= min(si) <= s1):
            pos.extend(oi)
    if not pos:
        return out, 0
    if tail:
        cut = min(pos)
        keep = out.paragraphs[:cut]
    else:
        cut = max(pos)
        keep = out.paragraphs[cut + 1:]
    if not keep:
        return out, 0
    n = len(out.paragraphs) - len(keep)
    return Chapter(out.index, out.title, out.url, keep, out.next_url, out.edited, getattr(out, "checked", 0)), n


# --- paragraf sorunları ------------------------------------------------------------------------------------------
OMITTED = "atlanmış kaynak paragrafı"


def paragraph_issues(src: Chapter, out: Chapter, lang: str, glossary: dict[str, str], vocab: set[str],
                     names: set[str] = frozenset()) -> tuple[dict[int, tuple[str, list[str]]], dict[int, list[str]]]:
    """Modelle düzeltilecek paragraflar: {çıktı paragrafı sırası: (karşılık gelen kaynak metin, [sorunlar])}.
    Kaynak ve çeviri uzunluklarına göre eşlenir; atlanmış kaynak paragrafı önceki çeviri paragrafına "ardına ekle"
    sorunu olarak, karşılıksız (uydurma/tekrar) çeviri paragrafı "sil" sorunu olarak gelir."""
    from collections import Counter

    issues: dict[int, tuple[str, list[str]]] = {}
    src_all = " ".join(src.paragraphs)
    cjk_src = bool(re.search(r"[぀-ヿ㐀-鿿가-힯]", src_all[:2000]))
    latin_src = not cjk_src
    kept = _kept_words(glossary, vocab) | set(names)
    # Kaynakta metnin içinde tekrar eden başlık satırı eşlemeye girmez (yoksa ilk paragrafa yapıştırılıyordu).
    src = Chapter(src.index, src.title, src.url, [p for i, p in enumerate(src.paragraphs)
                                                  if not (i < 2 and _title_line(p, src.index, src.title))])
    pairs = align(src.paragraphs, out.paragraphs, 0.35 if cjk_src and lang not in ("zh", "ja", "ko") else 1.0) \
        if out.paragraphs and src.paragraphs else []
    src_of: dict[int, str] = {}
    extra: dict[int, list[str]] = {}
    last_out = None
    for si, oi in pairs:
        stext = " ".join(src.paragraphs[k] for k in si)
        for o in oi if si else ():
            src_of[o] = stext
        if oi:
            last_out = oi[-1]
        if si and not oi:  # çevrilmemiş kaynak paragrafı
            for k in si:
                sp = src.paragraphs[k]
                if _title_line(sp, src.index, src.title):
                    continue  # metnin içinde tekrar eden bölüm başlığı: başlıkta zaten var
                if len(sp) >= 50 and not re.search(r"(?i)\b(chapter|translat|novel|\.com|\.net|patreon|discord)\b", sp):
                    tgt = last_out if last_out is not None else 0
                    extra.setdefault(tgt, []).append(sp)
    # Kaynakta olmayan tekrar: aynı paragrafın kopyalarından eşleşmeyeni (yoksa sonrakini) silinecek say.
    src_dups = any(v > 1 for v in Counter(_norm(p) for p in src.paragraphs if len(p) > 40).values())
    copies: dict[str, list[int]] = {}
    for i, p in enumerate(out.paragraphs):
        if len(p) > 40:
            copies.setdefault(_norm(p), []).append(i)
    drop: set[int] = set()
    for idx in copies.values():
        if len(idx) > 1 and not src_dups:
            unmatched = [k for k in idx if k not in src_of]
            drop.update(unmatched if 0 < len(unmatched) < len(idx) else idx[1:])
    for i, p in enumerate(out.paragraphs):
        sp = src_of.get(i, "")
        found: list[str] = []
        if i in drop:
            found.append("bu paragraf bölümde ikinci kez geçiyor (tekrar): boş döndür")
        # Kaynakta karşılığı bulunamayan paragraf silinmeye aday gösterilmez: eşleme yanılabilir, gerçek metin gider.
        if lang == "tr":
            old = archaic_words(p)
            if old:
                found.append("eski/ağdalı kelime; bugünkü Türkçeyle yaz: " + ", ".join(f"{w} → {r}" for w, r in old))
        if lang != "en" and latin_src and sp:
            left = leftover_english(sp, p, vocab, kept)
            if left:
                found.append("kaynak dilde kalmış kelime: " + ", ".join(left) + " — ad öbeğinin parçası olsa da çevir "
                             "(Feather Fire Lord → Tüy Ateşi Lordu, Green Lake → Yeşil Göl); yalnız kişinin asıl adı "
                             "(Ming, Fussen, Lunardo) aynen kalır")
        if sp:
            # Sözlük tutarlılığı tek başına sorun sayılmaz (sözlükte de hata olabilir; maliyetli); onarılan
            # paragrafta sözlük zaten modele gider. Yeni çeviride sözlük istemin parçası.
            lost = Counter(_numbers(sp)) - Counter(_numbers(p))
            if lost and lang == "tr":  # sayı yazıyla yazılmışsa (137 → yüz otuz yedi) eksik sayılmaz
                letters = _written_numbers(p)
                lost = Counter({n: c for n, c in lost.items()
                                if not (n.isdigit() and (w := tr_number_words(int(n))) and w in letters)})
            if lost and latin_src:
                found.append("kaynaktaki sayı(lar) çeviride yok ya da farklı: " + ", ".join(sorted(lost)[:6])
                             + " (kaynağa göre düzelt; sayı yazıyla yazılmışsa doğruysa bırak)")
            if len(sp) >= 200 and len(p) < 0.6 * len(sp) and lang not in ("zh", "ja", "ko") and not cjk_src:
                found.append("kaynağa göre çok kısa: atlanan cümleleri kaynaktan çevirip ekle")
        if i in extra:
            found.append(f"{OMITTED}: bu paragraftan SONRA gelen ve çevrilmemiş kaynak metni ('missing') çevir; çıktıda "
                         "önce bu paragrafın düzeltilmiş hâli, sonra boş satır (\\n\\n), sonra atlanan kısmın çevirisi olsun")
        if found:
            issues[i] = (sp, found)
    return issues, extra


def missing_share(src: Chapter, out: Chapter) -> float:
    """Kaynağın çevrilmeden kalan (eşlenemeyen) kısmının oranı; yüksekse bölüm baştan çevrilir."""
    if not src.paragraphs or not out.paragraphs:
        return 1.0 if src.paragraphs else 0.0
    total = sum(len(p) for p in src.paragraphs) or 1
    lost = sum(len(src.paragraphs[k]) for si, oi in align(src.paragraphs, out.paragraphs) if si and not oi for k in si
               if len(src.paragraphs[k]) >= 50)
    return lost / total


def archaic_density(out: Chapter) -> float:
    """1000 kelimede eski/ağdalı kelime sayısı (yüksekse bölüm baştan redakte edilir). Sözlük teriminden gelen
    kelimeler ("İptidai Yıldız") sayılmaz: onlar sözlük düzeltilince paragraf onarımıyla düzelir."""
    text = " ".join(out.paragraphs)
    n = max(1, len(text.split()))
    hits = sum(len(rx.findall(text)) for k, (rx, _) in zip(ARCHAIC_TR, _ARCHAIC) if k != r"iptidai")
    return 1000 * hits / n
