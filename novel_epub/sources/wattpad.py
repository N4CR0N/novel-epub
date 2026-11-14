from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ..models import Chapter, ChapterRef, Novel
from .base import Source

API = "https://www.wattpad.com/api/v3"
FIELDS = "id,title,user(name),cover,description,tags,completed,parts(id,title,url)"


class Wattpad(Source):
    """wattpad.com — hikâye ve bölüm listesi herkese açık API'den; bölüm metni `apiv2/?m=storytext` ucundan.

    Hikâye linki (/story/<id>-…) ya da bölüm linki (/<bölüm id>-…) verilebilir. Ücretli (Paid) bölümler
    yalnızca ön izleme kadar gelir.
    """

    name = "wattpad"
    domains = ("wattpad.com",)

    def story_id(self, url: str) -> str:
        path = urlparse(url).path
        m = re.match(r"/story/(\d+)", path)
        if m:
            return m.group(1)
        m = re.match(r"/(\d+)(?:-|$)", path)
        if not m:
            raise ValueError("Wattpad linki /story/<id>-… ya da /<bölüm id>-… biçiminde olmalı")
        part = self.f.json(f"{API}/story_parts/{m.group(1)}?fields=groupId")
        return str(part["groupId"])

    def novel(self, url: str) -> Novel:
        sid = self.story_id(url)
        d = self.f.json(f"{API}/stories/{sid}?fields={FIELDS}")
        novel = Novel(url=f"https://www.wattpad.com/story/{sid}", source=self.name, title=d.get("title") or sid,
                      author=(d.get("user") or {}).get("name", ""), cover_url=d.get("cover") or "",
                      genres=", ".join((d.get("tags") or [])[:8]), description=d.get("description") or "")
        novel.chapters = [ChapterRef(i, p.get("title") or f"Part {i}", p.get("url") or f"https://www.wattpad.com/{p['id']}")
                          for i, p in enumerate(d.get("parts") or [], 1)]
        return novel

    def chapter(self, ref: ChapterRef) -> Chapter:
        m = re.search(r"wattpad\.com/(\d+)", ref.url)
        if not m:
            raise ValueError(f"Bölüm kimliği yok: {ref.url}")
        html = self.f.get(f"https://www.wattpad.com/apiv2/?m=storytext&id={m.group(1)}").text
        return self.build_chapter(ref, BeautifulSoup(f"<div>{html}</div>", "html.parser").div, ref.title)
