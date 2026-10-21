"""Dosyadan kitap: EPUB, PDF, DOCX, TXT/MD, HTML → kitap bilgisi + bölümler.

Bölümler, dosyanın kendi yapısından (EPUB içindekiler, PDF yer imleri, Word başlık stilleri) ya da
"Chapter 3 / Bölüm 3 / 第三章" gibi başlık satırlarından ayrılır; hiçbiri yoksa eşit parçalara bölünür.
"""
from __future__ import annotations

import re
import warnings
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from .cleaner import clean_paragraphs, extract_paragraphs
from .models import Chapter, ChapterRef, Novel

SUPPORTED = (".epub", ".pdf", ".docx", ".txt", ".md", ".html", ".htm")

HEADING_RE = re.compile(
    r"^\s*(?:"
    r"(?:chapter|chap\.|bölüm|kısım|part|book|volume|cilt|episode|prologue|epilogue|önsöz|sonsöz|giriş|interlude)"
    r"\b[\s\d.:\-–—IVXLC]*.{0,80}"
    r"|第\s*[0-9一二三四五六七八九十百千零〇两]+\s*[章话話回节節卷].{0,40}"
    r")\s*$",
    re.I,
)
CHUNK_WORDS = 3000  # başlık bulunamazsa bölüm başına yaklaşık kelime
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)  # EPUB XHTML'i HTML ayrıştırıcıyla okunur


class FileError(ValueError):
    pass


def _book(path: Path, title: str, author: str = "", description: str = "") -> Novel:
    return Novel(url=f"dosya:{path.name}", title=title or path.stem, source="dosya", author=author,
                 description=description)


def _finish(novel: Novel, parts: list[tuple[str, list[str]]]) -> tuple[Novel, list[Chapter]]:
    chapters: list[Chapter] = []
    for title, paras in parts:
        paras = clean_paragraphs(paras, title)
        if not paras:
            continue
        i = len(chapters) + 1
        chapters.append(Chapter(i, title or f"Bölüm {i}", f"{novel.url}#{i}", paras))
    if not chapters:
        raise FileError("Dosyada okunabilir metin bulunamadı.")
    novel.chapters = [ChapterRef(c.index, c.title, c.url) for c in chapters]
    return novel, chapters


def split_by_headings(paras: list[str], min_chapters: int = 2) -> list[tuple[str, list[str]]]:
    """Başlık satırlarından böler; yeterli başlık yoksa eşit (≈CHUNK_WORDS kelime) parçalara."""
    heads = [i for i, p in enumerate(paras) if len(p) <= 100 and HEADING_RE.match(p)]
    if len(heads) >= min_chapters:
        parts = []
        if heads[0] > 0 and sum(len(p.split()) for p in paras[:heads[0]]) > 150:
            parts.append(("Giriş", paras[:heads[0]]))
        for a, b in zip(heads, heads[1:] + [len(paras)]):
            parts.append((paras[a], paras[a + 1:b]))
        return parts
    parts, cur, words = [], [], 0
    for p in paras:
        cur.append(p)
        words += len(p.split())
        if words >= CHUNK_WORDS:
            parts.append((f"Kısım {len(parts) + 1}", cur))
            cur, words = [], 0
    if cur:
        parts.append((f"Kısım {len(parts) + 1}", cur))
    return parts


def reflow(lines: list[str]) -> list[str]:
    """PDF/TXT satırlarını paragrafa çevirir: satır sonunda bölünmüş cümleleri birleştirir."""
    paras, cur = [], ""
    for raw in lines:
        line = raw.strip()
        if not line:
            if cur:
                paras.append(cur)
                cur = ""
            continue
        if HEADING_RE.match(line) and len(line) <= 100:
            if cur:
                paras.append(cur)
            paras.append(line)
            cur = ""
            continue
        if cur.endswith("-") and line[:1].islower():
            cur = cur[:-1] + line  # satır sonu tirelemesi
        elif cur and not re.search(r"[.!?…:\"”’»)\]]$", cur):
            cur += " " + line
        else:
            if cur:
                paras.append(cur)
            cur = line
    if cur:
        paras.append(cur)
    return paras


