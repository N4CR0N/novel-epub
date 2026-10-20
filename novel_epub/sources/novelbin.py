from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from ..models import Chapter, ChapterRef, Novel
from .base import Source


class NovelBin(Source):
    """novelbin.com / .me / .net — bölüm arşivi `/ajax/chapter-archive?novelId=<ad>` ucundan gelir.

    Not: bulut ortamından sınanamadı (site 503 döndü); yapı sitenin bilinen düzenine göre yazıldı.
    """

    name = "novelbin"
    domains = ("novelbin.com", "novelbin.me", "novelbin.net", "novelbin.org", "novelbin.cc")

    @staticmethod
    def novel_url(url: str) -> tuple[str, str]:
        p = urlparse(url)
        m = re.match(r"/(b|novel-book|novel)/([^/]+)", p.path)
        if not m:
            raise ValueError("novelbin linki /b/<ad> veya /novel-book/<ad> biçiminde olmalı")
        return f"{p.scheme}://{p.netloc}/{m.group(1)}/{m.group(2)}", m.group(2)

    def novel(self, url: str) -> Novel:
        url, slug = self.novel_url(url)
        soup = self.f.soup(url)
        rating = soup.select_one("[data-novel-id]")
        novel_id = rating["data-novel-id"] if rating else slug
        author = ""
        for li in soup.select("ul.info li, .info-meta li"):
            if "author" in li.get_text(" ", strip=True).lower():
                author = ", ".join(a.get_text(strip=True) for a in li.select("a")) or li.get_text(" ", strip=True).split(":", 1)[-1].strip()
        img = soup.select_one(".book img, .books img")
        cover = (img.get("data-src") or img.get("src")) if img else self.meta(soup, "og:image")
        novel = Novel(
            url=url,
            source=self.name,
            title=self.text(soup, "h3.title") or self.meta(soup, "og:title"),
            author=author,
            cover_url=urljoin(url, cover) if cover else "",
            description=self.text(soup, ".desc-text") or self.meta(soup, "og:description"),
        )
        p = urlparse(url)
        arch = self.f.soup(f"{p.scheme}://{p.netloc}/ajax/chapter-archive?novelId={novel_id}", referer=url,
                           headers={"X-Requested-With": "XMLHttpRequest"})
        seen = set()
        for a in arch.select("ul.list-chapter li a, a[href*='chapter']"):
            href = urljoin(url, a.get("href", ""))
            if not href or href in seen:
                continue
            seen.add(href)
            novel.chapters.append(ChapterRef(len(novel.chapters) + 1, a.get("title") or a.get_text(" ", strip=True), href))
        return novel

    def chapter(self, ref: ChapterRef) -> Chapter:
        soup = self.f.soup(ref.url)
        title = self.text(soup, ".chr-title .chr-text") or self.text(soup, ".chr-title") or ref.title
        content = soup.select_one("#chr-content") or soup.select_one("#chapter-content")
        return self.build_chapter(ref, content, title, self.next_link(soup, ref.url))
