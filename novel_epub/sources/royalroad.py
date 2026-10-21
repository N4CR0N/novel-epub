from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from ..models import Chapter, ChapterRef, Novel
from .base import Source

# Sayfa <style> bloklarında `display:none` verilen sınıf adları (korsan karşıtı gizli paragraflar).
HIDDEN_CLASS_RE = re.compile(r"\.([\w-]+)\s*\{[^}]*display\s*:\s*none", re.I)


class RoyalRoad(Source):
    """royalroad.com — kurgu sayfasındaki `#chapters` tablosunda tüm bölümler vardır.

    Bölüm metni `.chapter-content` içindedir; sitenin eklediği gizli (CSS ile display:none) korsan karşıtı
    paragraflar, sayfadaki <style> bloklarından bulunan sınıf adlarına göre silinir.
    """

    name = "royalroad"
    domains = ("royalroad.com",)

    @staticmethod
    def novel_url(url: str) -> str:
        p = urlparse(url)
        m = re.match(r"/fiction/(\d+)(?:/([^/]+))?", p.path)
        if not m:
            raise ValueError("royalroad linki /fiction/<id>/<ad> biçiminde olmalı")
        slug = f"/{m.group(2)}" if m.group(2) else ""
        return f"{p.scheme}://{p.netloc}/fiction/{m.group(1)}{slug}"

    def novel(self, url: str) -> Novel:
        url = self.novel_url(url)
        soup = self.f.soup(url)
        author = self.text(soup, ".fic-header h4 a[href^='/profile']") or self.text(soup, "h4 a[href^='/profile']")
        desc_el = soup.select_one(".description")
        img = soup.select_one("img.thumbnail")
        cover = self.meta(soup, "og:image") or (img.get("src") if img else "")
        novel = Novel(
            url=url,
            source=self.name,
            title=self.text(soup, ".fic-title h1") or self.meta(soup, "og:title", "twitter:title") or self.text(soup, "h1"),
            author=author,
            cover_url=urljoin(url, cover) if cover else "",
            genres=", ".join(a.get_text(strip=True) for a in soup.select(".fiction-info .tags a.fiction-tag")),
            description=desc_el.get_text("\n", strip=True) if desc_el else self.meta(soup, "og:description", "description"),
        )
        seen: set[str] = set()
        for row in soup.select("#chapters tbody tr.chapter-row, #chapters tr.chapter-row"):
            a = row.select_one("a[href*='/chapter/']")
            href = urljoin(url, row.get("data-url") or (a["href"] if a else ""))
            if "/chapter/" not in href or href in seen:
                continue
            seen.add(href)
            title = a.get_text(" ", strip=True) if a else ""
            novel.chapters.append(ChapterRef(len(novel.chapters) + 1, title, href))
        return novel

    @staticmethod
    def hidden_classes(soup) -> set[str]:
        css = " ".join(st.get_text() for st in soup.find_all("style"))
        return set(HIDDEN_CLASS_RE.findall(css))

    def chapter(self, ref: ChapterRef) -> Chapter:
        soup = self.f.soup(ref.url)
        title = self.text(soup, "h1.font-white") or ref.title
        content = soup.select_one(".chapter-content")
        if content:
            hidden = self.hidden_classes(soup)
            if hidden:
                for el in content.find_all(class_=True):
                    if not el.decomposed and hidden & set(el.get("class") or []):
                        el.decompose()
        nxt = None
        for a in soup.select("a[href*='/chapter/']"):
            if "next" in a.get_text("", strip=True).lower():
                nxt = urljoin(ref.url, a["href"])
                break
        return self.build_chapter(ref, content, title, nxt)
