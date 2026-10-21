from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..models import Chapter, ChapterRef, Novel
from .base import Source

AJAX = {"X-Requested-With": "XMLHttpRequest"}


class NovelFull(Source):
    """NovelFull ailesi — üç farklı düzen tek sınıfta ele alınır (sayfadan algılanır):

    1. novelfull.com: `?page=N` ile sayfalı `ul.list-chapter` (sayfa başına 50).
    2. readnovelfull.com: `/ajax/chapter-archive?novelId=<id>` tüm listeyi tek seferde verir.
    3. allnovelfull.net (NOVGO), novelfull.net, novgo.net: `/ajax-chapter-list?novelId=<id>&page=N&pageSize=50` JSON.
    Bölüm metni `#chapter-content` (veya `#chr-content`) içindedir.
    """

    name = "novelfull"
    domains = ("novelfull.com", "readnovelfull.com", "allnovelfull.net", "novelfull.net", "novgo.net")
    PAGE_SIZE = 50

    @staticmethod
    def novel_url(url: str) -> str:
        p = urlparse(url)
        path = re.sub(r"^/index\.php", "", p.path)
        m = re.match(r"/([^/]+\.html)$", path) or re.match(r"/([^/]+)/[^/]+\.html$", path)
        if not m:
            raise ValueError("novelfull linki /<ad>.html veya /<ad>/chapter-N-....html biçiminde olmalı")
        slug = m.group(1)
        if not slug.endswith(".html"):
            slug += ".html"
        # novelfull.com'da roman sayfası /index.php/<ad>.html altında da açılır; kısa biçim yeterli.
        return f"{p.scheme}://{p.netloc}/{slug}"

    @staticmethod
    def _links(html_soup, base: str, selector: str = "ul.list-chapter li a, li a[href*='/chapter-']"):
        for a in html_soup.select(selector):
            href = urljoin(base, a.get("href", ""))
            if href and "javascript" not in href:
                yield (a.get("title") or a.get_text(" ", strip=True)), href

    def novel(self, url: str) -> Novel:
        url = self.novel_url(url)
        soup = self.f.soup(url)
        def info(label: str, link_part: str) -> str:
            links = soup.select(f".info a[href*='/{link_part}/'], .m-imgtxt a[href*='/{link_part}/']")
            if links:
                return ", ".join(a.get_text(strip=True) for a in links)
            for el in soup.select(".info li, .info div"):
                txt = el.get_text(" ", strip=True)
                if txt.lower().startswith(label + ":"):
                    return ", ".join(x.strip() for x in txt.split(":", 1)[1].split(","))
            return ""

        author = info("author", "author") or self.meta(soup, "og:novel:author").replace(",", ", ")
        genres = info("genre", "genre")
        img = soup.select_one(".book img, .m-imgtxt .pic img")
        cover = self.meta(soup, "og:image") or ((img.get("data-src") or img.get("src")) if img else "")
        desc_el = soup.select_one(".desc-text") or soup.select_one(".m-desc .txt")
        title = self.text(soup, "h3.title") or self.text(soup, "h1.tit") or self.text(soup, "h1") or self.meta(soup, "og:novel:novel_name", "og:title")
        novel = Novel(
            url=url,
            source=self.name,
            title=title,
            author=author,
            cover_url=urljoin(url, cover) if cover else "",
            genres=genres,
            description=desc_el.get_text("\n", strip=True) if desc_el else self.meta(soup, "og:description"),
        )
        novel.chapters = self._chapter_list(url, soup)
        return novel

    def _chapter_list(self, url: str, soup: BeautifulSoup) -> list[ChapterRef]:
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
        refs: list[ChapterRef] = []
        seen: set[str] = set()

        def add(pairs) -> int:
            n = 0
            for title, href in pairs:
                if href in seen:
                    continue
                seen.add(href)
                refs.append(ChapterRef(len(refs) + 1, title, href))
                n += 1
            return n

        box = soup.select_one("#list-chapter[data-novel-id]")
        if box and box.get("data-list-url"):
            # NOVGO düzeni: JSON {code, html, totalPage}
            api = urljoin(origin, box["data-list-url"])
            nid = box["data-novel-id"]
            page, total = 1, 1
            while page <= total:
                try:
                    data = self.f.json(f"{api}?novelId={nid}&page={page}&pageSize={self.PAGE_SIZE}", headers=AJAX, referer=url)
                except Exception:
                    break
                if not data or data.get("code") != 200:
                    break
                total = int(data.get("totalPage") or 1)
                add(self._links(BeautifulSoup(data.get("html", ""), "lxml"), url))
                page += 1
            if refs:
                return refs
        elif soup.select_one("ul.pagination"):
            # novelfull.com düzeni: ?page=N
            last = 1
            for a in soup.select("ul.pagination a[href*='page=']"):
                m = re.search(r"[?&]page=(\d+)", a["href"])
                if m:
                    last = max(last, int(m.group(1)))
            add(self._links(soup, url, "ul.list-chapter li a"))
            for page in range(2, last + 1):
                add(self._links(self.f.soup(f"{url}?page={page}"), url, "ul.list-chapter li a"))
            if refs:
                return refs
        else:
            # readnovelfull düzeni: tüm arşiv tek HTML parçası
            rating = soup.select_one("[data-novel-id]")
            if rating:
                arch = self.f.soup(f"{origin}/ajax/chapter-archive?novelId={rating['data-novel-id']}", headers=AJAX, referer=url)
                add(self._links(arch, url, "ul.list-chapter li a"))
                if refs:
                    return refs
        # Yedek: sayfada görünen liste
        add(self._links(soup, url, "ul.list-chapter li a, ul.ul-list5 li a"))
        return refs

    def chapter(self, ref: ChapterRef) -> Chapter:
        soup = self.f.soup(ref.url)
        title = (self.text(soup, ".chapter-title") or self.text(soup, ".chr-text") or self.text(soup, "h1.chapter")) or ref.title
        content = soup.select_one("#chapter-content") or soup.select_one("#chr-content")
        return self.build_chapter(ref, content, title, self.next_link(soup, ref.url))
