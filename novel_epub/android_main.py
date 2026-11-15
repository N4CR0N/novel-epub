"""Android uygulamasının Python girişi (Chaquopy). Kotlin tarafı ön plan hizmetinden `start()` çağırır.

Arayüz bilgisayardakiyle aynı Flask uygulamasıdır; yalnız 127.0.0.1'e bağlanır (telefon ağa açılmaz) ve
uygulamanın kendi WebView'i onu açar. Veriler uygulamanın özel klasöründe durur.
"""
from __future__ import annotations

import os
import socket
import threading

_started: dict = {}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(home: str) -> int:
    """Sunucuyu (bir kez) başlatır, portunu döndürür. `home`: uygulamanın veri klasörü."""
    if _started:
        return _started["port"]
    os.environ["NOVEL_EPUB_HOME"] = home
    os.environ["NOVEL_EPUB_ANDROID"] = "1"
    from werkzeug.serving import make_server

    from . import web

    for d in (web.OUTPUT, web.LIBRARY, web.UPLOADS):
        d.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    web.APP_MODE["port"] = port
    srv = make_server("127.0.0.1", port, web.app, threaded=True)
    threading.Thread(target=srv.serve_forever, name="novel-epub-sunucu", daemon=True).start()
    _started.update(port=port, server=srv)
    print(f"WEBNOVEL_PORT={port}", flush=True)  # emülatör testi bu satırdan portu bulur
    print(f"WEBNOVEL_TOKEN={web.API_TOKEN}", flush=True)  # (uygulama kayıtlarını yalnız adb okuyabilir)
    return port


def token() -> str:
    """Arayüzün erişim anahtarı: telefondaki başka uygulamalar 127.0.0.1'deki sunucuyu kullanamasın."""
    from . import web

    return web.API_TOKEN


def busy() -> bool:
    """Süren bir indirme/çeviri var mı (Kotlin, hizmeti ve uyanık kalma kilidini buna göre tutar)."""
    if not _started:
        return False
    from . import web

    return bool(web.running_jobs())


def status() -> str:
    """Bildirimde gösterilecek kısa durum: "Kitap adı · 120/813 · çevriliyor" ya da boş."""
    if not _started:
        return ""
    from . import web

    jobs = web.running_jobs()
    if not jobs:
        return ""
    p = jobs[0].p
    count = f" · {p.done}/{p.total}" if p.total else ""
    return f"{p.title or 'Hazırlanıyor'}{count} · {p.phase}"


def output_path(name: str) -> str:
    """İndirilecek kitabın telefondaki tam yolu (Kotlin onu İndirilenler'e kopyalayıp açar)."""
    from . import web

    path = (web.OUTPUT / name).resolve()
    if web.OUTPUT.resolve() not in path.parents or not path.is_file():
        raise FileNotFoundError(name)
    return str(path)
