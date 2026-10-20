"""Kullanım:
  python -m novel_epub                      # web arayüzünü başlatır
  python -m novel_epub <link> [--bas 1 --son 50] [--cevir]
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from .pipeline import Job, Options


def main() -> None:
    ap = argparse.ArgumentParser(prog="novel_epub", description="Web novel linkinden tek EPUB (isteğe bağlı Türkçe çeviri)")
    ap.add_argument("url", nargs="?", help="Novel ana sayfası veya bölüm linki (boşsa web arayüzü açılır)")
    ap.add_argument("--bas", type=int, help="İlk bölüm sırası (1'den başlar)")
    ap.add_argument("--son", type=int, help="Son bölüm sırası (dahil)")
    ap.add_argument("--cevir", action="store_true", help="Gemini ile Türkçeye çevir")
    ap.add_argument("--model", default=os.environ.get("GEMINI_MODEL", ""), help="Gemini model(ler)i, virgülle (kota dolunca sıradakine geçer)")
    ap.add_argument("--bekleme", type=float, default=0.7, help="İstekler arası saniye")
    ap.add_argument("--isci", type=int, default=3, help="Paralel indirme sayısı")
    ap.add_argument("--toplu", type=int, default=3, help="Tek Gemini isteğinde en fazla kaç bölüm")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=5000)
    a = ap.parse_args()

    if not a.url:
        from .web import serve

        serve(a.host, a.port)
        return

    key = os.environ.get("GEMINI_API_KEY", "")
    if a.cevir and not key:
        from .web import load_settings

        key = load_settings().get("api_key", "")
    opts = Options(url=a.url, start=a.bas, end=a.son, translate=a.cevir, api_key=key, model=a.model,
                   delay=a.bekleme, workers=a.isci, batch=a.toplu, library=Path("kutuphane"), output=Path("cikti"))
    job = Job(opts, on_log=print)
    out = job.run()
    raise SystemExit(0 if out else 1)


if __name__ == "__main__":
    main()
