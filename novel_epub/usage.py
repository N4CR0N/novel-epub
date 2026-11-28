"""Kotalı/ücretli sağlayıcılarda harcama kaydı ve sınırı.

Abonelikle gelen API'lerde (ör. Command Code GOAT: 5 saatlik, haftalık, aylık dolar sınırı) aboneliği başka işlere de
kullanan biri olabilir; çeviri kuyruğu onun payını yemesin diye her istek token sayısı ve tahmini maliyetle
`kullanim.jsonl`'a yazılır ve sağlayıcı için konan pencere sınırları (son 5 saat / 7 gün harcaması) aşılınca o
sağlayıcının modelleri kota dolmuş gibi zincirden çıkar.

Sınır biçimi: "commandcode:5h=3,7d=10" (birden çok sağlayıcı ";" ile). Ortam değişkeni NOVEL_EPUB_SPEND_LIMITS.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# model adı (sağlayıcı/model) deseni → 1M token başına dolar:
# (girdi yoğun-dışı, girdi yoğun, çıktı yoğun-dışı, çıktı yoğun, önbellekten girdi)
PRICES: list[tuple[str, tuple[float, float, float, float, float]]] = [
    # Command Code Pricing & Limits (2026-11): yoğun saatler hafta içi 01–04 ve 06–10 UTC.
    (r"^commandcode/deepseek/deepseek-v4(\.1)?-flash", (0.15, 0.30, 0.60, 1.20, 0.003)),
]
UNKNOWN_PRICE = (1.0, 1.0, 4.0, 4.0, 0.1)  # fiyatı bilinmeyen modelde sınır güvenli tarafta kalsın diye yüksek tahmin

_UNITS = {"h": 3600, "d": 86400, "m": 60}


def is_peak(ts: float) -> bool:
    t = datetime.fromtimestamp(ts, timezone.utc)
    return t.weekday() < 5 and (1 <= t.hour < 4 or 6 <= t.hour < 10)


def rates(model: str) -> tuple[float, float, float, float, float]:
    for pat, r in PRICES:
        if re.search(pat, model):
            return r
    return UNKNOWN_PRICE


def cost(model: str, prompt: int, cached: int, completion: int, ts: float | None = None) -> float:
    """Tahmini maliyet (dolar). `prompt` önbellekten gelenleri de içerir."""
    in_off, in_peak, out_off, out_peak, cache = rates(model)
    peak = is_peak(ts if ts is not None else time.time())
    fresh = max(0, prompt - cached)
    return (fresh * (in_peak if peak else in_off) + cached * cache + completion * (out_peak if peak else out_off)) / 1e6


def parse_limits(spec: str) -> dict[str, dict[int, float]]:
    """"commandcode:5h=3,7d=10" → {"commandcode": {18000: 3.0, 604800: 10.0}}."""
    out: dict[str, dict[int, float]] = {}
    for part in (spec or "").split(";"):
        if ":" not in part:
            continue
        pid, rest = part.split(":", 1)
        for item in rest.split(","):
            m = re.fullmatch(r"\s*(\d+)([hdm])\s*=\s*([\d.]+)\s*", item)
            if m:
                out.setdefault(pid.strip(), {})[int(m.group(1)) * _UNITS[m.group(2)]] = float(m.group(3))
    return out


def _window_name(seconds: int) -> str:
    return f"{seconds // 86400} gün" if seconds % 86400 == 0 else f"{seconds // 3600} saat"


class Ledger:
    """Harcama defteri (JSONL; her satır bir istek). Aynı dosyayı birden çok süreç ekleyerek yazabilir."""

    def __init__(self, path: str | Path, limits: dict[str, dict[int, float]] | None = None):
        self.path = Path(path)
        self.limits = limits or {}
        self._lock = threading.Lock()

    def tracked(self, model: str) -> bool:
        return model.split("/", 1)[0] in self.limits

    def record(self, model: str, prompt: int, cached: int, completion: int, ts: float | None = None,
               note: str = "") -> float:
        ts = time.time() if ts is None else ts
        usd = cost(model, prompt, cached, completion, ts)
        row = {"t": round(ts, 1), "model": model, "in": prompt, "cached": cached, "out": completion,
               "usd": round(usd, 6)}
        if note:
            row["note"] = note
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        return usd

    def rows(self, since: float = 0.0) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text("utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("t", 0) >= since:
                out.append(r)
        return out

    def spent(self, provider: str, seconds: int, now: float | None = None) -> float:
        now = time.time() if now is None else now
        return sum(r.get("usd", 0.0) for r in self.rows(now - seconds) if r.get("model", "").split("/", 1)[0] == provider)

    def over(self, model: str, now: float | None = None) -> str:
        """Sınır aşıldıysa açıklama, yoksa boş."""
        pid = model.split("/", 1)[0]
        for seconds, cap in sorted(self.limits.get(pid, {}).items()):
            used = self.spent(pid, seconds, now)
            if used >= cap:
                return f"{pid} harcama sınırı: son {_window_name(seconds)} ${used:.2f} / ${cap:.2f}"
        return ""

    def summary(self, since: float = 0.0) -> dict[str, dict]:
        """Model başına istek, token ve dolar toplamı."""
        out: dict[str, dict] = {}
        for r in self.rows(since):
            s = out.setdefault(r.get("model", "?"), {"requests": 0, "in": 0, "cached": 0, "out": 0, "usd": 0.0})
            s["requests"] += 1
            for k in ("in", "cached", "out"):
                s[k] += r.get(k, 0)
            s["usd"] += r.get("usd", 0.0)
        return out


def from_env(path: str | Path) -> Ledger | None:
    spec = os.environ.get("NOVEL_EPUB_SPEND_LIMITS", "")
    return Ledger(path, parse_limits(spec)) if spec else None
