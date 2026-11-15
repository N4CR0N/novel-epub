"""Güvenlik/sağlamlık incelemesinde bulunan sorunların regresyon testleri (ağsız)."""
from __future__ import annotations

import io
import json
import time
from pathlib import Path

from novel_epub.models import Novel


def _lorem(n: int, seed: str) -> list[str]:
    return [f"{seed} paragraph {i}: the lantern swayed while Arin counted the steps to the mill." for i in range(n)]


# --- cleaner: sessizce metin silme / takılma ---------------------------------------------------------------

def test_cleaner_keeps_story_lines_that_look_like_noise():
    from novel_epub.cleaner import clean_paragraphs

    keep = ["He said he would visit Paris for the summer and never come back.",
            'Ed: "Stop right there," the captain shouted across the deck.']
    out = clean_paragraphs(keep + ["Visit freewebnovel.com for the latest chapters."], "")
    assert out == keep


def test_inline_watermark_regex_is_fast_on_long_whitespace():
    from novel_epub.cleaner import clean_paragraphs

    t = time.perf_counter()
    clean_paragraphs(["a" + " " * 20000 + "b"], "")
    assert time.perf_counter() - t < 1.0


# --- kitap klasörü çakışması --------------------------------------------------------------------------------

def _novel(title: str, url: str, source: str = "site") -> Novel:
    return Novel(url=url, title=title, source=source)


def test_book_dirname_keeps_legacy_and_separates_collisions(tmp_path: Path):
    from novel_epub.store import BookStore, book_dirname

    a = BookStore(tmp_path, _novel("Same Name", "https://a.example/novel/1"))
    assert a.dir.name == "site-same-name"  # ilk kitap eski biçimdeki adı alır
    # aynı kitap (http/www/son / farkı) aynı klasöre döner
    assert book_dirname(tmp_path, _novel("Same Name", "http://www.a.example/novel/1/")) == "site-same-name"
    b = BookStore(tmp_path, _novel("Same Name", "https://a.example/novel/2"))
    assert b.dir.name != a.dir.name and b.dir.name.startswith("site-same-name-")
    # Latin harfi olmayan iki başlık "kitap"ta çakışmaz
    c = book_dirname(tmp_path, _novel("天道", "https://a.example/n/3"))
    d = book_dirname(tmp_path, _novel("魔法", "https://a.example/n/4"))
    assert c != d and c.startswith("site-kitap-")
    # 60 karakterde kesilen uzun başlıklar da ayrışır
    long = "x" * 70
    assert book_dirname(tmp_path, _novel(long + "a", "https://a/1")) != book_dirname(tmp_path, _novel(long + "b", "https://a/2"))


def test_book_dirname_finds_old_upload_folder(tmp_path: Path):
    from novel_epub.store import book_dirname

    old = tmp_path / "dosya-1a2b3c4d-my-book"
    old.mkdir()
    (old / "kitap.json").write_text(json.dumps({"url": "dosya:1a2b3c4d_My Book.txt", "title": "1a2b3c4d_My Book"}))
    assert book_dirname(tmp_path, _novel("My Book", "dosya:My Book.txt", "dosya")) == old.name


# --- yüklemeler ---------------------------------------------------------------------------------------------

def test_upload_is_content_addressed_and_titled_without_prefix(tmp_path: Path, monkeypatch):
    from novel_epub import web

    monkeypatch.setattr(web, "UPLOADS", tmp_path / "up")
    c = web.app.test_client()
    txt = "\n\n".join(["Chapter 1", *_lorem(2, "a"), "Chapter 2", *_lorem(2, "b")]).encode()
    send = lambda: c.post("/api/upload", data={"file": (io.BytesIO(txt), "Ember Road.txt")},
                          content_type="multipart/form-data").get_json()
    first, second = send(), send()
    assert first["id"] == second["id"]
    assert first["title"] == "Ember Road"
    assert len([p for p in (tmp_path / "up").iterdir()]) == 1

    from novel_epub.files import load_file

    novel, _, _ = load_file(tmp_path / "up" / first["id"])
    assert novel.url == "dosya:Ember Road.txt"


