from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from ..models import Chapter, ChapterRef, Novel
from .base import Source


class Kakuyomu(Source):
    """カクヨム (kakuyomu.jp) — yazarların ücretsiz yayımladığı Japonca web romanları.

    Eser sayfasındaki `__NEXT_DATA__` (Apollo durumu) `tableOfContentsV2` ile tüm bölümleri sırayla verir;
    bölüm metni `.widget-episodeBody`. Okunuş (ruby) parantezleri alınmaz; istekler arasında en az 2 sn beklenir.
    """

    name = "kakuyomu"
    domains = ("kakuyomu.jp",)
    min_delay = 2.0

    @staticmethod
    def work_id(url: str) -> str:
        m = re.match(r"/works/(\d+)", urlparse(url).path)
        if not m:
            raise ValueError("kakuyomu linki kakuyomu.jp/works/<numara> biçiminde olmalı")
        return m.group(1)

    def novel(self, url: str) -> Novel:
        wid = self.work_id(url)
        url = f"https://kakuyomu.jp/works/{wid}"
        soup = self.f.soup(url)
        script = soup.select_one("script#__NEXT_DATA__")
        if not script or not script.string:
            raise ValueError("kakuyomu eser verisi bulunamadı")
        state = json.loads(script.string)["props"]["pageProps"]["__APOLLO_STATE__"]
        work = state.get(f"Work:{wid}") or {}
        author = state.get((work.get("author") or {}).get("__ref", ""), {})
        novel = Novel(url=url, source=self.name, title=work.get("title") or self.meta(soup, "og:title"),
                      author=author.get("activityName") or author.get("name") or "",
                      description=work.get("introduction") or self.meta(soup, "og:description"))
        toc = next((v for k, v in work.items() if k.startswith("tableOfContents")), []) or []
        for part in toc:
            section = state.get(part.get("__ref", ""), {})
            for ref in section.get("episodeUnions") or []:
                ep = state.get(ref.get("__ref", ""), {})
                if ep.get("id"):
                    novel.chapters.append(ChapterRef(len(novel.chapters) + 1, ep.get("title") or "",
                                                     f"{url}/episodes/{ep['id']}"))
        return novel

    def chapter(self, ref: ChapterRef) -> Chapter:
        soup = self.f.soup(ref.url)
        self.strip_ruby(soup)
        title = self.text(soup, ".widget-episodeTitle") or ref.title
        return self.build_chapter(ref, soup.select_one(".widget-episodeBody"), title)
