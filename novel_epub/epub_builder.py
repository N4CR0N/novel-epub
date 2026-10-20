from __future__ import annotations

import html
import uuid
from pathlib import Path

from ebooklib import epub

from .models import Chapter, Novel

CSS = """
body { font-family: serif; line-height: 1.55; margin: 0 4%; }
h1, h2 { text-align: center; line-height: 1.3; }
h2 { margin: 1.2em 0 1em; font-size: 1.3em; }
p { text-indent: 1.3em; margin: 0 0 0.6em; text-align: justify; }
.meta p { text-indent: 0; text-align: center; }
.desc p { text-indent: 0; }
"""


def _esc(s: str) -> str:
    return html.escape(s or "", quote=False)


def build_epub(novel: Novel, chapters: list[Chapter], out_path: Path, language: str = "tr",
               cover: bytes | None = None, subtitle: str = "") -> Path:
    book = epub.EpubBook()
    book.set_identifier(str(uuid.uuid5(uuid.NAMESPACE_URL, novel.url + subtitle)))
    book.set_title(novel.title + (f" ({subtitle})" if subtitle else ""))
    book.set_language(language)
    for a in [x.strip() for x in (novel.author or "").split(",") if x.strip()][:3]:
        book.add_author(a)
    if novel.description:
        book.add_metadata("DC", "description", novel.description)
    book.add_metadata("DC", "source", novel.url)

    style = epub.EpubItem(uid="style", file_name="style/main.css", media_type="text/css", content=CSS)
    book.add_item(style)

    if cover:
        book.set_cover("cover.jpg", cover)

    intro = epub.EpubHtml(title="Künye", file_name="kunye.xhtml", lang=language)
    desc = "".join(f"<p>{_esc(p)}</p>" for p in (novel.description or "").split("\n") if p.strip())
    intro.content = (
        f"<h1>{_esc(novel.title)}</h1><div class='meta'>"
        f"<p>{_esc(novel.author)}</p><p>{_esc(novel.genres)}</p>"
        f"<p>{len(chapters)} bölüm · {_esc(subtitle)}</p><p>{_esc(novel.url)}</p></div>"
        f"<div class='desc'>{desc}</div>"
    )
    intro.add_item(style)
    book.add_item(intro)

    items = []
    for ch in chapters:
        item = epub.EpubHtml(title=ch.title or f"Bölüm {ch.index}", file_name=f"b{ch.index:05d}.xhtml", lang=language)
        body = "".join(f"<p>{_esc(p)}</p>" for p in ch.paragraphs) or "<p>(Bu bölüm alınamadı.)</p>"
        item.content = f"<h2>{_esc(ch.title)}</h2>{body}"
        item.add_item(style)
        book.add_item(item)
        items.append(item)

    book.toc = [epub.Link("kunye.xhtml", "Künye", "kunye")] + items
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", intro] + items
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(out_path), book)
    return out_path
