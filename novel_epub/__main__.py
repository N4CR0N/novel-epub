"""Kullanım:
  python -m novel_epub                      # web arayüzünü başlatır
  python -m novel_epub <link> [--bas 1 --son 50] [--cevir] [--bicim epub|docx|html|txt|md]
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from .pipeline import Job, Options


def main() -> None:
    ap = argparse.ArgumentParser(prog="novel_epub", description="Web novel linkinden tek kitap: EPUB ya da DOCX/HTML/TXT/MD (isteğe bağlı çeviri)")
    ap.add_argument("url", nargs="?", help="Novel ana sayfası veya bölüm linki (boşsa web arayüzü açılır)")
    ap.add_argument("--bas", type=int, help="İlk bölüm sırası (1'den başlar)")
    ap.add_argument("--son", type=int, help="Son bölüm sırası (dahil)")
    ap.add_argument("--cevir", action="store_true", help="Yapay zekâ ile çevir")
    ap.add_argument("--dil", default="tr", help="Hedef dil kodu (tr, en, de…)")
    ap.add_argument("--model", default=os.environ.get("NOVEL_MODELS", os.environ.get("GEMINI_MODEL", "")),
                    help="Modeller en iyiden kötüye, virgülle; LiteLLM adı (gemini/…, openai/…, anthropic/…). "
                         "Önek yoksa Gemini. Kota dolunca sıradakine geçer, saatte bir en iyiler yeniden denenir.")
    ap.add_argument("--bicim", choices=["epub", "docx", "html", "txt", "md"], default=None,
                    help="Çıktı biçimi (varsayılan: ayarlardaki, o da yoksa epub)")
    ap.add_argument("--bekleme", type=float, default=0.7, help="İstekler arası saniye")
    ap.add_argument("--isci", type=int, default=3, help="Paralel indirme sayısı")
    ap.add_argument("--toplu", type=int, default=0, help="Tek Gemini isteğinde en fazla kaç bölüm (0 = otomatik)")
    ap.add_argument("--host", default=None,
                    help="127.0.0.1: yalnız bu PC (varsayılan: aynı Wi‑Fi'deki cihazlar hazır kitapları indirebilir)")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--iki-gecis", action="store_true",
                    help="Redaksiyonu çeviriden sonra ayrı istekte yap (daha yavaş; varsayılan tek geçiş)")
    ap.add_argument("--denetle", action="store_true",
                    help="Önceden çevrilmiş bölümleri de denetle ve düzelt (İngilizce kalan kelime, sözlük, eski kelime, eksik çeviri)")
    a = ap.parse_args()

    if not a.url:
        from .web import serve

        serve(a.host, a.port)
        return

    from .providers import ENV_KEYS

    keys = {pid: os.environ[env] for pid, env in ENV_KEYS.items() if os.environ.get(env)}
    model = a.model
    if a.cevir and (not keys or not model):
        from .web import load_settings

        s = load_settings()
        keys = keys or s.get("keys", {})
        model = model or ", ".join(s.get("models") or [])
    if a.bicim is None:
        from .web import load_settings

        a.bicim = load_settings().get("output_format", "epub")
    opts = Options(url=a.url, start=a.bas, end=a.son, translate=a.cevir, keys=keys, model=model, lang=a.dil,
                   delay=a.bekleme, workers=a.isci, batch=a.toplu, library=Path("kutuphane"), output=Path("cikti"),
                   fmt=a.bicim, audit=a.denetle, one_pass=not a.iki_gecis)
    job = Job(opts, on_log=print)
    out = job.run()
    raise SystemExit(0 if out else 1)


if __name__ == "__main__":
    main()
