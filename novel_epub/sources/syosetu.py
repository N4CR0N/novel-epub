from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from ..models import Chapter, ChapterRef, Novel
from .base import Source


class Syosetu(Source):
    """小説家になろう (ncode.syosetu.com) — yazarların ücretsiz yayımladığı Japonca web romanları.

    İçindekiler sayfa sayfa (100'er bölüm, `?p=N`); bölüm metni `.p-novel__text` (eski düzende `#novel_honbun`).
    Yazar ön/son notları (前書き/後書き) ve okunuş (ruby) parantezleri alınmaz. Sunucuyu yormamak için istekler
    arasında en az 2 sn beklenir. Tek bölümlük kısa öyküde içindekiler yoktur; metin aynı sayfadadır.
    """

    name = "syosetu"
    domains = ("ncode.syosetu.com",)
    min_delay = 2.0

    @staticmethod
    def novel_url(url: str) -> str:
        m = re.match(r"/(n\d+[a-z]+)", urlparse(url).path, re.I)
        if not m:
            raise ValueError("syosetu linki ncode.syosetu.com/<nコード>/ biçiminde olmalı")
        return f"https://ncode.syosetu.com/{m.group(1).lower()}/"

    def novel(self, url: str) -> Novel:
        url = self.novel_url(url)
        soup = self.f.soup(url)
        title = self.text(soup, ".p-novel__title") or self.text(soup, ".novel_title") or self.meta(soup, "og:title")
        author = self.text(soup, ".p-novel__author a") or self.text(soup, ".p-novel__author") or self.text(soup, ".novel_writername a")
        desc = soup.select_one(".p-novel__summary, #novel_ex")
        novel = Novel(url=url, source=self.name, title=title, author=re.sub(r"^作者[：:]\s*", "", author),
                      description=desc.get_text("\n", strip=True) if desc else self.meta(soup, "og:description"))
        links = self._episode_links(soup)
        if not links:  # tek bölümlük kısa öykü
            novel.chapters.append(ChapterRef(1, title, url))
            return novel
        last = soup.select_one("a.c-pager__item--last")
        pages = int(m.group(1)) if last and (m := re.search(r"[?&]p=(\d+)", last.get("href", ""))) else 1
        for p in range(2, pages + 1):
            links += self._episode_links(self.f.soup(f"{url}?p={p}"))
        seen: set[str] = set()
        for a in links:
            href = urljoin(url, a["href"])
            if href not in seen:
                seen.add(href)
                novel.chapters.append(ChapterRef(len(novel.chapters) + 1, a.get_text(" ", strip=True), href))
        return novel

    @staticmethod
    def _episode_links(soup) -> list:
        return [a for a in soup.select("a.p-eplist__subtitle, dl.novel_sublist2 dd.subtitle a") if a.get("href")]

    def chapter(self, ref: ChapterRef) -> Chapter:
        soup = self.f.soup(ref.url)
        self.strip_ruby(soup)  # okunuş: 漢字(かんじ) → 漢字
        body = None
        for el in soup.select(".p-novel__text, #novel_honbun"):
            cls = " ".join(el.get("class") or [])
            if "--preface" not in cls and "--afterword" not in cls:
                body = el
                break
        title = self.text(soup, "h1.p-novel__title") or self.text(soup, ".novel_subtitle") or ref.title
        return self.build_chapter(ref, body, title)
