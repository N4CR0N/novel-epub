"""Dosyadan kitap: EPUB, PDF, DOCX, TXT/MD, HTML → kitap bilgisi + bölümler.

Bölümler, dosyanın kendi yapısından (EPUB içindekiler, PDF yer imleri, Word başlık stilleri) ya da
"Chapter 3 / Bölüm 3 / 第三章" gibi başlık satırlarından ayrılır; hiçbiri yoksa eşit parçalara bölünür.
"""
from __future__ import annotations

import posixpath
import re
import warnings
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

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


UPLOAD_PREFIX = re.compile(r"^[0-9a-f]{8,12}_")  # arayüzden yüklenen dosyanın adına eklenen kimlik


def _book(path: Path, title: str, author: str = "", description: str = "") -> Novel:
    name = UPLOAD_PREFIX.sub("", path.name)
    return Novel(url=f"dosya:{name}", title=title or Path(name).stem, source="dosya", author=author,
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
def _zip_path(base_dir: str, href: str) -> str:
    """EPUB içindeki göreli bağlantı → zip içindeki tam yol (#parça ve %-kodlama atılır)."""
    href = unquote(href.split("#")[0])
    return posixpath.normpath(posixpath.join(base_dir, href)) if href else ""


def read_epub(path: Path) -> tuple[Novel, list[Chapter], bytes | None]:
    """EPUB 2/3: container.xml → OPF (üst veri, manifest, spine) → içindekiler (nav.xhtml ya da toc.ncx)."""
    ns = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/",
          "c": "urn:oasis:names:tc:opendocument:xmlns:container", "ncx": "http://www.daisy.org/z3986/2005/ncx/"}
    try:
        z = zipfile.ZipFile(path)
        root = ET.fromstring(z.read("META-INF/container.xml"))
        opf_path = root.find(".//c:rootfile", ns).get("full-path")
        opf = ET.fromstring(z.read(opf_path))
    except Exception as e:
        raise FileError(f"EPUB okunamadı: {e}") from e
    opf_dir = posixpath.dirname(opf_path)

    def dc(name: str) -> list[str]:
        return [(el.text or "").strip() for el in opf.findall(f".//dc:{name}", ns) if (el.text or "").strip()]

    desc = (dc("description") or [""])[0]
    novel = _book(path, (dc("title") or [""])[0], ", ".join(dc("creator")),
                  BeautifulSoup(desc, "html.parser").get_text(" ", strip=True) if desc else "")
    manifest: dict[str, dict] = {}
    for it in opf.findall(".//opf:manifest/opf:item", ns):
        manifest[it.get("id")] = {"path": _zip_path(opf_dir, it.get("href", "")), "type": it.get("media-type", ""),
                                  "props": it.get("properties", "")}

    toc_titles: dict[str, str] = {}
    nav = next((m for m in manifest.values() if "nav" in m["props"].split()), None)
    spine_el = opf.find(".//opf:spine", ns)
    ncx = manifest.get(spine_el.get("toc", "")) if spine_el is not None else None
    try:
        if nav:
            nsoup = BeautifulSoup(z.read(nav["path"]), "html.parser")
            box = nsoup.find("nav", attrs={"epub:type": "toc"}) or nsoup
            for a in box.find_all("a", href=True):
                toc_titles.setdefault(_zip_path(posixpath.dirname(nav["path"]), a["href"]), a.get_text(" ", strip=True))
        elif ncx:
            nroot = ET.fromstring(z.read(ncx["path"]))
            for pt in nroot.iter(f"{{{ns['ncx']}}}navPoint"):
                label = pt.find("ncx:navLabel/ncx:text", ns)
                content = pt.find("ncx:content", ns)
                if content is not None and label is not None:
                    toc_titles.setdefault(_zip_path(posixpath.dirname(ncx["path"]), content.get("src", "")),
                                          (label.text or "").strip())
    except Exception:
        toc_titles = {}

    parts: list[tuple[str, list[str]]] = []
    for ref in (spine_el.findall("opf:itemref", ns) if spine_el is not None else []):
        item = manifest.get(ref.get("idref", ""))
        if not item or item["type"] not in ("application/xhtml+xml", "text/html") or "nav" in item["props"].split():
            continue
        try:
            soup = BeautifulSoup(z.read(item["path"]), "html.parser")
        except KeyError:
            continue
        body = soup.body or soup
        h = body.find(["h1", "h2", "h3"])
        title = toc_titles.get(item["path"], "") or (h.get_text(" ", strip=True) if h else "")
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
    cover_id = next((m.get("content") for m in opf.findall(".//opf:metadata/opf:meta", ns) if m.get("name") == "cover"), None)
    cands = [m for m in manifest.values() if "cover-image" in m["props"].split()]
    cands += [manifest[cover_id]] if cover_id in manifest else []
    cands += [m for m in manifest.values() if m["type"].startswith("image/") and "cover" in m["path"].lower()]
    for m in cands:
        try:
            cover = z.read(m["path"])
            break
        except KeyError:
            continue
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


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def read_docx(path: Path) -> tuple[Novel, list[Chapter], bytes | None]:
    """Word (.docx): word/document.xml paragrafları; Başlık 1/2 (Heading 1/2, Title) stilleri bölüm başlarıdır."""
    try:
        z = zipfile.ZipFile(path)
        doc = ET.fromstring(z.read("word/document.xml"))
    except Exception as e:
        raise FileError(f"Word dosyası okunamadı: {e}") from e
    title = author = ""
    try:
        core = ET.fromstring(z.read("docProps/core.xml"))
        title = (core.findtext("{http://purl.org/dc/elements/1.1/}title") or "").strip()
        author = (core.findtext("{http://purl.org/dc/elements/1.1/}creator") or "").strip()
    except KeyError:
        pass
    style_names: dict[str, str] = {}  # stil kimliği → adı ("Heading1" → "heading 1")
    try:
        for st in ET.fromstring(z.read("word/styles.xml")).iter(f"{W}style"):
            name = st.find(f"{W}name")
            style_names[st.get(f"{W}styleId", "")] = (name.get(f"{W}val") if name is not None else "") or ""
    except KeyError:
        pass
    novel = _book(path, title, author)
    parts: list[tuple[str, list[str]]] = []
    all_paras, styled = [], False
    body = doc.find(f"{W}body")
    for p in (body.iter(f"{W}p") if body is not None else []):
        text = "".join((t.text or "") if t.tag == f"{W}t" else ("\t" if t.tag == f"{W}tab" else "\n")
                       for t in p.iter() if t.tag in (f"{W}t", f"{W}tab", f"{W}br")).strip()
        if not text:
            continue
        ps = p.find(f"{W}pPr/{W}pStyle")
        sid = ps.get(f"{W}val", "") if ps is not None else ""
        style = (style_names.get(sid) or sid).lower()
        if not parts and re.match(r"(title|subtitle|konu başlığı|alt konu başlığı)$", style):
            continue  # kapak sayfası: kitabın adı / alt başlığı, bölüm değil
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
    soup = BeautifulSoup(_decode(path.read_bytes()), "html.parser")
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
