"""HTTP katmanı: hangi ortamda çalışıyorsak oranın en iyi istemcisi.

- Masaüstü (Windows/Linux): curl_cffi, Chrome taklidiyle (basit Cloudflare kontrolünü geçer). Yanıt nesnesi olduğu gibi döner.
- Android (Chaquopy): sistemin HttpURLConnection'ı (OkHttp + Conscrypt; telefondaki tarayıcıya yakın bir bağlantı).
- İkisi de yoksa: Python'un urllib'i (certifi varsa onun sertifikalarıyla).

Hepsi aynı küçük arayüzü verir: get/post → status_code, headers.get(), text, content, json().
"""
from __future__ import annotations

import json as _json
import re

# Telefondaki ve bilgisayardaki tarayıcılara benzer istek başlığı (urllib/Java'nın varsayılanı bazı sitelerde reddedilir)
USER_AGENT = ("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0.0.0 Mobile Safari/537.36")
_DEFAULT_HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


def _has_curl_cffi() -> bool:
    try:
        import curl_cffi  # noqa: F401
        return True
    except Exception:
        return False


def _has_java() -> bool:
    try:
        from java import jclass  # noqa: F401  (yalnız Chaquopy'de var)
        return True
    except Exception:
        return False


_BACKEND: str | None = None


def backend() -> str:
    """'curl_cffi' | 'android' | 'urllib' (bir kez seçilir; testte `set_backend` ile değiştirilebilir)."""
    global _BACKEND
    if _BACKEND is None:
        _BACKEND = "curl_cffi" if _has_curl_cffi() else "android" if _has_java() else "urllib"
    return _BACKEND


def set_backend(name: str | None) -> None:
    global _BACKEND
    _BACKEND = name


class Headers(dict):
    """Büyük/küçük harf duyarsız yanıt başlıkları."""

    def __init__(self, items=()):
        super().__init__()
        for k, v in items:
            if k:
                super().__setitem__(k.lower(), v)

    def get(self, key, default=None):
        return super().get(key.lower(), default)

    def __getitem__(self, key):
        return super().__getitem__(key.lower())

    def __contains__(self, key):
        return super().__contains__(str(key).lower())


class Response:
    def __init__(self, status_code: int, headers: Headers, content: bytes, url: str = ""):
        self.status_code = status_code
        self.headers = headers
        self.content = content
        self.url = url

    @property
    def text(self) -> str:
        m = re.search(r"charset=([\w-]+)", self.headers.get("content-type", "") or "", re.I)
        enc = m.group(1) if m else "utf-8"
        try:
            return self.content.decode(enc, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")

    def json(self):
        return _json.loads(self.text)


def _merge(headers: dict | None, browser: bool) -> dict:
    out = dict(_DEFAULT_HEADERS) if browser else {"User-Agent": USER_AGENT}
    for k, v in (headers or {}).items():
        for d in [x for x in out if x.lower() == k.lower()]:
            del out[d]
        out[k] = v
    return out


def _urllib_request(method: str, url: str, headers: dict | None, data: bytes | None, timeout: float,
                    browser: bool) -> Response:
    import ssl
    import urllib.error
    import urllib.request

    ctx = None
    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    req = urllib.request.Request(url, data=data, method=method, headers=_merge(headers, browser))
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return Response(r.status, Headers(r.headers.items()), r.read(), r.geturl())
    except urllib.error.HTTPError as e:  # 4xx/5xx de bir yanıttır (gövdesi hata ayrıntısını taşır)
        return Response(e.code, Headers(e.headers.items() if e.headers else ()), e.read() or b"", url)


def _android_request(method: str, url: str, headers: dict | None, data: bytes | None, timeout: float,
                     browser: bool) -> Response:
    from java import jarray, jbyte, jclass

    conn = jclass("java.net.URL")(url).openConnection()
    ms = int(timeout * 1000)
    conn.setConnectTimeout(min(ms, 30000))
    conn.setReadTimeout(ms)
    conn.setInstanceFollowRedirects(True)
    conn.setRequestMethod(method)
    for k, v in _merge(headers, browser).items():
        conn.setRequestProperty(k, str(v))
    try:
        if data is not None:
            conn.setDoOutput(True)
            out = conn.getOutputStream()
            out.write(jarray(jbyte)(data))
            out.close()
        code = conn.getResponseCode()
        stream = conn.getInputStream() if code < 400 else conn.getErrorStream()
        body = b""
        if stream is not None:
            buf = jclass("java.io.ByteArrayOutputStream")()
            chunk = jarray(jbyte)(65536)
            while True:
                n = stream.read(chunk)
                if n < 0:
                    break
                buf.write(chunk, 0, n)
            stream.close()
            body = bytes(buf.toByteArray())
        hdrs = []
        fields = conn.getHeaderFields()
        for key in fields.keySet().toArray():
            if key is not None:
                vals = fields.get(key)
                hdrs.append((str(key), ", ".join(str(v) for v in vals.toArray())))
        return Response(int(code), Headers(hdrs), body, str(conn.getURL().toString()))
    finally:
        conn.disconnect()


def _request(method: str, url: str, headers: dict | None, data: bytes | None, timeout: float,
             browser: bool = False) -> Response:
    if backend() == "android":
        return _android_request(method, url, headers, data, timeout, browser)
    return _urllib_request(method, url, headers, data, timeout, browser)


class Session:
    """Site indirmeleri için oturum (masaüstünde çerezleri ve bağlantıyı koruyan curl_cffi oturumu)."""

    def __init__(self, impersonate: str = "chrome"):
        self._s = None
        if backend() == "curl_cffi":
            from curl_cffi import requests

            self._s = requests.Session(impersonate=impersonate)

    def get(self, url: str, headers: dict | None = None, timeout: float = 30):
        if self._s is not None:
            return self._s.get(url, headers=headers, timeout=timeout)
        return _request("GET", url, headers, None, timeout, browser=True)

    def post(self, url: str, headers: dict | None = None, data: bytes | None = None, timeout: float = 30):
        if self._s is not None:
            return self._s.post(url, headers=headers, data=data, timeout=timeout)
        return _request("POST", url, headers, data, timeout, browser=True)


def get(url: str, headers: dict | None = None, timeout: float = 30):
    if backend() == "curl_cffi":
        from curl_cffi import requests

        return requests.get(url, headers=headers, timeout=timeout)
    return _request("GET", url, headers, None, timeout)


def post(url: str, headers: dict | None = None, data: bytes | None = None, timeout: float = 30):
    if backend() == "curl_cffi":
        from curl_cffi import requests

        return requests.post(url, headers=headers, data=data, timeout=timeout)
    return _request("POST", url, headers, data, timeout)


def request(method: str, url: str, headers: dict | None = None, data: bytes | None = None, timeout: float = 60):
    """Herhangi bir yöntemle düz istek (Google Drive gibi API'ler için: PUT, DELETE; PATCH yerine üst bilgiyle POST)."""
    if backend() == "curl_cffi":
        from curl_cffi import requests

        return requests.request(method, url, headers=headers, data=data, timeout=timeout)
    return _request(method, url, headers, data, timeout)
