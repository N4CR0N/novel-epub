"""Çeviri kalite denetimi.

Çeviri bittikten (ve redakte edildikten) sonra her bölüme uygulanır; bitmiş kitaplar için "Çeviriyi denetle ve
düzelt" de aynısını yapar. İki tür düzeltme var:
- kesin kurallar (kodla): bölüm başlığı kalıbı ("Chapter 700 X" → "Bölüm 700: X"; uydurulmuş "Cilt" yok), seviye
  kısaltması ("Lv. 10" / "Sv. 10" → "Seviye 10");
- modelle onarılacak paragraflar: kaynak dilde kalmış kelime ("Dean Ming", "Spacetime Island"), sözlüğe uymayan terim,
  eski/ağdalı Türkçe ("talebe", "ekseriyet", "muvaffak olamaz"), kaynağa göre çok kısa kalmış (eksik) paragraf.
"""
from __future__ import annotations

import re

from .models import Chapter

QUALITY_VERSION = 1  # denetim kuralları değişince artır: bitmiş kitaplar yeniden denetlenebilir

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
        kw = {w.lower() for w in re.findall(r"[A-Za-z]{3,}", k)}
        left = [w for w in re.findall(r"[A-Za-z]{3,}", v)
                if w.lower() in kw and w.lower() not in TR_SAME and (w.lower() in COMMON_EN or w.lower() in vocab)]
        if left:
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
        m = re.match(r"^(\d+)\b\s*", rest)
        if m and (m.group(1) in (num, vol) or after_vol_word):
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


def fix_chapter(src: Chapter, out: Chapter, lang: str) -> Chapter:
    """Kesin kurallarla düzeltilmiş bölüm (başlık kalıbı; Türkçede seviye kısaltması)."""
    title = normalize_title(src.title, out.title, lang)
    paras = out.paragraphs
    if lang == "tr":
        title = fix_levels(title)
        paras = [fix_levels(p) for p in paras]
    if title == out.title and paras == out.paragraphs:
        return out
    return Chapter(out.index, title, out.url, paras, out.next_url, out.edited, getattr(out, "checked", 0))


# --- paragraf sorunları ------------------------------------------------------------------------------------------
def paragraph_issues(src: Chapter, out: Chapter, lang: str, glossary: dict[str, str], vocab: set[str]) -> dict[int, list[str]]:
    """Modelle düzeltilecek paragraflar: {çıktı paragrafı sırası: [sorunların açıklaması]}.
    Kaynak ve çeviri paragraf sayısı eşitse paragraf paragraf (sözlük, eksik çeviri), değilse bölüm genelinde bakılır."""
    issues: dict[int, list[str]] = {}
    aligned = len(src.paragraphs) == len(out.paragraphs)
    src_all = " ".join(src.paragraphs)
    latin_src = not re.search(r"[぀-ヿ㐀-鿿가-힯]", src_all[:2000])
    kept = _kept_words(glossary, vocab)
    for i, p in enumerate(out.paragraphs):
        sp = src.paragraphs[i] if aligned else src_all
        found: list[str] = []
        if lang == "tr":
            old = archaic_words(p)
            if old:
                found.append("eski/ağdalı kelime; bugünkü Türkçeyle yaz: " + ", ".join(f"{w} → {r}" for w, r in old))
        if lang != "en" and latin_src:
            left = leftover_english(sp, p, vocab, kept)
            if left:
                found.append("kaynak dilde kalmış kelime (kişi/yer adı değilse çevir): " + ", ".join(left))
        if aligned:
            miss = glossary_misses(sp, p, glossary)
            if miss:
                found.append("sözlükteki karşılığı kullan: " + "; ".join(f"{k} → {v}" for k, v in miss[:8]))
            if len(sp) >= 160 and len(p) < 0.45 * len(sp) and lang not in ("zh", "ja", "ko"):
                found.append("kaynağa göre çok kısa: eksik çevrilmiş olabilir, atlanan kısmı ekle")
        if found:
            issues[i] = found
    return issues


def archaic_density(out: Chapter) -> float:
    """1000 kelimede eski/ağdalı kelime sayısı (yüksekse bölüm baştan redakte edilir)."""
    text = " ".join(out.paragraphs)
    n = max(1, len(text.split()))
    hits = sum(len(rx.findall(text)) for rx, _ in _ARCHAIC)
    return 1000 * hits / n
