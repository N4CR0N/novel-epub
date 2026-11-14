"""EPUB 3 yazıcı (yalnız standart kütüphane; eski okuyucular için toc.ncx de yazılır)."""
from __future__ import annotations

import html
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .models import Chapter, Novel

CSS = """
body { font-family: serif; line-height: 1.55; margin: 0 4%; }
h1, h2 { text-align: center; line-height: 1.3; }
h2 { margin: 1.2em 0 1em; font-size: 1.3em; }
p { text-indent: 1.3em; margin: 0 0 0.6em; text-align: justify; }
.meta p { text-indent: 0; text-align: center; }
.desc p { text-indent: 0; }
.cover { text-align: center; margin: 0; padding: 0; }
.cover img { max-width: 100%; max-height: 100%; }
"""

CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="EPUB/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""


def _esc(s: str) -> str:
    return html.escape(s or "", quote=False)


def _attr(s: str) -> str:
    return html.escape(s or "", quote=True)


def _xhtml(title: str, body: str, lang: str, css: str = "style/main.css") -> str:
    return (f'<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
            f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
            f'lang="{_attr(lang)}" xml:lang="{_attr(lang)}">\n<head><meta charset="utf-8"/><title>{_esc(title)}</title>'
            f'<link rel="stylesheet" type="text/css" href="{css}"/></head>\n<body>{body}</body>\n</html>\n')


def _image_type(data: bytes) -> tuple[str, str]:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png", "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif", "image/gif"
    return "jpg", "image/jpeg"


def build_epub(novel: Novel, chapters: list[Chapter], out_path: Path, language: str = "tr",
               cover: bytes | None = None, subtitle: str = "") -> Path:
    title = novel.title + (f" ({subtitle})" if subtitle else "")
    ident = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, novel.url + subtitle)}"
    authors = [x.strip() for x in (novel.author or "").split(",") if x.strip()][:3]
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    files: dict[str, str | bytes] = {"style/main.css": CSS}
    manifest = ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
                '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
                '<item id="style" href="style/main.css" media-type="text/css"/>']
    spine: list[str] = []
    toc: list[tuple[str, str]] = []  # (href, başlık)
    cover_meta = ""

    if cover:
        ext, mime = _image_type(cover)
        files[f"cover.{ext}"] = cover
        manifest.append(f'<item id="cover-img" href="cover.{ext}" media-type="{mime}" properties="cover-image"/>')
        files["cover.xhtml"] = _xhtml("Kapak", f'<div class="cover"><img src="cover.{ext}" alt="{_attr(novel.title)}"/></div>',
                                      language)
        manifest.append('<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>')
        spine.append("cover")
        cover_meta = '<meta name="cover" content="cover-img"/>'

    spine.append("nav")
    desc = "".join(f"<p>{_esc(p)}</p>" for p in (novel.description or "").split("\n") if p.strip())
    files["kunye.xhtml"] = _xhtml("Künye", (
        f"<h1>{_esc(novel.title)}</h1><div class='meta'>"
        f"<p>{_esc(novel.author)}</p><p>{_esc(novel.genres)}</p>"
        f"<p>{len(chapters)} bölüm · {_esc(subtitle)}</p><p>{_esc(novel.url)}</p></div>"
        f"<div class='desc'>{desc}</div>"), language)
    manifest.append('<item id="kunye" href="kunye.xhtml" media-type="application/xhtml+xml"/>')
    spine.append("kunye")
    toc.append(("kunye.xhtml", "Künye"))

    for ch in chapters:
        name = f"b{ch.index:05d}.xhtml"
        ch_title = ch.title or f"Bölüm {ch.index}"
        body = "".join(f"<p>{_esc(p)}</p>" for p in ch.paragraphs) or "<p>(Bu bölüm alınamadı.)</p>"
        files[name] = _xhtml(ch_title, f"<h2>{_esc(ch.title)}</h2>{body}", language)
        manifest.append(f'<item id="b{ch.index:05d}" href="{name}" media-type="application/xhtml+xml"/>')
        spine.append(f"b{ch.index:05d}")
        toc.append((name, ch_title))

    nav_items = "".join(f'<li><a href="{_attr(h)}">{_esc(t)}</a></li>' for h, t in toc)
    files["nav.xhtml"] = _xhtml("İçindekiler", f'<nav epub:type="toc" id="toc"><h1>İçindekiler</h1><ol>{nav_items}</ol></nav>',
                                language)
    points = "".join(f'<navPoint id="p{i}" playOrder="{i}"><navLabel><text>{_esc(t)}</text></navLabel>'
                     f'<content src="{_attr(h)}"/></navPoint>' for i, (h, t) in enumerate(toc, 1))
    files["toc.ncx"] = ('<?xml version="1.0" encoding="utf-8"?>\n'
                        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
                        f'<head><meta name="dtb:uid" content="{_attr(ident)}"/></head>'
                        f'<docTitle><text>{_esc(title)}</text></docTitle><navMap>{points}</navMap></ncx>')

    meta = [f'<dc:identifier id="uid">{_esc(ident)}</dc:identifier>', f"<dc:title>{_esc(title)}</dc:title>",
            f"<dc:language>{_esc(language)}</dc:language>", f'<meta property="dcterms:modified">{modified}</meta>',
            f"<dc:source>{_esc(novel.url)}</dc:source>"]
    meta += [f"<dc:creator>{_esc(a)}</dc:creator>" for a in authors]
    if novel.description:
        meta.append(f"<dc:description>{_esc(novel.description)}</dc:description>")
    if cover_meta:
        meta.append(cover_meta)
    opf = ('<?xml version="1.0" encoding="utf-8"?>\n'
           '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">\n'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">' + "".join(meta) + "</metadata>\n"
           "<manifest>" + "".join(manifest) + "</manifest>\n"
           '<spine toc="ncx">' + "".join(f'<itemref idref="{i}"/>' for i in spine) + "</spine>\n</package>\n")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".epub.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("EPUB/content.opf", opf)
        for name, data in files.items():
            z.writestr("EPUB/" + name, data)
    tmp.replace(out_path)
    return out_path
