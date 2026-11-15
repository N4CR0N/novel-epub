"""Masaüstü uygulaması: arayüz kendi penceresinde açılır (tarayıcı ya da konsol yok).

Pencere Windows'un WebView2 motorunu kullanır (Windows 10/11'de hazır gelir). Arka planda yerel
sunucu çalışır; aynı Wi‑Fi'deki telefon da arayüzü açıp EPUB indirebilir.
"""
from __future__ import annotations

import json
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


def _window_backend_ok():
    """Pencerenin Windows tarafını (WinForms + WebView2 DLL'leri) pencere açmadan yükle.

    pywebview açılışta ARM64/x64/x86 WebView2Loader klasörlerinin hepsini arar; biri pakette yoksa uygulama hiç açılmaz.
    """
    if sys.platform != "win32":
        return None
    import webview.platforms.winforms  # noqa: F401  (edgechromium + DLL yollarını da yükler)

    return True


def self_test(home: Path) -> int:
    """Paketlenmiş exe'nin parçalarını pencere açmadan sınar (derleme hattı kullanır): --oz-test"""
    import json
    import urllib.request

    report: dict = {}
    try:
        import webview  # noqa: F401  (pencere kütüphanesi paketlenmiş mi)
        from curl_cffi import requests as _cc  # noqa: F401
        from . import llm

        class _R:  # ağsız sahte yanıt: istek kurma + yanıt çözme yolunun tamamı
            status_code = 200
            text = ""

            @staticmethod
            def json():
                return {"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}, "finishReason": "STOP"}]}

        r = llm.completion("gemini/gemini-2.5-flash", [{"role": "user", "content": "x"}], api_key="test",
                           response_format={"type": "json_object"}, post=lambda *a: _R())
        report["llm"] = r.choices[0].message.content == '{"ok": true}' and all(
            llm.build_request(m, [{"role": "user", "content": "x"}])[0].startswith("https://")
            for m in ("openai/gpt-5", "anthropic/claude-sonnet-4-5", "deepseek/deepseek-chat"))

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
        report["pencere"] = _window_backend_ok()
        report["ok"] = report["arayuz"] and report["info"] and report["llm"] and report["pencere"] is not False
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
    # Pencere: ilk açılışta ekranı kaplar (her çözünürlük/ölçekte düzgün); sonra son boyut ve konum hatırlanır.
    state_path = home / "pencere.json"
    try:
        state = json.loads(state_path.read_text("utf-8"))
    except Exception:
        state = {}
    maximized = state.get("max", True)
    window = webview.create_window(APP_NAME, f"http://127.0.0.1:{port}/", width=int(state.get("w", 1200)),
                                   height=int(state.get("h", 820)), x=state.get("x"), y=state.get("y"),
                                   maximized=maximized, min_size=(420, 560), text_select=True)

    def _set_max(flag: bool):
        state["max"] = flag

    def _remember():
        try:
            if not state.get("max"):
                state.update(w=window.width, h=window.height, x=window.x, y=window.y)
            state_path.write_text(json.dumps(state), encoding="utf-8")
        except Exception:
            pass

    try:
        window.events.maximized += lambda: _set_max(True)
        window.events.restored += lambda: _set_max(False)
    except Exception:
        pass
    state["max"] = maximized

    def on_closing():
        if web.running_jobs() and not window.create_confirmation_dialog(
                APP_NAME, "Çeviri hâlâ sürüyor. Kapatırsan durur; tekrar açıp aynı linkle başlatınca "
                          "kaldığı yerden devam eder. Kapatılsın mı?"):
            return False
        _remember()
        return True

    window.events.closing += on_closing
    webview.start()
    os._exit(0)  # arka plandaki sunucu ve iş parçacıkları da kapansın


if __name__ == "__main__":
    main()
