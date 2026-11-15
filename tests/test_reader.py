"""Gömülü okuyucu: EPUB içindekiler, bölüm, kaldığın yer, ağdaki telefon için yalnız okuma (ağsız)."""
from __future__ import annotations

from pathlib import Path

from novel_epub.models import Chapter, Novel


def _book(out: Path) -> Path:
    from novel_epub.exporters import export

    chs = [Chapter(i, f"Bölüm {i}: Lorem {i}", f"u{i}",
                   [f"Lorem ipsum {i}.{k} dolor sit amet, fener sallandı ve Arin basamakları saydı." for k in range(6)] + ["***"])
           for i in range(1, 4)]
    novel = Novel(url="https://x.example/n", title="Lorem Kitap", source="test", author="Yazar")
    return export("epub", novel, chs, out / "lorem-kitap_1-3_tr", language="tr", cover=None, subtitle="")


def test_reader_toc_chapter_and_progress(tmp_path: Path, monkeypatch):
    from novel_epub import web

    out = tmp_path / "cikti"
    out.mkdir()
    path = _book(out)
    monkeypatch.setattr(web, "OUTPUT", out)
    monkeypatch.setattr(web, "BASE", tmp_path)
    c = web.app.test_client()
    b = c.get(f"/api/read/{path.name}").get_json()
    assert b["title"] == "Lorem Kitap" and b["progress"] is None
    assert b["toc"][-3:] == ["Bölüm 1: Lorem 1", "Bölüm 2: Lorem 2", "Bölüm 3: Lorem 3"]
    i = b["toc"].index("Bölüm 2: Lorem 2")
    ch = c.get(f"/api/read/{path.name}/{i}").get_json()
    assert ch["title"] == "Bölüm 2: Lorem 2" and len(ch["paragraphs"]) == 7 and ch["paragraphs"][-1] == "***"
    assert c.get(f"/api/read/{path.name}/99").status_code == 404

    assert c.post(f"/api/read/{path.name}/progress", json={"ch": i, "frac": 0.5, "total": len(b["toc"])}).status_code == 200
    assert c.get(f"/api/read/{path.name}").get_json()["progress"]["ch"] == i
    book = [x for x in c.get("/api/books").get_json() if x["name"] == path.name][0]
    assert book["read"] == round(100 * (i + 0.5) / len(b["toc"]))

    # klasör dışı ya da EPUB olmayan dosya açılmaz
    (out / "not.txt").write_text("x")
    assert c.get("/api/read/not.txt").status_code == 404
    assert c.get("/api/read/..%2Fayarlar.json").status_code == 404


def test_phone_on_wifi_can_read_but_not_write_progress(tmp_path: Path, monkeypatch):
    from novel_epub import web

    out = tmp_path / "cikti"
    out.mkdir()
    path = _book(out)
    monkeypatch.setattr(web, "OUTPUT", out)
    monkeypatch.setattr(web, "BASE", tmp_path)
    monkeypatch.setitem(web.SERVER, "lan", True)
    lan = dict(base_url="http://192.168.1.10:5000", environ_base={"REMOTE_ADDR": "192.168.1.20"})
    c = web.app.test_client()
    assert c.get(f"/api/read/{path.name}", **lan).status_code == 200
    assert c.get(f"/api/read/{path.name}/1", **lan).status_code == 200
    assert c.post(f"/api/read/{path.name}/progress", json={"ch": 1, "frac": 0}, **lan).status_code == 403
