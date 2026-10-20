from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..cleaner import clean_paragraphs, extract_paragraphs
from ..fetcher import Fetcher
from ..models import Chapter, ChapterRef, Novel


class Source:
    name = "base"
    domains: tuple[str, ...] = ()

    def __init__(self, fetcher: Fetcher):
        self.f = fetcher

    @classmethod
    def matches(cls, url: str) -> bool:
        host = urlparse(url).netloc.lower().split(":")[0]
        return any(host == d or host.endswith("." + d) for d in cls.domains)

    def novel(self, url: str) -> Novel:
        raise NotImplementedError

    def chapter(self, ref: ChapterRef) -> Chapter:
        raise NotImplementedError

    # --- yardımcılar ---
    @staticmethod
    def meta(soup: BeautifulSoup, *names: str) -> str:
        for n in names:
            m = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
            if m and m.get("content"):
                return m["content"].strip()
        return ""

    @staticmethod
    def text(soup: BeautifulSoup, selector: str) -> str:
        el = soup.select_one(selector)
        return el.get_text(" ", strip=True) if el else ""

    @staticmethod
    def build_chapter(ref: ChapterRef, content_el, title: str = "", next_url: str | None = None) -> Chapter:
        title = title or ref.title
        paras = clean_paragraphs(extract_paragraphs(content_el), title) if content_el else []
        return Chapter(index=ref.index, title=title, url=ref.url, paragraphs=paras, next_url=next_url)

    @staticmethod
    def next_link(soup: BeautifulSoup, base_url: str) -> str | None:
        for sel in ("a[rel=next]", "a#next_chap", "a#next-chapter", "a.next_chap", "a.next-chap", "a.btn-next"):
            a = soup.select_one(sel)
            if a and a.get("href") and not a["href"].startswith("javascript"):
                return urljoin(base_url, a["href"])
        for a in soup.find_all("a", href=True):
            t = a.get_text(" ", strip=True).lower()
            if t in ("next", "next chapter", "next chap", "sonraki", "sonraki bölüm", "下一章", "次へ", "次の話") or t.startswith("next chapter"):
                if not a["href"].startswith("javascript"):
                    return urljoin(base_url, a["href"])
        return None
