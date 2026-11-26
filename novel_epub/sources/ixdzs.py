from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from ..models import Chapter, ChapterRef, Novel
from .base import Source


class Ixdzs(Source):
    """爱下电子书 (ixdzs8.com / ixdzs.tw) — Çince ham metin. Bölüm adresleri sıralı: /read/<id>/p<N>.html;
    sayfadaki listede en yüksek N bulunur, bölümler 1..N diye kurulur (ad bölüm sayfasından gelir).
    Metin `article.page-content section p`."""

    name = "ixdzs"
    domains = ("ixdzs8.com", "ixdzs.tw")
    min_delay = 1.5

    @staticmethod
    def book_url(url: str) -> str:
        p = urlparse(url)
        m = re.match(r"/read/(\d+)", p.path)
        if not m:
            raise ValueError("ixdzs linki /read/<numara>/ biçiminde olmalı")
        return f"{p.scheme}://{p.netloc}/read/{m.group(1)}/"

    def novel(self, url: str) -> Novel:
        url = self.book_url(url)
        soup = self.f.soup(url)
        novel = Novel(url=url, source=self.name,
                      title=self.meta(soup, "og:novel:book_name", "og:title") or self.text(soup, "h1"),
                      author=self.meta(soup, "og:novel:author"),
                      description=self.meta(soup, "og:description"),
                      cover_url=self.meta(soup, "og:image"))
        titles: dict[int, str] = {}
        for a in soup.select("a[href]"):
            m = re.search(r"/read/\d+/p(\d+)\.html$", a["href"])
            text = a.get_text(" ", strip=True)
            if m and text not in ("立即阅读", "开始阅读", "继续阅读", "最新章节", "上一章", "下一章", "目录"):
                titles.setdefault(int(m.group(1)), text)
        last = max(titles, default=0)
        for n in range(1, last + 1):
            novel.chapters.append(ChapterRef(n, titles.get(n, f"第{n}章"), urljoin(url, f"p{n}.html")))
        return novel

    def chapter(self, ref: ChapterRef) -> Chapter:
        soup = self.f.soup(ref.url)
        art = soup.select_one("article.page-content")
        title = (self.text(art, "h2") if art else "") or ref.title
        return self.build_chapter(ref, art.select_one("section") if art else None, title)
