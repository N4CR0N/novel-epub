"""Tanınmayan siteler için genel kaynak.

İçindekiler sayfası verilirse bölüm bağlantılarını bulur; bölüm sayfası verilirse oradan
"Sonraki" bağlantılarını izleyerek ilerler. İçerik, en çok paragraf metni barındıran öğedir.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..cleaner import chapter_number
from ..models import Chapter, ChapterRef, Novel
from .base import Source

CHAPTER_LINK_RE = re.compile(r"(chapter|chap|ch[-_.]?\d|bölüm|episode|第.{1,8}[章话話回]|/\d+\.html?$)", re.I)
CONTENT_HINT_RE = re.compile(r"(chapter|chr|content|article|entry|text|reader|novel)", re.I)


def best_content(soup: BeautifulSoup):
    best, best_score = None, 0
    for el in soup.find_all(["div", "article", "section", "main"]):
        ps = el.find_all("p", recursive=False) or el.find_all("p")
        score = sum(len(p.get_text(strip=True)) for p in ps)
        if not ps:
            score = len(el.get_text(strip=True)) * 0.3 if el.find("br") else 0
        hint = " ".join(el.get("class") or []) + " " + (el.get("id") or "")
        if CONTENT_HINT_RE.search(hint):
            score *= 1.3
        # Çok geniş kapsayıcıları (tüm sayfa) cezalandır: alt öğe sayısına göre.
        score /= 1 + len(el.find_all(["div", "ul", "nav"])) / 40
        if score > best_score:
            best, best_score = el, score
    return best


class Generic(Source):
    name = "genel"

    @classmethod
    def matches(cls, url: str) -> bool:
        return True

    def novel(self, url: str) -> Novel:
        soup = self.f.soup(url)
        host = urlparse(url).netloc
        title = self.meta(soup, "og:title") or (soup.title.get_text(strip=True) if soup.title else url)
        novel = Novel(url=url, source=self.name, title=title,
                      cover_url=urljoin(url, self.meta(soup, "og:image")) if self.meta(soup, "og:image") else "",
                      description=self.meta(soup, "og:description", "description"))
        seen = set()
        for a in soup.find_all("a", href=True):
            href = urljoin(url, a["href"]).split("#")[0]
            text = a.get_text(" ", strip=True)
            if urlparse(href).netloc != host or href in seen or href == url:
                continue
            if CHAPTER_LINK_RE.search(href) or CHAPTER_LINK_RE.search(text):
                seen.add(href)
                novel.chapters.append(ChapterRef(len(novel.chapters) + 1, text or href, href))
        # Sırası ters (en yeni üstte) listeleri düzelt.
        nums = [chapter_number(c.title) or chapter_number(c.url) for c in novel.chapters]
        known = [n for n in nums if n is not None]
        if len(known) >= 3 and known[0] > known[-1]:
            novel.chapters.reverse()
            for i, c in enumerate(novel.chapters, 1):
                c.index = i
        if len(novel.chapters) < 3:
            # İçindekiler bulunamadı: bu sayfayı ilk bölüm say, "Sonraki" ile gez.
            novel.chapters = [ChapterRef(1, title, url)]
            novel.follow_next = True
        return novel

    def chapter(self, ref: ChapterRef) -> Chapter:
        soup = self.f.soup(ref.url)
        h = soup.find(["h1", "h2"])
        title = h.get_text(" ", strip=True) if h else ref.title
        return self.build_chapter(ref, best_content(soup), title, self.next_link(soup, ref.url))
