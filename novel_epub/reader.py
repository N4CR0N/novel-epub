"""Gömülü okuyucu için EPUB erişimi: içindekiler ve tek bölüm, tüm kitabı ayrıştırmadan (telefonda da hızlı)."""
from __future__ import annotations

import json
import posixpath
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from bs4 import BeautifulSoup

NS = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/",
      "c": "urn:oasis:names:tc:opendocument:xmlns:container", "ncx": "http://www.daisy.org/z3986/2005/ncx/"}


def _zip_path(base_dir: str, href: str) -> str:
    href = href.split("#", 1)[0]
    return posixpath.normpath(posixpath.join(base_dir, href)) if base_dir else posixpath.normpath(href)


class EpubBook:
    """Bir EPUB'ın üst verisi ve okunacak belgeleri (spine sırasıyla, içindekiler başlıklarıyla)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        with zipfile.ZipFile(self.path) as z:
            root = ET.fromstring(z.read("META-INF/container.xml"))
            opf_path = root.find(".//c:rootfile", NS).get("full-path")
            opf = ET.fromstring(z.read(opf_path))
            opf_dir = posixpath.dirname(opf_path)

            def dc(name: str) -> str:
                el = opf.find(f".//dc:{name}", NS)
                return (el.text or "").strip() if el is not None and el.text else ""

            self.title = dc("title") or self.path.stem
            self.author = dc("creator")
            self.language = dc("language")
            manifest = {it.get("id"): {"path": _zip_path(opf_dir, it.get("href", "")),
                                       "type": it.get("media-type", ""), "props": it.get("properties", "")}
                        for it in opf.findall(".//opf:manifest/opf:item", NS)}
            titles = self._toc(z, opf, manifest)
            spine = opf.find(".//opf:spine", NS)
            docs = []
            for ref in (spine.findall("opf:itemref", NS) if spine is not None else []):
                item = manifest.get(ref.get("idref", ""))
                if item and item["type"] in ("application/xhtml+xml", "text/html") and "nav" not in item["props"].split():
                    docs.append(item["path"])
            if titles:  # içindekilerde olan belgeler (kapak, boş sayfalar dışarıda)
                docs = [d for d in docs if d in titles]
            self.items: list[tuple[str, str]] = [(d, titles.get(d, "")) for d in docs]
            self.cover = next((m["path"] for m in manifest.values() if "cover-image" in m["props"].split()), None) or \
                next((m["path"] for m in manifest.values() if m["type"].startswith("image/") and "cover" in m["path"].lower()), None)

    @staticmethod
    def _toc(z: zipfile.ZipFile, opf, manifest: dict) -> dict[str, str]:
        titles: dict[str, str] = {}
        try:
            nav = next((m for m in manifest.values() if "nav" in m["props"].split()), None)
            spine = opf.find(".//opf:spine", NS)
            ncx = manifest.get(spine.get("toc", "")) if spine is not None else None
            if nav:
                soup = BeautifulSoup(z.read(nav["path"]), "html.parser")
                box = soup.find("nav", attrs={"epub:type": "toc"}) or soup
                for a in box.find_all("a", href=True):
                    titles.setdefault(_zip_path(posixpath.dirname(nav["path"]), a["href"]), a.get_text(" ", strip=True))
            elif ncx:
                root = ET.fromstring(z.read(ncx["path"]))
                for pt in root.iter(f"{{{NS['ncx']}}}navPoint"):
                    label, content = pt.find("ncx:navLabel/ncx:text", NS), pt.find("ncx:content", NS)
                    if label is not None and content is not None:
                        titles.setdefault(_zip_path(posixpath.dirname(ncx["path"]), content.get("src", "")),
                                          (label.text or "").strip())
        except Exception:
            return {}
        return titles

    def toc(self) -> list[str]:
        return [t or f"{i + 1}" for i, (_, t) in enumerate(self.items)]

    def chapter(self, i: int) -> dict:
        """i. belgenin başlığı ve paragrafları (düz metin; arayüz kendisi biçimler)."""
        doc, title = self.items[i]
        with zipfile.ZipFile(self.path) as z:
            soup = BeautifulSoup(z.read(doc), "html.parser")
        body = soup.body or soup
        for bad in body.find_all(["script", "style"]):
            bad.decompose()
        h = body.find(["h1", "h2", "h3"])
        heading = h.get_text(" ", strip=True) if h else ""
        if h:
            h.decompose()
        blocks = body.find_all(["p", "li", "blockquote", "h4", "h5", "h6"])
        paras = [b.get_text(" ", strip=True) for b in blocks if not b.find(["p", "li"])]
        if not paras:
            paras = [ln.strip() for ln in body.get_text("\n").split("\n")]
        return {"index": i, "title": heading or title, "paragraphs": [p for p in paras if p]}

    def cover_bytes(self) -> tuple[bytes, str] | None:
        if not self.cover:
            return None
        with zipfile.ZipFile(self.path) as z:
            data = z.read(self.cover)
        ext = self.cover.rsplit(".", 1)[-1].lower()
        return data, {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp",
                      "gif": "image/gif"}.get(ext, "application/octet-stream")


_CACHE: dict[tuple[str, float], EpubBook] = {}
_LOCK = threading.Lock()


def open_book(path: Path) -> EpubBook:
    key = (str(path), path.stat().st_mtime)
    with _LOCK:
        book = _CACHE.get(key)
        if book is None:
            book = EpubBook(path)
            if len(_CACHE) >= 4:
                _CACHE.pop(next(iter(_CACHE)))
            _CACHE[key] = book
        return book


class Progress:
    """Kitap başına kaldığın yer (bölüm + bölüm içi oran), veri klasöründe `okuma.json`."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _all(self) -> dict:
        try:
            return json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            return {}

    def get(self, book: str) -> dict | None:
        return self._all().get(book)

    def all(self) -> dict:
        return self._all()

    def set(self, book: str, chapter: int, frac: float, t: float | None = None, total: int = 0) -> dict:
        rec = {"ch": max(0, int(chapter)), "frac": min(1.0, max(0.0, float(frac))), "t": float(t or time.time()),
               "total": max(0, int(total or 0))}
        with self._lock:
            data = self._all()
            data[book] = rec
            self.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return rec
