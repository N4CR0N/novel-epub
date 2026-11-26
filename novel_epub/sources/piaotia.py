from __future__ import annotations

import html as htmllib
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..cleaner import clean_paragraphs
from ..models import Chapter, ChapterRef, Novel
from .base import Source


class Piaotia(Source):
    """飘天文学 (piaotia.com) — Çince ham metin (GBK). İçindekiler `/html/<a>/<b>/` sayfasında tek parça;
    bölüm metni H1'den sonraki tablodan sonra `<br />` ile ayrılmış düz satırlardır (kapanmayan etiketler
    yüzünden HTML ayrıştırıcıya güvenilmez, metin dilimlenir)."""

    name = "piaotia"
    domains = ("piaotia.com",)
    min_delay = 1.5

    def _html(self, url: str) -> str:
        return self.f.get(url).content.decode("gbk", "replace")

    @staticmethod
    def toc_url(url: str) -> str:
        p = urlparse(url)
        m = re.search(r"/(?:bookinfo|html)/(\d+)/(\d+)", p.path)
        if not m:
            raise ValueError("piaotia linki /bookinfo/<a>/<b>.html ya da /html/<a>/<b>/ biçiminde olmalı")
        return f"https://www.piaotia.com/html/{m.group(1)}/{m.group(2)}/"

    def novel(self, url: str) -> Novel:
        toc = self.toc_url(url)
        soup = BeautifulSoup(self._html(toc), "html.parser")
        title = self.text(soup, "h1")
        title = re.sub(r"(最新章节|全文阅读|章节目录)$", "", title).strip()
        novel = Novel(url=toc, source=self.name, title=title)
        seen: set[str] = set()
        for a in soup.select("div.centent li a[href]"):
            href = urljoin(toc, a["href"])
            if re.search(r"/\d+\.html$", href) and href not in seen:
                seen.add(href)
                novel.chapters.append(ChapterRef(len(novel.chapters) + 1, a.get_text(" ", strip=True), href))
        return novel

    @staticmethod
    def parse_chapter(page: str) -> tuple[str, list[str]]:
        low = page.lower()
        i = low.find("<h1")
        if i == -1:
            return "", []
        j = low.find("</h1>", i)
        head = BeautifulSoup(page[i:j + 5], "html.parser").h1
        if head and head.a:
            head.a.decompose()  # H1'de önce kitap adı bağlantısı, sonra bölüm adı
        title = head.get_text(" ", strip=True) if head else ""
        start = low.find("</table>", j)
        start = (start + len("</table>")) if start != -1 else j + 5
        ends = [k for k in (low.find("<!--", start), low.find("<div", start), low.find("<center", start)) if k != -1]
        body = page[start:min(ends) if ends else len(page)]
        lines = [re.sub(r"<[^>]+>", "", x) for x in re.split(r"<br\s*/?>", body, flags=re.I)]
        lines = [htmllib.unescape(x).replace("\xa0", " ").strip() for x in lines]
        return title, [x for x in lines if x]

    def chapter(self, ref: ChapterRef) -> Chapter:
        title, paras = self.parse_chapter(self._html(ref.url))
        title = title or ref.title
        return Chapter(index=ref.index, title=title, url=ref.url, paragraphs=clean_paragraphs(paras, title))
