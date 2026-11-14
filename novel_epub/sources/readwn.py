from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..models import Chapter, ChapterRef, Novel
from .base import Source


class ReadWN(Source):
    """FanMTL / ReadWN / WuxiaBox ailesi (aynı motor).

    Roman sayfası ilk 100 bölümü listeler; kalanlar `/e/extend/fy.php?page=N&wjm=<ad>` sayfalarında 100'er
    (N=1..son). Bölüm linki `/novel/<ad>_<n>.html`, metin `div.chapter-content` içindedir.
    """

    name = "readwn"
    domains = ("fanmtl.com", "readwn.com", "wuxiabox.com")

    @staticmethod
    def novel_url(url: str) -> tuple[str, str]:
        p = urlparse(url)
        m = re.match(r"/novel/([^/_]+?)(?:_\d+)?\.html$", p.path)
        if not m:
            raise ValueError("Link /novel/<ad>.html ya da /novel/<ad>_<n>.html biçiminde olmalı")
        return f"{p.scheme}://{p.netloc}/novel/{m.group(1)}.html", m.group(1)

    def novel(self, url: str) -> Novel:
        url, slug = self.novel_url(url)
        soup = self.f.soup(url)
        img = soup.select_one("figure.cover img, .novel-header img")
        cover = (img.get("data-src") or img.get("src") or "") if img else ""
        host = urlparse(url).netloc.removeprefix("www.").split(".")[0]
        novel = Novel(
            url=url, source=host,
            title=self.text(soup, "h1.novel-title") or self.text(soup, "h1"),
            author=self.text(soup, "[itemprop=author]"),
            cover_url=urljoin(url, cover) if cover else "",
            genres=", ".join(a.get_text(strip=True) for a in soup.select(".categories a")),
            description=self.text(soup, ".summary .content"),
        )
        refs: list[ChapterRef] = []
        seen: set[str] = set()

        def add_from(s: BeautifulSoup) -> None:
            for a in s.select("ul.chapter-list li a[href]"):
                href = urljoin(url, a["href"])
                if href not in seen:
                    seen.add(href)
                    title = a.get("title") or self.text(a, ".chapter-title") or a.get_text(" ", strip=True)
                    refs.append(ChapterRef(len(refs) + 1, title, href))

        add_from(soup)
        nums = [int(n) for a in soup.select("a[href*='fy.php']") for n in re.findall(r"[?&]page=(\d+)", a["href"])]
        for page in range(1, max(nums, default=0) + 1):
            add_from(self.f.soup(urljoin(url, f"/e/extend/fy.php?page={page}&wjm={slug}"), referer=url))
        novel.chapters = refs
        return novel

    def chapter(self, ref: ChapterRef) -> Chapter:
        soup = self.f.soup(ref.url)
        title = self.text(soup, ".chapter-header h2, .titles h2, span.chapter-title") or ref.title
        return self.build_chapter(ref, soup.select_one("div.chapter-content"), title, self.next_link(soup, ref.url))
