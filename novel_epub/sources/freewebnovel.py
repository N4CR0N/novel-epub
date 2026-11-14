from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..models import Chapter, ChapterRef, Novel
from .base import Source


class FreeWebNovel(Source):
    """freewebnovel.com ve aynı motoru kullanan libread.com — bölüm listesi `?ajax=chapters` JSON ucundan
    sayfa sayfa (200'er) gelir."""

    name = "freewebnovel"
    domains = ("freewebnovel.com", "libread.com")
    PAGE_SIZE = 200

    @staticmethod
    def novel_url(url: str) -> str:
        p = urlparse(url)
        m = re.match(r"(/(?:novel|libread)/[^/]+)", p.path)
        if not m:
            raise ValueError("freewebnovel/libread linki /novel/<ad> ya da /libread/<ad> biçiminde olmalı")
        return f"{p.scheme}://{p.netloc}{m.group(1)}"

    def novel(self, url: str) -> Novel:
        url = self.novel_url(url)
        soup = self.f.soup(url)
        novel = Novel(
            url=url,
            source="libread" if "libread." in urlparse(url).netloc else self.name,
            title=self.meta(soup, "og:novel:novel_name", "og:title") or self.text(soup, "h1"),
            author=self.meta(soup, "og:novel:author").replace(",", ", "),
            cover_url=urljoin(url, self.meta(soup, "og:image")) if self.meta(soup, "og:image") else "",
            genres=self.meta(soup, "og:novel:genre"),
            description=self.text(soup, ".m-desc .txt") or self.meta(soup, "og:description"),
        )
        novel.chapters = self._chapter_list(url, soup)
        return novel

    def _chapter_list(self, url: str, soup: BeautifulSoup) -> list[ChapterRef]:
        refs: list[ChapterRef] = []
        seen: set[str] = set()

        def add_from(html_soup):
            for a in html_soup.select("li a[href*='/chapter-']"):
                href = urljoin(url, a["href"])
                if href in seen:
                    continue
                seen.add(href)
                refs.append(ChapterRef(index=len(refs) + 1, title=a.get("title") or a.get_text(" ", strip=True), url=href))

        page, total = 1, 1
        while page <= total:
            try:
                data = self.f.json(
                    f"{url}?ajax=chapters&page={page}&pageSize={self.PAGE_SIZE}",
                    headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
                    referer=url,
                )
            except Exception:
                data = None
            if not data or data.get("code") != 200:
                break
            total = int(data.get("totalPage") or 1)
            add_from(BeautifulSoup(data.get("html", ""), "html.parser"))
            page += 1
        if not refs:
            # Yedek: sayfadaki listeden (yalnızca ilk 40 bölüm + son bölümler) al.
            box = soup.select("#indexListPage ul.ul-list5")
            for ul in box[1:] or box:
                add_from(ul)
        return refs

    def chapter(self, ref: ChapterRef) -> Chapter:
        soup = self.f.soup(ref.url)
        title = self.text(soup, "span.chapter") or self.text(soup, ".m-read .chapter") or ref.title
        content = soup.select_one("#article") or soup.select_one(".m-read .txt")
        return self.build_chapter(ref, content, title, self.next_link(soup, ref.url))
