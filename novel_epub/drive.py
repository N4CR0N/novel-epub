"""Google Drive: Google ile giriş ve uygulamanın kendi klasörüne yükleme/indirme.

Giriş, cihazın kendi tarayıcısında yapılır (Google gömülü pencerede girişe izin vermez): PKCE ile yetki kodu,
dönüş adresi uygulamanın yerel sunucusu (http://127.0.0.1:<port>/oauth2cb). Kapsam yalnız `drive.file`: uygulama
Drive'da yalnız kendi oluşturduğu dosyaları görebilir; kullanıcının diğer dosyalarına erişemez.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Callable

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/drive/v3"
UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"
SCOPES = "https://www.googleapis.com/auth/drive.file openid email"
FOLDER_NAME = "WebNovel Downloader & Translator"
FOLDER_MIME = "application/vnd.google-apps.folder"
CHUNK = 8 * 1024 * 1024  # büyük dosyalar 8 MB'lık parçalarla (256 KB'ın katı olmalı)


class DriveError(RuntimeError):
    pass


def client() -> tuple[str, str] | None:
    """Uygulamanın Google istemci kimliği: derlemede `_google.py`'ye yazılır (depoda yok), geliştirmede ortamdan."""
    cid, sec = os.environ.get("NOVEL_EPUB_GOOGLE_ID", ""), os.environ.get("NOVEL_EPUB_GOOGLE_SECRET", "")
    if not cid:
        try:
            from ._google import CLIENT_ID as cid, CLIENT_SECRET as sec  # type: ignore
        except ImportError:
            return None
    return (cid, sec) if cid else None


Http = Callable[..., object]  # (method, url, headers=None, data=None, timeout=60) -> yanıt (status_code, content, headers)


def _http(method: str, url: str, headers: dict | None = None, data: bytes | None = None, timeout: float = 120):
    from . import net

    return net.request(method, url, headers=headers, data=data, timeout=timeout)


def _json(resp) -> dict:
    try:
        return json.loads(resp.content or b"{}")
    except ValueError:
        return {}


def _err(resp) -> str:
    d = _json(resp)
    e = d.get("error")
    msg = (e.get("message") if isinstance(e, dict) else d.get("error_description") or e) or ""
    return f"HTTP {resp.status_code}" + (f": {msg}" if msg else "")


