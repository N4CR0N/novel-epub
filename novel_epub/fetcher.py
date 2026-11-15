"""Sayfa çeker: masaüstünde tarayıcı taklidiyle (curl_cffi; Cloudflare'in basit kontrolünü geçer), Android'de
sistemin bağlantısıyla (net.py)."""
from __future__ import annotations

import ipaddress
import random
import socket
import threading
import time
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from . import net


class BlockedError(RuntimeError):
    """Site bot koruması (Cloudflare vb.) ile isteği engelledi."""


class FetchError(RuntimeError):
    pass


MAX_RETRY_AFTER = 120  # sitenin "şu kadar sonra dene" isteğine en çok bu kadar uyulur


_FAKE_IP = ipaddress.ip_network("198.18.0.0/15")


def _private_host(host: str) -> bool:
    """Bilgisayarın kendisi ya da yerel ağ adresi mi (site sayfasındaki bir bağlantı oraya yönlendirmesin)."""
    host = (host or "").strip("[]").lower()
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return True
    try:
        addrs = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            addrs = {ipaddress.ip_address(i[4][0].split("%")[0]) for i in socket.getaddrinfo(host, None)}
        except (OSError, ValueError):
            return False  # çözülemiyorsa istek zaten başarısız olur
    # 198.18.0.0/15: VPN/proxy araçlarının "fake-ip" kipi her alan adına buradan adres verir; site sayılır.
    addrs = {a for a in addrs if a not in _FAKE_IP}
    return any(a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast
               or a.is_unspecified for a in addrs)


def check_url(url: str) -> None:
    """Yalnız internetteki http/https adresleri: file://, yerel ağ ve bilgisayarın kendi adresleri reddedilir."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise FetchError(f"Yalnız http/https adresleri açılır: {url[:80]}")
    if _private_host(parts.hostname or ""):
        raise FetchError(f"Yerel ağ adresi açılmaz: {parts.hostname}")


def _looks_blocked(resp) -> bool:
    if resp.headers.get("cf-mitigated") == "challenge":
        return True
    head = resp.text[:3000].lower()
    return "<title>just a moment" in head or "cf-browser-verification" in head


class Fetcher:
    def __init__(self, delay: float = 0.7, retries: int = 4, timeout: int = 30, impersonate: str = "chrome",
                 stop: threading.Event | None = None):
        self.delay = delay
        self.stop = stop or threading.Event()  # Durdur'a basılınca beklemeler hemen biter
        self._hosts: dict[str, None] = {}
        self.retries = retries
        self.timeout = timeout
        self.session = net.Session(impersonate=impersonate)
        self._lock = threading.Lock()
        self._last = 0.0

    def _wait_turn(self) -> None:
        # Paralel işçiler olsa da istekler arasında en az `delay` saniye bırak (siteyi yormamak için).
        with self._lock:
            now = time.monotonic()
            gap = self.delay + random.uniform(0, self.delay * 0.3) - (now - self._last)
            if gap > 0:
                self._sleep(gap)
            self._last = time.monotonic()

    def _sleep(self, seconds: float) -> None:
        if self.stop.wait(seconds):
            raise FetchError("Durduruldu")

    def _check(self, url: str) -> None:
        host = urlsplit(url).hostname or ""
        if host not in self._hosts:
            check_url(url)
            self._hosts[host] = None
        elif urlsplit(url).scheme not in ("http", "https"):
            check_url(url)

    def get(self, url: str, headers: dict | None = None, referer: str | None = None):
        self._check(url)
        last_err: Exception | None = None
        for attempt in range(self.retries):
            self._wait_turn()
            hdrs = dict(headers or {})
            if referer:
                hdrs["Referer"] = referer
            try:
                resp = self.session.get(url, headers=hdrs, timeout=self.timeout)
            except Exception as e:  # ağ hatası
                last_err = e
                self._sleep(2 ** attempt)
                continue
            if _looks_blocked(resp):
                last_err = BlockedError(f"Bot koruması: {url}")
                self._sleep(3 * (attempt + 1))
                continue
            if resp.status_code in (429, 500, 502, 503, 504):
                last_err = FetchError(f"HTTP {resp.status_code}: {url}")
                retry_after = resp.headers.get("Retry-After", "")
                wait = float(retry_after) if retry_after.isdigit() else 2 ** (attempt + 1)
                self._sleep(min(wait, MAX_RETRY_AFTER))
                continue
            if resp.status_code >= 400:
                raise FetchError(f"HTTP {resp.status_code}: {url}")
            final = str(getattr(resp, "url", "") or "")
            if final and final != url:  # yönlendirme yerel ağa gittiyse yanıtı kullanma
                self._check(final)
            return resp
        if isinstance(last_err, BlockedError):
            raise last_err
        raise FetchError(f"{self.retries} denemede alınamadı: {url} ({last_err})")

    def soup(self, url: str, **kw) -> BeautifulSoup:
        return BeautifulSoup(self.get(url, **kw).text, "html.parser")

    def json(self, url: str, **kw):
        return self.get(url, **kw).json()

    def content(self, url: str, **kw) -> bytes:
        return self.get(url, **kw).content
