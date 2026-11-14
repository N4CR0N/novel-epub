from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from ..cleaner import chapter_number
from ..models import Chapter, ChapterRef, Novel
from .base import Source
from .generic import best_content


class NovelBuddy(Source):
    """novelbuddy.com / .me — roman sayfası yalnız son bölümleri gösterir (tam liste tarayıcıda JS ile gelir).

    Bu yüzden 1. bölümden başlanır ve her bölümdeki "Next" bağlantısı izlenir (follow_next).
    """

    name = "novelbuddy"
    domains = ("novelbuddy.com", "novelbuddy.me")

    @staticmethod
    def novel_url(url: str) -> str:
        p = urlparse(url)
        slug = p.path.strip("/").split("/")[0]
        if not slug:
            raise ValueError("novelbuddy linki /<ad> ya da /<ad>/chapter-… biçiminde olmalı")
        return f"{p.scheme}://{p.netloc}/{slug}"

    def novel(self, url: str) -> Novel:
        url = self.novel_url(url)
        soup = self.f.soup(url)
        title = self.text(soup, "h1") or re.sub(r"\s*-\s*NovelBuddy$", "", self.meta(soup, "og:title"))
        novel = Novel(url=url, source=self.name, title=title,
                      author=", ".join(a.get_text(strip=True) for a in soup.select("a[href*='/authors/']")),
                      cover_url=self.meta(soup, "og:image"),
                      genres=", ".join(a.get_text(strip=True) for a in soup.select("a[href*='/genres/']"))[:200],
                      description=self.meta(soup, "og:description", "description"))
        slug = urlparse(url).path.strip("/")
        links = [(urljoin(url, a["href"]), a.get_text(" ", strip=True))
                 for a in soup.select(f"a[href*='/{slug}/chapter-']")]
        if not links:
            raise ValueError("Bölüm bağlantısı bulunamadı")
        first = min(links, key=lambda x: chapter_number(x[0]) or 10 ** 9)
        novel.chapters = [ChapterRef(1, first[1] or "Chapter 1", first[0])]
        novel.follow_next = True
        return novel

    def chapter(self, ref: ChapterRef) -> Chapter:
        soup = self.f.soup(ref.url)
        title = self.text(soup, "h1") or ref.title
        return self.build_chapter(ref, best_content(soup), title, self.next_link(soup, ref.url))
