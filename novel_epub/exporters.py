"""Kitabı seçilen biçimde yazar: EPUB (varsayılan), Word (DOCX), tek dosya HTML, düz metin (TXT), Markdown.

Ek paket yok: DOCX ve EPUB zipfile ile, diğerleri düz metin olarak yazılır (exe boyutu küçük kalsın).
"""
from __future__ import annotations

import base64
import html
import re
import zipfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .epub_builder import build_epub
from .models import Chapter, Novel

# biçim → (arayüz adı, dosya uzantısı, MIME türü)
FORMATS: dict[str, tuple[str, str, str]] = {
    "epub": ("EPUB", "epub", "application/epub+zip"),
    "docx": ("Word (DOCX)", "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "html": ("HTML", "html", "text/html; charset=utf-8"),
    "txt": ("TXT", "txt", "text/plain; charset=utf-8"),
    "md": ("Markdown", "md", "text/markdown; charset=utf-8"),
}
DEFAULT_FORMAT = "epub"
EXTENSIONS = {ext: fmt for fmt, (_, ext, _) in FORMATS.items()}

# XML 1.0'da yasak denetim karakterleri (kaynak sitelerden nadiren gelir; DOCX'i bozar)
_BAD_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def normalize(fmt: str | None) -> str:
    fmt = (fmt or "").lower().strip().lstrip(".")
    return fmt if fmt in FORMATS else DEFAULT_FORMAT


def export(fmt: str, novel: Novel, chapters: list[Chapter], out_base: Path, language: str = "tr",
           cover: bytes | None = None, subtitle: str = "") -> Path:
    """out_base uzantısız yol; biçimin uzantısı eklenir. Yazılan dosyanın yolunu döndürür."""
    fmt = normalize(fmt)
    out = Path(f"{out_base}.{FORMATS[fmt][1]}")
    # sitelerden nadiren gelen denetim karakterleri EPUB/DOCX'i bozar (katı okuyucular dosyayı açmaz)
    novel = replace(novel, title=_BAD_XML.sub("", novel.title), author=_BAD_XML.sub("", novel.author or ""))
    chapters = [replace(ch, title=_BAD_XML.sub("", ch.title),
                        paragraphs=[q for q in (_BAD_XML.sub("", x).strip() for x in ch.paragraphs) if q])
                for ch in chapters]
    out.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "epub":
        return build_epub(novel, chapters, out, language=language, cover=cover, subtitle=subtitle)
    writer = {"docx": _docx, "html": _html, "txt": _txt, "md": _md}[fmt]
    writer(novel, chapters, out, language, cover, subtitle)
    return out


def _title(novel: Novel, subtitle: str) -> str:
    return novel.title + (f" ({subtitle})" if subtitle else "")


# --- düz metin ---
def _txt(novel, chapters, out: Path, language, cover, subtitle) -> None:
    head = [_title(novel, subtitle)]
    if novel.author:
        head.append(novel.author)
    parts = ["\n".join(head)]
    for ch in chapters:
        parts.append(f"{ch.title}\n{'=' * min(60, max(3, len(ch.title)))}\n\n" + "\n\n".join(ch.paragraphs))
    out.write_text("\n\n\n".join(parts) + "\n", encoding="utf-8")


# --- Markdown ---
_MD_START = re.compile(r"^(\s*)([#>+\-*]|\d+[.)])(\s)")


def _md_text(s: str) -> str:
    s = s.replace("\\", "\\\\").replace("*", "\\*").replace("_", "\\_").replace("`", "\\`")
    return _MD_START.sub(lambda m: f"{m.group(1)}\\{m.group(2)}{m.group(3)}", s)


def _md(novel, chapters, out: Path, language, cover, subtitle) -> None:
    lines = [f"# {_md_text(_title(novel, subtitle))}", ""]
    if novel.author:
        lines += [f"*{_md_text(novel.author)}*", ""]
    for ch in chapters:
        lines += [f"## {_md_text(ch.title)}", ""]
        for p in ch.paragraphs:
            lines += [_md_text(p), ""]
    out.write_text("\n".join(lines), encoding="utf-8")


# --- tek dosya HTML (kapak gömülü, içindekiler bağlantılı; tarayıcıda ve telefonda okunur) ---
_HTML_CSS = """
:root { color-scheme: light dark; --fg:#1d2733; --bg:#fbfcfe; --mut:#5b6b7c; --acc:#2f7fc4; }
@media (prefers-color-scheme: dark) { :root { --fg:#dfe7ef; --bg:#12171d; --mut:#93a3b4; --acc:#6db3f2; } }
body { margin:0; background:var(--bg); color:var(--fg); font:1.08rem/1.7 Georgia, "Times New Roman", serif; }
main { max-width:40em; margin:0 auto; padding:2.5em 1.2em 5em; }
h1 { font-size:1.9em; line-height:1.25; margin:.2em 0; } h2 { font-size:1.35em; margin:2.6em 0 1em; }
.by { color:var(--mut); margin:0 0 2em; } img.cover { display:block; max-width:min(100%, 22em); margin:0 auto 2em; }
nav ol { padding-left:1.4em; columns:2 14em; } nav a { color:var(--acc); text-decoration:none; }
p { margin:0 0 .9em; text-align:justify; hyphens:auto; } section { break-before:page; }
"""


def _cover_uri(cover: bytes | None) -> str:
    if not cover:
        return ""
    mime = ("image/png" if cover[:8] == b"\x89PNG\r\n\x1a\n" else "image/webp" if cover[8:12] == b"WEBP"
            else "image/gif" if cover[:4] == b"GIF8" else "image/jpeg")
    return f"data:{mime};base64,{base64.b64encode(cover).decode('ascii')}"


def _html(novel, chapters, out: Path, language, cover, subtitle) -> None:
    e = html.escape
    title = _title(novel, subtitle)
    body = [f"<h1>{e(title)}</h1>"]
    if novel.author:
        body.append(f'<p class="by">{e(novel.author)}</p>')
    uri = _cover_uri(cover)
    if uri:
        body.append(f'<img class="cover" src="{uri}" alt="">')
    body.append("<nav><ol>" + "".join(f'<li><a href="#b{i}">{e(ch.title)}</a></li>'
                                      for i, ch in enumerate(chapters, 1)) + "</ol></nav>")
    for i, ch in enumerate(chapters, 1):
        body.append(f'<section id="b{i}"><h2>{e(ch.title)}</h2>'
                    + "".join(f"<p>{e(p)}</p>" for p in ch.paragraphs) + "</section>")
    out.write_text(
        f'<!DOCTYPE html>\n<html lang="{e(language)}"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{e(title)}</title>'
        f"<style>{_HTML_CSS}</style></head><body><main>{''.join(body)}</main></body></html>\n",
        encoding="utf-8")


# --- Word (DOCX): başlık stilleri gerçek (Word'ün gezinti bölmesi bölümleri gösterir), her bölüm yeni sayfada ---
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _x(s: str) -> str:
    return html.escape(_BAD_XML.sub("", s), quote=False)


def _para(text: str, style: str = "") -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f'<w:p>{ppr}<w:r><w:t xml:space="preserve">{_x(text)}</w:t></w:r></w:p>'


_STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{_W}">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Georgia" w:hAnsi="Georgia" w:cs="Georgia" w:eastAsia="SimSun"/>
<w:sz w:val="24"/><w:lang w:val="{{lang}}"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="160" w:line="300" w:lineRule="auto"/><w:jc w:val="both"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:spacing w:before="2400" w:after="240"/><w:jc w:val="center"/></w:pPr><w:rPr><w:b/><w:sz w:val="52"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:jc w:val="center"/></w:pPr><w:rPr><w:i/><w:color w:val="5B6B7C"/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:keepNext/><w:pageBreakBefore/><w:spacing w:before="480" w:after="360"/><w:jc w:val="left"/><w:outlineLvl w:val="0"/></w:pPr>
<w:rPr><w:b/><w:sz w:val="34"/></w:rPr></w:style>
</w:styles>"""

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""


def _docx(novel, chapters, out: Path, language, cover, subtitle) -> None:
    body = [_para(novel.title, "Title")]
    for line in (subtitle, novel.author):
        if line:
            body.append(_para(line, "Subtitle"))
    for ch in chapters:
        body.append(_para(ch.title, "Heading1"))
        body += [_para(p) for p in ch.paragraphs]
    sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="708" w:footer="708" w:gutter="0"/>'
            "</w:sectPr>")
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document xmlns:w="{_W}"><w:body>'
                + "".join(body) + sect + "</w:body></w:document>")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f"<dc:title>{_x(_title(novel, subtitle))}</dc:title><dc:creator>{_x(novel.author or '')}</dc:creator>"
            f"<dc:language>{_x(language)}</dc:language>"
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>')
    lang_tag = {"tr": "tr-TR", "en": "en-US", "de": "de-DE", "es": "es-ES", "ru": "ru-RU"}.get(language, language)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", _STYLES.replace("{lang}", _x(lang_tag)))
        z.writestr("docProps/core.xml", core)
