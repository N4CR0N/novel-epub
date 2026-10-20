"""Bölüm metnini temizler ve indirilen bölümleri denetler."""
from __future__ import annotations

import hashlib
import re

from bs4 import Tag

from .models import Chapter

# Kısa satırlarda görülen site reklamı / filigran / emek satırları.
NOISE_RE = re.compile(
    r"(free\s*web\s*novel|novel\s*bin|light\s*novel\s*(world|pub|cave)|webnovel\.com|"
    r"read\s+(the\s+)?(latest|more|next)\s+chapters?|visit\s+\S+\s+for|for\s+the\s+best\s+novel|"
    r"^(translated|translator|edited|editor|proofread(er)?|tl|ed|tlc)\s*(by)?\s*[:：]|"
    r"^\s*(advertisement|sponsored content)\s*$|https?://|www\.\S+)",
    re.I,
)
BLOCK_RE = re.compile(r"(just a moment|enable javascript|checking your browser|access denied|captcha)", re.I)
NOISE_TAGS = ("script", "style", "noscript", "iframe", "ins", "button", "form", "svg")
NOISE_CLASS_RE = re.compile(r"(\bads?\b|advert|banner|sponsor|\bshare|comment|\bnav\b|skiptranslate)", re.I)


def extract_paragraphs(el: Tag) -> list[str]:
    """Bir içerik öğesinden paragraf listesi çıkarır (<p> yoksa <br>/satır sonlarından)."""
    for bad in el.find_all(NOISE_TAGS):
        bad.decompose()
    for div in el.find_all(["div", "aside"]):
        if div.decomposed:
            continue
        cls = " ".join(div.get("class") or []) + " " + (div.get("id") or "")
        if NOISE_CLASS_RE.search(cls) and len(div.get_text(strip=True)) < 400:
            div.decompose()
    ps = el.find_all("p")
    if len(ps) >= 3:
        texts = [p.get_text(" ", strip=True) for p in ps]
    else:
        for br in el.find_all("br"):
            br.replace_with("\n")
        texts = el.get_text("\n").split("\n")
    return [t for t in (re.sub(r"\s+", " ", t).strip() for t in texts) if t]


def clean_paragraphs(paragraphs: list[str], title: str = "") -> list[str]:
    out: list[str] = []
    norm_title = re.sub(r"\W+", "", title.lower())
    for i, p in enumerate(paragraphs):
        p = re.sub(r"\s+", " ", p).strip()
        if not p:
            continue
        if len(p) < 200 and NOISE_RE.search(p):
            continue
        # Başta tekrar eden bölüm başlığını at (EPUB'da zaten başlık var).
        if i < 3 and norm_title and re.sub(r"\W+", "", p.lower()) == norm_title:
            continue
        if out and out[-1] == p:
            continue
        out.append(p)
    return out


def chapter_number(text: str) -> int | None:
    m = re.search(r"(?:chapter|ch\.?|bölüm|episode|ep\.?)\s*(\d+)", text, re.I) or re.search(r"第\s*(\d+)\s*[章话話回]", text)
    if not m:
        m = re.search(r"chapter[-_](\d+)", text, re.I)
    return int(m.group(1)) if m else None


def check_chapter(ch: Chapter, min_chars: int = 300) -> list[str]:
    issues = []
    text = " ".join(ch.paragraphs)
    if not ch.paragraphs:
        issues.append("boş")
    elif ch.char_count < min_chars:
        issues.append(f"kısa ({ch.char_count} karakter)")
    if BLOCK_RE.search(text[:500]) and ch.char_count < 2000:
        issues.append("engel sayfası gibi")
    return issues


def check_book(chapters: list[Chapter]) -> dict:
    """Bölümler arası denetim: kopya içerik, numara boşlukları, sorunlu bölümler."""
    report = {"sorunlu": {}, "kopya": [], "eksik_numaralar": []}
    seen: dict[str, int] = {}
    for ch in chapters:
        iss = check_chapter(ch)
        if iss:
            report["sorunlu"][ch.index] = iss
        h = hashlib.sha1("\n".join(ch.paragraphs).encode()).hexdigest()
        if ch.paragraphs and h in seen:
            report["kopya"].append((seen[h], ch.index))
        seen.setdefault(h, ch.index)
    nums = [n for n in (chapter_number(c.title) or chapter_number(c.url) for c in chapters) if n is not None]
    if len(nums) >= 2 and nums == sorted(nums):
        have = set(nums)
        report["eksik_numaralar"] = [n for n in range(nums[0], nums[-1] + 1) if n not in have][:50]
    return report
