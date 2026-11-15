"""Google Drive: giriş (PKCE), yükleme/güncelleme, listeleme, indirme — sahte Google sunucusuyla (ağsız)."""
from __future__ import annotations

import base64
import json
import re
import urllib.parse
from pathlib import Path

import pytest


class Resp:
    def __init__(self, code=200, body=None, headers=None, raw=None):
        self.status_code = code
        self.content = raw if raw is not None else json.dumps(body or {}).encode()
        self.headers = headers or {}


class FakeGoogle:
    """Google'ın token ve Drive uçlarını taklit eder; dosyaları bellekte tutar."""

    def __init__(self):
        self.files: dict[str, dict] = {}
        self.calls: list[tuple[str, str]] = []
        self.sessions: dict[str, dict] = {}
        self.n = 0

    def __call__(self, method, url, headers=None, data=None, timeout=60):
        self.calls.append((method, url.split("?")[0]))
        headers = headers or {}
        u = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        if url.startswith("https://oauth2.googleapis.com/token"):
            form = dict(urllib.parse.parse_qsl(data.decode()))
            if form["grant_type"] == "authorization_code":
                assert form["code"] == "KOD" and len(form["code_verifier"]) > 40
                idt = "x." + base64.urlsafe_b64encode(json.dumps({"email": "okur@example.com"}).encode()).decode().rstrip("=") + ".y"
                return Resp(body={"access_token": "A1", "refresh_token": "R1", "expires_in": 3600, "id_token": idt,
                                  "scope": "https://www.googleapis.com/auth/drive.file openid email"})
            return Resp(body={"access_token": "A2", "expires_in": 3600})
        if url.startswith("https://oauth2.googleapis.com/revoke"):
            return Resp()
        assert headers.get("Authorization", "").startswith("Bearer ") or u.netloc == "upload.session"
        path = u.path
        if u.netloc == "upload.session":  # yükleme oturumuna PUT
            sess = self.sessions[path]
            sess["data"] += data
            total = int(headers["Content-Range"].rsplit("/", 1)[1]) if "Content-Range" in headers else len(data)
            if len(sess["data"]) < total:
                return Resp(308)
            fid = sess.get("id") or f"f{len(self.files) + 1}"
            self.files[fid] = {"id": fid, "name": sess["name"], "parents": sess["parents"], "data": sess["data"],
                               "mime": "x"}
            return Resp(200, {"id": fid})
        if path.startswith("/upload/drive/v3/files"):
            self.n += 1
            meta = json.loads(data or b"{}")
            fid = path.rsplit("/", 1)[-1] if path.count("/") > 4 else None
            if fid:
                assert headers.get("X-HTTP-Method-Override") == "PATCH"
                meta = {**self.files[fid], **meta}
            sp = f"/s{self.n}"
            self.sessions[sp] = {"name": meta["name"], "parents": meta.get("parents", []), "data": b"", "id": fid}
            return Resp(200, {}, {"Location": f"https://upload.session{sp}"})
        if path == "/drive/v3/files" and method == "GET":
            qs = q.get("q", "")
            res = [f for f in self.files.values() if
                   ("mimeType='application/vnd.google-apps.folder'" in qs and f.get("mime") == "folder" and f["name"] in qs)
                   or ("in parents" in qs and re.search(r"'(\w+)' in parents", qs).group(1) in f["parents"]
                       and ("name=" not in qs or f"name='{f['name']}'" in qs))]
            return Resp(body={"files": [{"id": f["id"], "name": f["name"], "size": str(len(f.get("data", b"")))} for f in res]})
        if path == "/drive/v3/files" and method == "POST":
            meta = json.loads(data)
            fid = f"d{len(self.files) + 1}"
            self.files[fid] = {"id": fid, "name": meta["name"], "mime": "folder", "parents": []}
            return Resp(body={"id": fid})
        if path.startswith("/drive/v3/files/"):
            fid = path.rsplit("/", 1)[-1]
            if fid not in self.files:
                return Resp(404, {"error": {"message": "not found"}})
            if q.get("alt") == "media":
                return Resp(raw=self.files[fid]["data"])
            return Resp(body={"id": fid, "trashed": False})
        raise AssertionError(url)