def _q(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


class Drive:
    """Oturum durumu `load()`/`save(dict)` ile saklanır: {"refresh", "email", "folder"} (yenileme anahtarı web.py'de
    kasaya gider)."""

    def __init__(self, load: Callable[[], dict], save: Callable[[dict], None], http: Http | None = None):
        self._load, self._save = load, save
        self.http = http or _http
        self._pending: dict[str, tuple[str, str, float]] = {}  # state → (doğrulayıcı, dönüş adresi, zaman)
        self._access: tuple[str, float] | None = None
        self._lock = threading.Lock()

    # --- giriş ---
    def signed_in(self) -> bool:
        return bool(self._load().get("refresh"))

    def email(self) -> str:
        return self._load().get("email", "")

    def auth_url(self, redirect_uri: str) -> str:
        cl = client()
        if not cl:
            raise DriveError("Bu sürümde Google girişi yok")
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        now = time.time()
        self._pending = {k: v for k, v in self._pending.items() if now - v[2] < 900}
        self._pending[state] = (verifier, redirect_uri, now)
        return AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": cl[0], "redirect_uri": redirect_uri, "response_type": "code", "scope": SCOPES,
            "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
            "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"})

    def finish(self, state: str, code: str) -> str:
        """Tarayıcıdan dönen kodu anahtara çevirir; giriş yapan hesabın e-postasını döndürür."""
        pend = self._pending.pop(state, None)
        if not pend or time.time() - pend[2] > 900:
            raise DriveError("Giriş isteği bulunamadı ya da süresi doldu; yeniden dene")
        cid, sec = client() or ("", "")
        resp = self.http("POST", TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, urllib.parse.urlencode({
            "code": code, "client_id": cid, "client_secret": sec, "redirect_uri": pend[1],
            "grant_type": "authorization_code", "code_verifier": pend[0]}).encode())
        d = _json(resp)
        if resp.status_code != 200 or not d.get("refresh_token"):
            raise DriveError("Google girişi tamamlanamadı: " + _err(resp))
        if "drive.file" not in d.get("scope", "drive.file"):
            raise DriveError("Drive izni verilmedi; girişte Drive kutusunu işaretle")
        email = ""
        try:  # kimlik belirteci doğrudan Google'dan TLS ile geldi; yalnız e-postayı okuyoruz
            payload = d.get("id_token", "").split(".")[1]
            email = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("email", "")
        except (IndexError, ValueError):
            pass
        self._access = (d["access_token"], time.time() + int(d.get("expires_in", 3600)) - 60)
        self._save({"refresh": d["refresh_token"], "email": email, "folder": ""})
        return email

    def logout(self) -> None:
        st = self._load()
        if st.get("refresh"):
            try:
                self.http("POST", REVOKE_URL, {"Content-Type": "application/x-www-form-urlencoded"},
                          urllib.parse.urlencode({"token": st["refresh"]}).encode())
            except Exception:
                pass
        self._access = None
        self._save({})

    def _token(self) -> str:
        with self._lock:
            if self._access and self._access[1] > time.time():
                return self._access[0]
            st = self._load()
            if not st.get("refresh"):
                raise DriveError("Google ile giriş yapılmamış")
            cid, sec = client() or ("", "")
            resp = self.http("POST", TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, urllib.parse.urlencode({
                "client_id": cid, "client_secret": sec, "refresh_token": st["refresh"], "grant_type": "refresh_token"}).encode())
            d = _json(resp)
            if resp.status_code != 200:
                if d.get("error") in ("invalid_grant", "unauthorized_client"):
                    self._save({})
                    raise DriveError("Google oturumu sona erdi; yeniden giriş yap")
                raise DriveError("Google'a bağlanılamadı: " + _err(resp))
            self._access = (d["access_token"], time.time() + int(d.get("expires_in", 3600)) - 60)
            return self._access[0]

    def _call(self, method: str, url: str, body: dict | None = None, data: bytes | None = None,
              headers: dict | None = None, ok=(200,)):
        for attempt in range(2):
            h = {"Authorization": f"Bearer {self._token()}", **(headers or {})}
            payload = data
            if body is not None:
                h["Content-Type"] = "application/json; charset=UTF-8"
                payload = json.dumps(body).encode()
            resp = self.http(method, url, h, payload)
            if resp.status_code == 401 and attempt == 0:
                self._access = None
                continue
            if resp.status_code not in ok:
                raise DriveError("Drive: " + _err(resp))
            return resp
        raise DriveError("Drive: yetki reddedildi")

    # --- klasör ve dosyalar ---
    def folder(self) -> str:
        st = self._load()
        if st.get("folder"):
            r = self.http("GET", f"{API}/files/{st['folder']}?fields=id,trashed",
                          {"Authorization": f"Bearer {self._token()}"}, None)
            if r.status_code == 200 and not _json(r).get("trashed"):
                return st["folder"]
        q = f"name='{_q(FOLDER_NAME)}' and mimeType='{FOLDER_MIME}' and trashed=false"
        found = _json(self._call("GET", f"{API}/files?" + urllib.parse.urlencode({"q": q, "fields": "files(id)", "spaces": "drive"})))
        fid = (found.get("files") or [{}])[0].get("id")
        if not fid:
            fid = _json(self._call("POST", f"{API}/files?fields=id", {"name": FOLDER_NAME, "mimeType": FOLDER_MIME}))["id"]
        self._save({**self._load(), "folder": fid})
        return fid

    def files(self) -> list[dict]:
        q = f"'{self.folder()}' in parents and trashed=false"
        out, token = [], ""
        while True:
            params = {"q": q, "fields": "nextPageToken,files(id,name,size,modifiedTime)", "orderBy": "modifiedTime desc",
                      "pageSize": "200", **({"pageToken": token} if token else {})}
            d = _json(self._call("GET", f"{API}/files?" + urllib.parse.urlencode(params)))
            out += [{"id": f["id"], "name": f["name"], "size": int(f.get("size", 0)), "modified": f.get("modifiedTime", "")}
                    for f in d.get("files", [])]
            token = d.get("nextPageToken", "")
            if not token:
                return out

    def _find(self, name: str, folder: str) -> str | None:
        q = f"name='{_q(name)}' and '{folder}' in parents and trashed=false"
        d = _json(self._call("GET", f"{API}/files?" + urllib.parse.urlencode({"q": q, "fields": "files(id)"})))
        return (d.get("files") or [{}])[0].get("id")

    def upload(self, path: Path, name: str | None = None, mime: str = "application/octet-stream",
               progress: Callable[[int, int], None] | None = None) -> str:
        """Dosyayı uygulama klasörüne yükler; aynı adlı dosya varsa üzerine yazar (sürüm geçmişi Drive'da kalır)."""
        path = Path(path)
        name = name or path.name
        folder = self.folder()
        existing = self._find(name, folder)
        size = path.stat().st_size
        hdr = {"X-Upload-Content-Type": mime, "X-Upload-Content-Length": str(size)}
        if existing:  # güncelleme PATCH ister; Android'in bağlantısı PATCH bilmez → POST + yöntem üst bilgisi
            r = self._call("POST", f"{UPLOAD_API}/files/{existing}?uploadType=resumable&fields=id", body={},
                           headers={**hdr, "X-HTTP-Method-Override": "PATCH"})
        else:
            r = self._call("POST", f"{UPLOAD_API}/files?uploadType=resumable&fields=id",
                           body={"name": name, "parents": [folder]}, headers=hdr)
        session = r.headers.get("Location") or r.headers.get("location")
        if not session:
            raise DriveError("Drive yükleme oturumu açılamadı")
        sent = 0
        with open(path, "rb") as f:
            while True:
                chunk = f.read(CHUNK if size > 4 * CHUNK else size or 1)
                end = sent + len(chunk) - 1
                h = {"Content-Length": str(len(chunk))}
                if size:
                    h["Content-Range"] = f"bytes {sent}-{end}/{size}"
                resp = self.http("PUT", session, h, chunk)
                if resp.status_code in (200, 201):
                    if progress:
                        progress(size, size)
                    return _json(resp).get("id", existing or "")
                if resp.status_code != 308:
                    raise DriveError("Drive yüklemesi yarıda kaldı: " + _err(resp))
                sent = end + 1
                if progress:
                    progress(sent, size)

    def download(self, file_id: str, dest: Path) -> Path:
        resp = self._call("GET", f"{API}/files/{urllib.parse.quote(file_id)}?alt=media")
        tmp = Path(dest).with_suffix(Path(dest).suffix + ".part")
        tmp.write_bytes(resp.content)
        tmp.replace(dest)
        return Path(dest)