# --- türler ---
def read_epub(path: Path) -> tuple[Novel, list[Chapter], bytes | None]:
    import ebooklib
    from ebooklib import epub

    book = epub.read_epub(str(path), options={"ignore_ncx": False})

    def meta(name: str) -> str:
        v = book.get_metadata("DC", name)
        return v[0][0].strip() if v and v[0] and v[0][0] else ""

    novel = _book(path, meta("title"), ", ".join(m[0] for m in book.get_metadata("DC", "creator") if m[0]),
                  BeautifulSoup(meta("description"), "lxml").get_text(" ", strip=True) if meta("description") else "")
    toc_titles: dict[str, str] = {}

    def walk(items):
        for it in items:
            if isinstance(it, tuple):
                walk([it[0]])
                walk(it[1])
            elif getattr(it, "href", None):
                toc_titles.setdefault(it.href.split("#")[0], it.title)

    walk(book.toc)
    parts: list[tuple[str, list[str]]] = []
    for idref, _linear in book.spine:
        item = book.get_item_with_id(idref)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        soup = BeautifulSoup(item.get_content(), "lxml")
        body = soup.body or soup
        h = body.find(["h1", "h2", "h3"])
        title = toc_titles.get(item.get_name(), "") or (h.get_text(" ", strip=True) if h else "")
        paras = extract_paragraphs(body)
        if sum(len(p) for p in paras) < 80:  # kapak, içindekiler, boş sayfa
            continue
        if title and paras and paras[0].strip() == title.strip():
            paras = paras[1:]
        if sum(len(p.split()) for p in paras) > CHUNK_WORDS * 6:  # tüm kitap tek dosyada
            parts += split_by_headings(paras)
        else:
            parts.append((title, paras))
    cover = None
    for it in book.get_items():
        if it.get_type() == ebooklib.ITEM_COVER or ("cover" in (it.get_name() or "").lower()
                                                     and (it.media_type or "").startswith("image/")):
            cover = it.get_content()
            break
    novel, chapters = _finish(novel, parts)
    return novel, chapters, cover


def read_pdf(path: Path) -> tuple[Novel, list[Chapter], bytes | None]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as e:
            raise FileError("PDF şifreli; şifresiz bir kopya gerekli.") from e
    info = reader.metadata or {}
    novel = _book(path, (info.get("/Title") or "").strip(), (info.get("/Author") or "").strip())
    pages = [(p.extract_text() or "").splitlines() for p in reader.pages]
    if sum(len("".join(lines)) for lines in pages) < 200:
        raise FileError("Bu PDF'de metin yok (taranmış görüntü olabilir); önce OCR'lı bir sürüm gerekir.")
    # Sayfaların çoğunda aynen tekrarlanan üst/alt bilgi satırları ve sayfa numaraları.
    edge = Counter(l.strip() for lines in pages for l in (lines[:2] + lines[-2:]) if l.strip())
    repeated = {l for l, n in edge.items() if n >= max(3, len(pages) * 0.4)}

    def page_lines(i: int) -> list[str]:
        return [l for l in pages[i] if l.strip() not in repeated and not re.fullmatch(r"\s*[-–]?\s*\d{1,4}\s*[-–]?\s*", l)]

    outline = []
    try:
        for o in reader.outline:
            if not isinstance(o, list):
                outline.append((o.title.strip(), reader.get_destination_page_number(o)))
    except Exception:
        outline = []
    outline = sorted({(p, t) for t, p in outline if t})
    if len(outline) >= 2:
        parts = []
        if outline[0][0] > 0:
            front = reflow([l for i in range(outline[0][0]) for l in page_lines(i)])
            if sum(len(p.split()) for p in front) > 150:
                parts.append(("Giriş", front))
        for (a, title), (b, _) in zip(outline, outline[1:] + [(len(pages), "")]):
            paras = reflow([l for i in range(a, max(a + 1, b)) for l in page_lines(i)])
            if paras and paras[0].strip().lower() == title.lower():
                paras = paras[1:]
            parts.append((title, paras))
    else:
        parts = split_by_headings(reflow([l for i in range(len(pages)) for l in page_lines(i) + [""]]))
    novel, chapters = _finish(novel, parts)
    return novel, chapters, None


