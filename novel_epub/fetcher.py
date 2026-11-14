"""Tarayıcı taklidiyle (curl_cffi) sayfa çeker; Cloudflare'in basit kontrolünü geçer."""
from __future__ import annotations

import random
import threading
import time

from bs4 import BeautifulSoup
from curl_cffi import requests


class BlockedError(RuntimeError):
    """Site bot koruması (Cloudflare vb.) ile isteği engelledi."""


class FetchError(RuntimeError):
    pass


def _looks_blocked(resp) -> bool:
    if resp.headers.get("cf-mitigated") == "challenge":
        return True
    head = resp.text[:3000].lower()
    return "<title>just a moment" in head or "cf-browser-verification" in head


class Fetcher:
    def __init__(self, delay: float = 0.7, retries: int = 4, timeout: int = 30, impersonate: str = "chrome"):
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self.session = requests.Session(impersonate=impersonate)
        self._lock = threading.Lock()
        self._last = 0.0

    def _wait_turn(self) -> None:
        # Paralel işçiler olsa da istekler arasında en az `delay` saniye bırak (siteyi yormamak için).
        with self._lock:
            now = time.monotonic()
            gap = self.delay + random.uniform(0, self.delay * 0.3) - (now - self._last)
            if gap > 0:
                time.sleep(gap)
            self._last = time.monotonic()

    def get(self, url: str, headers: dict | None = None, referer: str | None = None):
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
                time.sleep(2 ** attempt)
                continue
            if _looks_blocked(resp):
                last_err = BlockedError(f"Bot koruması: {url}")
                time.sleep(3 * (attempt + 1))
                continue
            if resp.status_code in (429, 500, 502, 503, 504):
                last_err = FetchError(f"HTTP {resp.status_code}: {url}")
                retry_after = resp.headers.get("Retry-After", "")
                time.sleep(float(retry_after) if retry_after.isdigit() else 2 ** (attempt + 1))
                continue
            if resp.status_code >= 400:
                raise FetchError(f"HTTP {resp.status_code}: {url}")
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