def test_old_uploads_are_pruned(tmp_path: Path, monkeypatch):
    import os

    from novel_epub import web

    up = tmp_path / "up"
    up.mkdir()
    stale = up / "deadbeef0000_old.txt"
    stale.write_text("x")
    old = time.time() - (web.UPLOAD_KEEP_DAYS + 1) * 86400
    os.utime(stale, (old, old))
    monkeypatch.setattr(web, "UPLOADS", up)
    web._prune_uploads()
    assert not stale.exists()


# --- ağ: yerel adres, Retry-After, Durdur -----------------------------------------------------------------

def test_fetcher_refuses_local_and_non_http_urls():
    import pytest

    from novel_epub.fetcher import FetchError, Fetcher

    f = Fetcher(delay=0)
    for url in ("file:///etc/passwd", "http://127.0.0.1:5000/api/settings", "http://192.168.1.10/",
                "http://[::1]/", "http://localhost/", "http://169.254.169.254/latest/meta-data/"):
        with pytest.raises(FetchError):
            f.get(url)


def test_fetcher_caps_retry_after_and_stops_on_cancel(monkeypatch):
    import threading

    import pytest

    from novel_epub import fetcher as fm

    class Resp:
        status_code, url, text = 429, "", ""
        headers = {"Retry-After": "86400"}

    stop = threading.Event()
    f = fm.Fetcher(delay=0, retries=2, stop=stop)
    monkeypatch.setattr(fm, "check_url", lambda url: None)
    monkeypatch.setattr(f.session, "get", lambda *a, **k: Resp())
    waits = []
    monkeypatch.setattr(f, "_sleep", lambda s: waits.append(s))
    with pytest.raises(fm.FetchError):
        f.get("https://site.example/a")
    assert waits and max(waits) <= fm.MAX_RETRY_AFTER

    f2 = fm.Fetcher(delay=0, retries=2, stop=stop)
    monkeypatch.setattr(f2.session, "get", lambda *a, **k: Resp())
    stop.set()
    t = time.perf_counter()
    with pytest.raises(fm.FetchError, match="Durduruldu"):
        f2.get("https://site.example/a")
    assert time.perf_counter() - t < 1


# --- anahtarlar ---------------------------------------------------------------------------------------------

def test_saving_settings_with_env_key_keeps_file_keys(tmp_path: Path, monkeypatch):
    from novel_epub import web

    monkeypatch.setattr(web, "SETTINGS_PATH", tmp_path / "ayarlar.json")
    monkeypatch.setattr(web, "_keyring", lambda: None)
    (tmp_path / "ayarlar.json").write_text(json.dumps({"models": [], "keys": {"openai": "sk-UYDURMA"}}), "utf-8")
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaORTAM")
    s = web.load_settings()
    assert s["key_store"] == "ortam"
    s["theme"] = "dark"
    web.save_settings(s)
    saved = json.loads((tmp_path / "ayarlar.json").read_text("utf-8"))
    assert saved["keys"] == {"openai": "sk-UYDURMA"}  # dosyadaki anahtar silinmedi, ortamdaki diske yazılmadı


def test_unknown_key_format_is_not_sent_anywhere(tmp_path: Path, monkeypatch):
    import pytest

    from novel_epub import providers, web

    calls = []
    with pytest.raises(providers.UnknownFormat):
        providers.detect("tamamen-bilinmeyen-bicim", get=lambda u, h: calls.append(u) or (200, {"data": []}))
    assert calls == []
    # kullanıcı sağlayıcıyı seçince yalnız ona sorulur
    p, _ = providers.detect("tamamen-bilinmeyen-bicim", provider="groq",
                            get=lambda u, h: calls.append(u) or (200, {"data": [{"id": "llama-x"}]}))
    assert p.id == "groq" and len(calls) == 1 and "groq" in calls[0]

    monkeypatch.setattr(web, "SETTINGS_PATH", tmp_path / "ayarlar.json")
    r = web.app.test_client().post("/api/keys", json={"key": "tamamen-bilinmeyen-bicim"})
    assert r.status_code == 400 and r.get_json()["choose_provider"] is True
