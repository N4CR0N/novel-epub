"""Tarayıcı geçmişinden okunan novel sitelerini bulur (yalnız bu bilgisayarda; hiçbir yere gönderilmez).

Telefondaki Brave geçmişi, Brave Sync'te "Geçmiş" açıkken PC'deki Brave'e gelir; buradan okunur.
Chromium tabanlı tarayıcılar (Brave, Chrome, Edge) geçmişi profil klasöründeki `History` SQLite
dosyasında tutar. Tarayıcı açıkken dosya kilitli olabileceği için önce geçici bir kopyası alınır.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

BROWSERS = {
    "Brave": ("BraveSoftware", "Brave-Browser"),
    "Chrome": ("Google", "Chrome"),
    "Edge": ("Microsoft", "Edge"),
}
NOVEL_URL_RE = re.compile(
    r"(chapter|/chap[-_]?\d|/ch[-_/]?\d+|/novel[s]?/|/book/|/fiction/|/series/|/read/|bolum|episode|第.+章)", re.I)
# Novel olmayan ama adresinde bu kalıplar sık geçen siteler.
SKIP_DOMAINS = {"google.com", "youtube.com", "github.com", "reddit.com", "wikipedia.org", "amazon.com",
                "goodreads.com", "fandom.com", "translate.google.com", "bing.com", "duckduckgo.com"}


def _user_data_dirs() -> dict[str, Path]:
    out = {}
    for name, (vendor, product) in BROWSERS.items():
        if sys.platform == "win32":
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / vendor / product / "User Data"
        elif sys.platform == "darwin":
            base = Path.home() / "Library/Application Support" / vendor / product
        else:
            base = Path.home() / ".config" / (f"{vendor}/{product}" if name == "Brave" else
                                              ("google-chrome" if name == "Chrome" else "microsoft-edge"))
        out[name] = base
    return out


def history_files() -> list[tuple[str, str, Path]]:
    """(tarayıcı, profil, History dosyası) listesi."""
    found = []
    for browser, base in _user_data_dirs().items():
        if not base.exists():
            continue
        for prof in sorted(base.iterdir()):
            h = prof / "History"
            if prof.is_dir() and (h.is_file() or (prof / "Bookmarks").is_file()) and (
                    prof.name == "Default" or prof.name.startswith("Profile")):
                found.append((browser, prof.name, h))
    return found


def _read_urls(path: Path) -> list[tuple[str, str, int]]:
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "History"
        try:
            shutil.copy2(path, copy)
        except OSError:
            copy = None
        uri = f"file:{(copy or path).as_posix()}?mode=ro" + ("" if copy else "&immutable=1")
        con = sqlite3.connect(uri, uri=True)
        try:
            return con.execute("SELECT url, title, visit_count FROM urls").fetchall()
        finally:
            con.close()


def _read_bookmarks(path: Path) -> list[tuple[str, str]]:
    """Profilin Bookmarks (JSON) dosyasındaki tüm (adres, ad) çiftleri; senkronize edilmiş mobil yer işaretleri dahil."""
    out = []

    def walk(node):
        if node.get("type") == "url" and node.get("url"):
            out.append((node["url"], node.get("name", "")))
        for ch in node.get("children", []) or []:
            walk(ch)

    try:
        roots = json.loads(path.read_text("utf-8")).get("roots", {})
    except (OSError, ValueError):
        return []
    for root in roots.values():
        if isinstance(root, dict):
            walk(root)
    return out


def _domain(url: str) -> str:
    host = urlparse(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _novel_key(url: str) -> str:
    """Aynı romanın bölümlerini tek sayan anahtar: alan adı + bölüm parçaları atılmış ilk iki yol parçası."""
    segs = [p for p in urlparse(url).path.split("/") if p]
    keep = [p for p in segs if not re.search(r"(chapter|chap|^ch[-_]?\d|^\d+(\.html?)?$|bolum|episode)", p, re.I)]
    return _domain(url) + "/" + "/".join(keep[:2])


def scan(supported) -> dict:
    """Geçmişteki novel adreslerini alan adına göre gruplar.

    `supported(url)` → özel destek veren kaynağın adı ya da None.
    """
    files = history_files()
    if not files:
        return {"browsers": [], "sites": [], "error": "Bu bilgisayarda Brave/Chrome/Edge geçmişi bulunamadı."}
    sites: dict[str, dict] = defaultdict(lambda: {"urls": 0, "visits": 0, "bookmarks": 0, "novels": set(),
                                                  "sample": ("", "", -1)})
    errors, read = [], []
    for browser, profile, path in files:
        try:
            rows = _read_urls(path) if path.is_file() else []
        except sqlite3.Error as e:
            errors.append(f"{browser}/{profile}: okunamadı ({e}); tarayıcıyı kapatıp tekrar dene")
            continue
        read.append(f"{browser}/{profile}")
        marks = _read_bookmarks(path.parent / "Bookmarks")
        rows = list(rows) + [(u, t, None) for u, t in marks]
        for url, title, visits in rows:
            if not url.startswith("http") or not NOVEL_URL_RE.search(url):
                continue
            dom = _domain(url)
            if not dom or any(dom == s or dom.endswith("." + s) for s in SKIP_DOMAINS):
                continue
            s = sites[dom]
            if visits is None:  # yer işareti
                s["bookmarks"] += 1
                visits = 0
            s["urls"] += 1
            s["visits"] += visits or 0
            s["novels"].add(_novel_key(url))
            if (visits or 0) > s["sample"][2]:
                s["sample"] = (url, title or "", visits or 0)
    out = []
    for dom, s in sites.items():
        url, title, _ = s["sample"]
        out.append({"domain": dom, "urls": s["urls"], "visits": s["visits"], "bookmarks": s["bookmarks"],
                    "novels": len(s["novels"]),
                    "sample_url": url, "sample_title": title[:120], "supported": supported(url)})
    out.sort(key=lambda x: (-x["urls"], x["domain"]))
    return {"browsers": read, "sites": out[:100], "error": "; ".join(errors)}
