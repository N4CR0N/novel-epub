"""Masaüstü uygulaması: arayüz kendi penceresinde açılır (tarayıcı ya da konsol yok).

Pencere Windows'un WebView2 motorunu kullanır (Windows 10/11'de hazır gelir). Arka planda yerel
sunucu çalışır; aynı Wi‑Fi'deki telefon da arayüzü açıp EPUB indirebilir.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
from pathlib import Path

APP_NAME = "WebNovel Downloader & Translator"
LEGACY_DIR = "Novel EPUB"  # eski sürümün Belgeler altındaki veri klasörü


def _documents_dir() -> Path:
    if sys.platform == "win32":
        try:  # OneDrive'a yönlendirilmiş "Belgeler" klasörünü de doğru bulur
            import ctypes
            from ctypes import wintypes

            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:  # CSIDL_PERSONAL
                return Path(buf.value)
        except Exception:
            pass
    return Path.home() / "Documents"


def data_home() -> Path:
    """Kitaplık, çıktılar ve ayarların klasörü.

    Uygulamanın yanında kutuphane/ ya da ayarlar.json varsa (taşınabilir kullanım, eski kurulum)
    orası; yoksa Belgeler altında: eski "Novel EPUB" klasörü varsa o (kitaplık ve ayarlar korunur),
    yoksa "WebNovel Downloader & Translator".
    """
    if os.environ.get("NOVEL_EPUB_HOME"):
        return Path(os.environ["NOVEL_EPUB_HOME"])
    here = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    if (here / "kutuphane").exists() or (here / "ayarlar.json").exists():
        return here
    docs = _documents_dir()
    return docs / LEGACY_DIR if (docs / LEGACY_DIR).exists() else docs / APP_NAME


def _free_port(preferred: int = 5000) -> int:
    for port in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind(("0.0.0.0", port))
                return s.getsockname()[1]
            except OSError:
                continue
    return preferred


def self_test(home: Path) -> int:
    """Paketlenmiş exe'nin parçalarını pencere açmadan sınar (derleme hattı kullanır): --oz-test"""
    import json
    import urllib.request

    report: dict = {}
    try:
        import webview  # noqa: F401  (pencere kütüphanesi paketlenmiş mi)
        from curl_cffi import requests as _cc  # noqa: F401
        from .translator import _litellm

        lt = _litellm()  # LiteLLM ve fiyat/model tablosu paketlenmiş mi: ağsız sahte yanıtla tam yol
        r = lt.completion(model="gemini/gemini-2.5-flash", messages=[{"role": "user", "content": "x"}],
                          mock_response='{"ok": true}')
        report["litellm"] = r.choices[0].message.content == '{"ok": true}' and lt.get_max_tokens("gemini/gemini-2.5-flash") > 0

        from . import web

        port = _free_port(5099)
        threading.Thread(target=lambda: web.app.run(host="127.0.0.1", port=port, use_reloader=False), daemon=True).start()
        for _ in range(50):
            try:
                html = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2).read().decode()
                break
            except Exception:
                import time

                time.sleep(0.2)
        report["arayuz"] = "WebNovel Downloader" in html
        report["info"] = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/info").read())["local"]
        kr = web._keyring()
        report["kasa"] = type(kr.get_keyring()).__name__ if kr else "yok"
        report["ok"] = report["arayuz"] and report["info"] and report["litellm"]
    except Exception as e:  # rapora yaz, çıkış kodu 1
        report["hata"] = repr(e)
        report["ok"] = False
    (home / "oz-test.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if report["ok"] else 1


def main() -> None:
    home = data_home()
    home.mkdir(parents=True, exist_ok=True)
    os.environ["NOVEL_EPUB_HOME"] = str(home)
    if sys.stdout is None or sys.stderr is None:  # pencere uygulamasında konsol yok: kayıt dosyaya
        log = open(home / "uygulama.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log

    if "--oz-test" in sys.argv:
        os._exit(self_test(home))

    import webview

    from . import web  # NOVEL_EPUB_HOME ayarlandıktan sonra içe aktarılmalı

    port = _free_port()
    web.LIBRARY.mkdir(exist_ok=True)
    web.OUTPUT.mkdir(exist_ok=True)
    web.APP_MODE["port"] = port
    threading.Thread(target=lambda: web.app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False),
                     daemon=True).start()

    webview.settings["ALLOW_DOWNLOADS"] = True
    window = webview.create_window(APP_NAME, f"http://127.0.0.1:{port}/", width=900, height=900,
                                   min_size=(420, 600), text_select=True)

    def on_closing():
        if web.running_jobs() and not window.create_confirmation_dialog(
                APP_NAME, "Çeviri hâlâ sürüyor. Kapatırsan durur; tekrar açıp aynı linkle başlatınca "
                          "kaldığı yerden devam eder. Kapatılsın mı?"):
            return False
        return True

    window.events.closing += on_closing
    webview.start()
    os._exit(0)  # arka plandaki sunucu ve iş parçacıkları da kapansın


if __name__ == "__main__":
    main()