@pytest.fixture
def drive(monkeypatch):
    from novel_epub import drive as dm

    monkeypatch.setenv("NOVEL_EPUB_GOOGLE_ID", "uydurma.apps.googleusercontent.com")
    monkeypatch.setenv("NOVEL_EPUB_GOOGLE_SECRET", "uydurma-gizli")
    state: dict = {}
    g = FakeGoogle()
    d = dm.Drive(lambda: dict(state), lambda s: (state.clear(), state.update(s)), http=g)
    return d, g, state


def test_login_upload_update_list_download(drive, tmp_path: Path, monkeypatch):
    from novel_epub import drive as dm

    d, g, state = drive
    url = d.auth_url("http://127.0.0.1:5000/oauth2cb")
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    assert q["scope"].split()[0].endswith("/drive.file") and q["code_challenge_method"] == "S256"
    with pytest.raises(dm.DriveError):
        d.finish("yanlis-state", "KOD")
    assert d.finish(q["state"], "KOD") == "okur@example.com"
    assert state["refresh"] == "R1" and d.signed_in()

    book = tmp_path / "kitap.epub"
    book.write_bytes(b"PK" + b"x" * 1000)
    fid = d.upload(book, mime="application/epub+zip")
    assert g.files[fid]["data"] == book.read_bytes() and g.files[fid]["parents"] == [state["folder"]]
    book.write_bytes(b"PK" + b"y" * 50)
    assert d.upload(book) == fid  # aynı ad: üzerine yazılır, kopya oluşmaz
    assert len([f for f in g.files.values() if f["name"] == "kitap.epub"]) == 1
    assert [f["name"] for f in d.files()] == ["kitap.epub"]
    out = d.download(fid, tmp_path / "geri.epub")
    assert out.read_bytes() == book.read_bytes()

    # büyük dosya parça parça
    monkeypatch.setattr(dm, "CHUNK", 256 * 1024)
    big = tmp_path / "yedek.zip"
    big.write_bytes(bytes(range(256)) * 5000)  # 1.28 MB > 4 parça
    fid2 = d.upload(big)
    assert g.files[fid2]["data"] == big.read_bytes()

    d.logout()
    assert not d.signed_in() and ("POST", "https://oauth2.googleapis.com/revoke") in g.calls


def test_web_drive_endpoints_and_secret_never_reaches_ui(drive, tmp_path: Path, monkeypatch):
    from novel_epub import web
    from novel_epub.drive import Drive

    d, g, _ = drive
    monkeypatch.setattr(web, "SETTINGS_PATH", tmp_path / "ayarlar.json")
    monkeypatch.setattr(web, "_keyring", lambda: None)
    monkeypatch.setattr(web, "OUTPUT", tmp_path / "cikti")
    (tmp_path / "cikti").mkdir()
    (tmp_path / "cikti" / "a.epub").write_bytes(b"PK..")
    monkeypatch.setitem(web._DRIVE, "d", Drive(web._drive_load, web._drive_save, http=g))
    monkeypatch.setattr(web, "ANDROID", True)  # tarayıcı açma yerine adres döner
    c = web.app.test_client()
    assert c.get("/api/drive").get_json()["available"] is True
    url = c.post("/api/drive/login", json={}).get_json()["url"]
    state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))["state"]
    # Google'dan dönüş: tarayıcıdan, erişim anahtarı olmadan gelir
    r = c.get(f"/oauth2cb?state={state}&code=KOD", headers={"X-Token": ""})
    assert r.status_code == 200 and "okur@example.com" in r.get_data(as_text=True)
    st = c.get("/api/drive").get_json()
    assert st["signed_in"] and st["email"] == "okur@example.com"
    assert "R1" not in json.dumps(c.get("/api/settings").get_json())  # yenileme anahtarı arayüze gitmez
    assert c.post("/api/drive/upload", json={"name": "a.epub"}).get_json()["ok"]
    assert c.post("/api/drive/upload", json={"name": "../ayarlar.json"}).status_code == 404
    files = c.get("/api/drive/files").get_json()
    assert files[0]["name"] == "a.epub" and files[0]["here"]
    assert c.post("/api/drive/download", json={"id": files[0]["id"], "name": "../x.epub"}).get_json()["name"] == "x.epub"
    # ağdaki telefon Drive uçlarına dokunamaz
    lan = dict(base_url="http://192.168.1.10:5000", environ_base={"REMOTE_ADDR": "192.168.1.20"})
    monkeypatch.setitem(web.SERVER, "lan", True)
    assert c.get("/api/drive", **lan).status_code == 403
    assert c.get(f"/oauth2cb?state=x&code=y", **lan).status_code == 403