def read_docx(path: Path) -> tuple[Novel, list[Chapter], bytes | None]:
    import docx

    d = docx.Document(str(path))
    cp = d.core_properties
    novel = _book(path, (cp.title or "").strip(), (cp.author or "").strip())
    parts: list[tuple[str, list[str]]] = []
    all_paras, styled = [], False
    for p in d.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        style = (p.style.name or "").lower() if p.style is not None else ""
        if re.match(r"(heading|başlık|title)\s*[12]?$", style):
            styled = True
            parts.append((text, []))
        elif parts:
            parts[-1][1].append(text)
        all_paras.append(text)
    if not styled or len(parts) < 2:
        parts = split_by_headings(all_paras)
    novel, chapters = _finish(novel, parts)
    return novel, chapters, None


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1254", "gb18030", "shift_jis", "latin-1"):
        try:
            text = data.decode(enc)
            if enc == "utf-16" and "\x00" in text:
                continue
            return text
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def read_text(path: Path) -> tuple[Novel, list[Chapter], bytes | None]:
    text = _decode(path.read_bytes()).replace("\r\n", "\n")
    lines = text.split("\n")
    if path.suffix.lower() == ".md":
        heads = [l.lstrip("#").strip() for l in lines if re.match(r"^#{1,2}\s+\S", l)]
        lines = [l.lstrip("#").strip() if re.match(r"^#{1,6}\s", l) else l for l in lines]
    else:
        heads = []
    # Boş satırla ayrılmış paragraflar varsa onları kullan, yoksa her satır bir paragraf.
    paras = reflow(lines) if "\n\n" in text else [l.strip() for l in lines if l.strip()]
    novel = _book(path, "")
    if len(heads) >= 2:
        hs = set(heads)
        parts, cur = [], None
        for p in paras:
            if p in hs:
                cur = (p, [])
                parts.append(cur)
            elif cur:
                cur[1].append(p)
        novel, chapters = _finish(novel, parts)
    else:
        novel, chapters = _finish(novel, split_by_headings(paras))
    return novel, chapters, None


def read_html(path: Path) -> tuple[Novel, list[Chapter], bytes | None]:
    soup = BeautifulSoup(_decode(path.read_bytes()), "lxml")
    title = soup.title.get_text(strip=True) if soup.title else ""
    body = soup.body or soup
    heads = body.find_all(["h1", "h2"])
    novel = _book(path, title)
    if len(heads) >= 2:
        parts = []
        for h in heads:
            paras = []
            for sib in h.find_next_siblings():
                if sib.name in ("h1", "h2"):
                    break
                t = sib.get_text(" ", strip=True)
                if t:
                    paras.append(t)
            parts.append((h.get_text(" ", strip=True), paras))
        return (*_finish(novel, parts), None)
    return (*_finish(novel, split_by_headings(extract_paragraphs(body))), None)


READERS = {".epub": read_epub, ".pdf": read_pdf, ".docx": read_docx, ".txt": read_text, ".md": read_text,
           ".html": read_html, ".htm": read_html}


def load_file(path: str | Path) -> tuple[Novel, list[Chapter], bytes | None]:
    """Dosyayı okur: (kitap bilgisi, bölümler, kapak resmi ya da None)."""
    path = Path(path)
    reader = READERS.get(path.suffix.lower())
    if reader is None:
        raise FileError(f"Desteklenmeyen dosya türü: {path.suffix or '?'} (desteklenen: {', '.join(SUPPORTED)})")
    if not path.exists():
        raise FileError(f"Dosya bulunamadı: {path}")
    return reader(path)
