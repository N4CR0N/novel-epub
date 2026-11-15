"""PC'de çalışan yerel web arayüzü. Aynı Wi‑Fi'deki telefondan da açılır, hazır kitaplar oradan indirilir."""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, abort, jsonify, render_template, request, send_from_directory

from . import __version__
from .exporters import DEFAULT_FORMAT, EXTENSIONS, FORMATS, normalize
from .pipeline import Job, Options
from .store import BookStore
from .translator import DEFAULT_MODELS, DEFAULT_TEMPERATURE, LANGUAGES, MAX_AUTO_CHAPTERS, THINKING_LEVELS

BASE = Path(os.environ.get("NOVEL_EPUB_HOME", Path.cwd()))
SETTINGS_PATH = BASE / "ayarlar.json"
LIBRARY = BASE / "kutuphane"
OUTPUT = BASE / "cikti"
UPLOADS = BASE / "yuklenen"
MAX_UPLOAD_MB = 300

app = Flask(__name__)
JOBS: dict[str, Job] = {}
APP_MODE: dict = {}  # masaüstü uygulaması doldurur: {"port": ...}
ANDROID = os.environ.get("NOVEL_EPUB_ANDROID") == "1"  # telefon uygulaması (android_main.py)
DONE_PHASES = ("bitti", "hata", "iptal edildi")


def running_jobs() -> list[Job]:
    return [j for j in JOBS.values() if j.p.phase not in DONE_PHASES]


KEYRING_SERVICE = "novel-epub"


def _kr_user(pid: str) -> str:
    return f"{pid}_api_key"  # Gemini için eski ad da budur: "gemini_api_key"


def _keyring():
    """İşletim sisteminin şifre kasası (Windows: Kimlik Bilgisi Yöneticisi); yoksa None."""
    try:
        import keyring
        from keyring.backends.fail import Keyring as FailKeyring

        if isinstance(keyring.get_keyring(), FailKeyring) and sys.platform == "win32":
            # Paketlenmiş uygulamada eklenti kaydı bulunamayabilir: Windows kasasını doğrudan seç.
            from keyring.backends.Windows import WinVaultKeyring

            keyring.set_keyring(WinVaultKeyring())
        return None if isinstance(keyring.get_keyring(), FailKeyring) else keyring
    except Exception:
        return None


def _read_file() -> dict:
    return json.loads(SETTINGS_PATH.read_text("utf-8")) if SETTINGS_PATH.exists() else {}


def _write_file(data: dict) -> None:
    SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def load_settings() -> dict:
    """Ayarlar + anahtarlar. Anahtarlar kasada (yoksa ayarlar.json'da); ortam değişkeni hepsini ezer.

    s["keys"]: {sağlayıcı: anahtar}, s["models"]: seçili modeller (LiteLLM adları, en iyiden kötüye),
    s["providers"]: {sağlayıcı: {"models": [erişilen modeller]}}.
    """
    from .providers import ENV_KEYS, parse_or_empty, provider_of

    s = {"delay": 0.7, "workers": 3, "batch": 0, "thinking": "medium", "temperature": DEFAULT_TEMPERATURE,
         "lang": "tr", "providers": {}, "models": [], "output_format": DEFAULT_FORMAT}
    file = _read_file()
    s.update(file)
    s["lang_set"] = bool(file.get("lang_set") or "lang" in file)  # kullanıcı hedef dili seçmiş mi
    # Eski sürüm: tek Gemini anahtarı + virgüllü "model" metni.
    if "models" not in file:
        s["models"] = parse_or_empty(os.environ.get("GEMINI_MODEL") or file.get("model") or DEFAULT_MODELS)
    file_keys: dict = dict(file.get("keys") or {})
    if file.get("api_key"):
        file_keys.setdefault("gemini", file["api_key"])
    for m in s["models"]:  # seçili modellerin sağlayıcıları listede görünsün
        s["providers"].setdefault(provider_of(m).id, {})
    kr = _keyring()
    keys: dict[str, str] = {}
    store = "dosya"
    if kr:
        try:
            if file_keys:  # düz metin anahtarları kasaya taşı
                for pid, k in file_keys.items():
                    kr.set_password(KEYRING_SERVICE, _kr_user(pid), k)
                file.pop("api_key", None)
                file.pop("keys", None)
                file.setdefault("models", s["models"])
                _write_file(file)
            for pid in set(s["providers"]) | set(file_keys) | {"gemini"}:
                k = kr.get_password(KEYRING_SERVICE, _kr_user(pid))
                if k:
                    keys[pid] = k
                    s["providers"].setdefault(pid, {})
            store = "kasa"
        except Exception:
            kr = None
    if not kr:
        keys = file_keys
    for pid, env in ENV_KEYS.items():
        if os.environ.get(env):
            keys[pid], store = os.environ[env], "ortam"
            s["providers"].setdefault(pid, {})
    s["keys"], s["key_store"] = keys, store
    s["api_key"] = keys.get("gemini", "")  # eski kullanım
    if s.get("batch") == 3 and not s.get("batch_set"):  # eski sabit varsayılan → otomatik
        s["batch"] = 0
    return s


def save_settings(s: dict, new_keys: dict | None = None, removed: tuple = ()) -> None:
    """Ayarları ayarlar.json'a yazar; anahtarlar kasa varsa kasaya, yoksa dosyaya gider."""
    out = {k: v for k, v in s.items() if k not in ("api_key", "key_store", "keys", "model")}
    file_keys = dict(s.get("keys") or {}) if s.get("key_store") == "dosya" else {}
    kr = _keyring()
    for pid, key in (new_keys or {}).items():
        stored = False
        if kr:
            try:
                kr.set_password(KEYRING_SERVICE, _kr_user(pid), key)
                stored = True
            except Exception:
                pass
        if not stored:
            file_keys[pid] = key
    for pid in removed:
        file_keys.pop(pid, None)
        if kr:
            try:
                kr.delete_password(KEYRING_SERVICE, _kr_user(pid))
            except Exception:
                pass
    if file_keys:
        out["keys"] = file_keys
    _write_file(out)


@app.get("/")
def index():
    return render_template("index.html", version=__version__)


def _public_settings(s: dict) -> dict:
    from .providers import BY_ID

    provs = []
    for pid, info in s.get("providers", {}).items():
        p = BY_ID.get(pid)
        if not p:
            continue
        key = s["keys"].get(pid, "")
        provs.append({"id": pid, "name": p.name, "prefix": p.prefix, "has_key": bool(key) or p.auth == "none",
                      "hint": (f"…{key[-4:]}" if key and not key.startswith("http") else key),
                      "available": info.get("models") or [], "key_url": p.key_url})
    hidden = ("api_key", "keys", "providers")
    return {**{k: v for k, v in s.items() if k not in hidden}, "providers": provs,
            "has_key": any(x["has_key"] for x in provs),
            "formats": [{"id": k, "name": v[0]} for k, v in FORMATS.items()]}


@app.get("/api/settings")
def get_settings():
    data = _public_settings(load_settings())
    if not _is_local():
        data["providers"] = [{**p, "hint": "", "available": []} for p in data["providers"]]
    return jsonify(data)


@app.post("/api/settings")
def post_settings():
    s = load_settings()
    data = request.get_json(force=True)
    if data.get("lang") in LANGUAGES:
        s["lang"], s["lang_set"] = data["lang"], True
    if data.get("theme") in ("light", "dark", "system"):
        s["theme"] = data["theme"]
    if data.get("ui_lang") in ("tr", "en", "de", "es", "ru"):
        s["ui_lang"] = data["ui_lang"]
    if data.get("output_format") in FORMATS:
        s["output_format"] = data["output_format"]
    if data.get("thinking") in THINKING_LEVELS:
        s["thinking"] = data["thinking"]
    if data.get("temperature") not in (None, ""):
        s["temperature"] = max(0.0, min(1.5, float(data["temperature"])))
    for k, typ in (("delay", float), ("workers", int), ("batch", int)):
        if data.get(k) not in (None, ""):
            s[k] = typ(data[k])
    s["batch_set"] = True
    save_settings(s)
    return get_settings()


@app.post("/api/keys")
def add_key():
    """Anahtarı yapıştır: sağlayıcı tanınır, erişilen modeller listelenir, en iyi 5'i seçili gelir (ilk kez)."""
    from .providers import KeyError_, detect, rank

    key = (request.get_json(force=True).get("key") or "").strip()
    if not key:
        return jsonify({"error": "Anahtar boş"}), 400
    try:
        prov, available = detect(key)
    except KeyError_ as e:
        return jsonify({"error": str(e)}), 400
    s = load_settings()
    s["providers"].setdefault(prov.id, {})["models"] = available
    if not any(m.startswith(prov.prefix + "/") for m in s["models"]):
        s["models"] = rank(s["models"] + available[:5])
    save_settings(s, new_keys={prov.id: key})
    return jsonify({"provider": prov.id, "name": prov.name, "models": len(available),
                    **_public_settings(load_settings())})


@app.delete("/api/keys/<pid>")
def remove_key(pid: str):
    from .providers import BY_ID

    if pid not in BY_ID:
        abort(404)
    s = load_settings()
    s["providers"].pop(pid, None)
    s["keys"].pop(pid, None)
    s["models"] = [m for m in s["models"] if not m.startswith(BY_ID[pid].prefix + "/")]
    save_settings(s, removed=(pid,))
    return get_settings()


@app.post("/api/keys/<pid>/refresh")
def refresh_models(pid: str):
    from .providers import BY_ID, KeyError_, list_models

    s = load_settings()
    if pid not in BY_ID or (pid not in s["keys"] and BY_ID[pid].auth != "none"):
        return jsonify({"error": "Bu sağlayıcı için anahtar yok"}), 400
    try:
        s["providers"].setdefault(pid, {})["models"] = list_models(BY_ID[pid], s["keys"].get(pid, ""))
    except Exception as e:
        return jsonify({"error": str(e)[:300]}), 400
    save_settings(s)
    return get_settings()


@app.post("/api/models")
def set_models():
    """Seçili modeller; sıra her zaman otomatik: en iyiden en kötüye."""
    from .providers import rank

    chosen = request.get_json(force=True).get("models") or []
    s = load_settings()
    allowed = {m for info in s["providers"].values() for m in info.get("models") or []} | set(s["models"])
    s["models"] = rank([m for m in dict.fromkeys(chosen) if m in allowed])
    save_settings(s)
    return get_settings()


@app.get("/api/sources")
def sources():
    """Özel destekli siteler (arayüzde gösterilir)."""
    from .sources import SOURCES

    return jsonify([{"name": c.name, "domains": list(c.domains)} for c in SOURCES])


@app.get("/api/languages")
def languages():
    return jsonify([{"code": c, "name": ui} for c, (_, ui) in LANGUAGES.items()])


@app.post("/api/upload")
def upload():
    from .files import SUPPORTED

    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "Dosya seçilmedi"}), 400
    name = Path(f.filename).name
    ext = Path(name).suffix.lower()
    if ext not in SUPPORTED:
        return jsonify({"error": f"Desteklenmeyen tür: {ext or '?'} (desteklenen: {', '.join(SUPPORTED)})"}), 400
    UPLOADS.mkdir(parents=True, exist_ok=True)
    _prune_uploads()
    safe = re.sub(r"[^\w.\- ]+", "_", name)[:120]
    tmp = UPLOADS / f".yukleniyor-{uuid.uuid4().hex[:8]}"
    f.save(tmp)
    if tmp.stat().st_size > MAX_UPLOAD_MB * 1024 * 1024:
        tmp.unlink()
        return jsonify({"error": f"Dosya {MAX_UPLOAD_MB} MB'tan büyük"}), 400
    # Aynı dosya aynı kimliği alır: yeniden yüklemede kopya birikmez, kitap klasörü de aynı kalır (kaldığı yerden sürer).
    digest = hashlib.sha1(tmp.read_bytes()).hexdigest()[:12]
    file_id = f"{digest}_{safe}"
    dest = UPLOADS / file_id
    tmp.replace(dest)
    try:  # hemen okunabiliyor mu: kitap adı ve bölüm sayısı
        from .files import load_file

        novel, chapters, _ = load_file(dest)
    except Exception as e:
        dest.unlink(missing_ok=True)
        return jsonify({"error": str(e)}), 400
    return jsonify({"id": file_id, "name": name, "title": novel.title, "chapters": len(chapters),
                    "words": sum(len(" ".join(c.paragraphs).split()) for c in chapters)})


UPLOAD_KEEP_DAYS = 7


def _prune_uploads() -> None:
    """Yüklenen dosyalar okunup bölümleri kitap klasörüne kaydedildikten sonra gereksiz; bir haftadan eskileri silinir."""
    limit = time.time() - UPLOAD_KEEP_DAYS * 86400
    for p in UPLOADS.glob("*") if UPLOADS.is_dir() else []:
        try:
            if p.is_file() and p.stat().st_mtime < limit:
                p.unlink()
        except OSError:
            pass


def _upload_path(file_id: str) -> Path | None:
    p = UPLOADS / Path(file_id).name
    return p if file_id and p.is_file() else None


@app.post("/api/test-site")
def test_site():
    """Bir linkin desteklenip desteklenmediğini dener: bölüm listesi + ilk bölüm."""
    from .cleaner import check_chapter
    from .fetcher import Fetcher
    from .sources import source_for

    url = (request.get_json(force=True).get("url") or "").strip()
    if not url.startswith("http"):
        return jsonify({"error": "Geçerli bir link gir"}), 400
    src = source_for(url, Fetcher(delay=0.3, retries=2))
    out = {"source": src.name}
    try:
        novel = src.novel(url)
        out.update(title=novel.title, chapters=len(novel.chapters), follow_next=novel.follow_next,
                   first=novel.chapters[0].title if novel.chapters else "",
                   last=novel.chapters[-1].title if novel.chapters else "")
        if novel.chapters:
            ch = src.chapter(novel.chapters[0])
            out.update(sample_paragraphs=len(ch.paragraphs), sample_chars=ch.char_count, issues=check_chapter(ch))
        out["ok"] = bool(novel.chapters) and not out.get("issues")
    except Exception as e:
        out.update(ok=False, error=str(e)[:300])
    return jsonify(out)


@app.get("/api/history-scan")
def history_scan():
    """Bu PC'deki Brave/Chrome/Edge geçmişi + yer işaretlerinden novel siteleri (yalnız yerel)."""
    if not _is_local():
        abort(403)
    from .history import scan

    return jsonify(scan(_supported))


def _supported(u: str):
    from .sources import SOURCES

    return next((c.name for c in SOURCES if c.matches(u)), None)


@app.get("/api/phone/status")
def phone_status():
    """Root'lu Android telefon: adb var mı, bağlı cihaz ve izin durumu (yalnız yerel)."""
    if not _is_local():
        abort(403)
    from .history import find_adb, phone_devices

    adb = find_adb(BASE)
    if not adb:
        return jsonify({"adb": False})
    try:
        return jsonify({"adb": True, "devices": [{"serial": sn, "state": st} for sn, st in phone_devices(adb)]})
    except Exception as e:
        return jsonify({"adb": True, "devices": [], "error": str(e)[:200]})


@app.post("/api/phone/adb-download")
def phone_adb_download():
    if not _is_local():
        abort(403)
    from .history import download_adb

    try:
        return jsonify({"ok": True, "adb": download_adb(BASE)})
    except Exception as e:
        return jsonify({"error": f"adb indirilemedi: {e}"}), 400


@app.post("/api/phone/scan")
def phone_scan():
    """Telefondan (root, USB) tarayıcı geçmişi + yer işaretlerini PC'ye kopyalar ve tarar."""
    if not _is_local():
        abort(403)
    from .history import PhoneError, find_adb, pull_android, scan

    adb = find_adb(BASE)
    if not adb:
        return jsonify({"error": "adb yok; önce indir"}), 400
    dest = BASE / "telefon-gecmis"
    try:
        dirs = pull_android(adb, dest)
    except PhoneError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({**scan(_supported, dirs), "copied_to": str(dest)})


@app.post("/api/jobs")
def start_job():
    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()
    file_path = _upload_path(data.get("file_id") or "") if data.get("file_id") else None
    if data.get("file_id") and not file_path:
        return jsonify({"error": "Yüklenen dosya bulunamadı; yeniden seç"}), 400
    if not file_path and not url.startswith("http"):
        return jsonify({"error": "Geçerli bir link gir ya da dosya seç"}), 400
    s = load_settings()
    lang = data.get("lang") if data.get("lang") in LANGUAGES else s.get("lang", "tr")
    opts = Options(
        url=url,
        file=str(file_path) if file_path else "",
        lang=lang,
        start=int(data["start"]) if data.get("start") else None,
        end=int(data["end"]) if data.get("end") else None,
        translate=bool(data.get("translate")),
        keys=s.get("keys", {}),
        model=", ".join(s.get("models") or []),
        delay=float(s.get("delay", 0.7)),
        workers=int(s.get("workers", 3)),
        batch=max(0, min(MAX_AUTO_CHAPTERS, int(s.get("batch", 0)))),
        edit=bool(data.get("edit", True)),
        thinking=s.get("thinking", "medium"),
        temperature=float(s.get("temperature", DEFAULT_TEMPERATURE)),
        review_after=20 if data.get("review") else 0,
        library=LIBRARY,
        output=OUTPUT,
        fmt=normalize(data.get("format") or s.get("output_format")),
    )
    if opts.translate and (not opts.model or (not opts.keys and not opts.model.startswith("ollama_chat/"))):
        return jsonify({"error": "Çeviri için önce Ayarlar'dan bir API anahtarı ekle ve en az bir model seç"}), 400
    job_id = uuid.uuid4().hex[:10]
    job = Job(opts, on_log=print)
    JOBS[job_id] = job
    threading.Thread(target=job.run, daemon=True).start()
    return jsonify({"id": job_id})


@app.get("/api/jobs/<job_id>")
def job_status(job_id: str):
    job = JOBS.get(job_id) or abort(404)
    p = job.p
    return jsonify({
        "phase": p.phase, "done": p.done, "total": p.total, "title": p.title, "error": p.error, "notice": p.notice,
        "result": Path(p.result).name if p.result else "", "report": p.report, "logs": p.logs[-80:],
        "running": p.phase not in DONE_PHASES,
    })


@app.post("/api/jobs/<job_id>/cancel")
def job_cancel(job_id: str):
    (JOBS.get(job_id) or abort(404)).cancel()
    return jsonify({"ok": True})


def _lang() -> str:
    lang = request.args.get("lang", "tr")
    return lang if lang in LANGUAGES else "tr"


def _book(name: str) -> BookStore:
    """Kitaplıktaki bir kitap klasörü (yalnızca var olan klasör adları kabul edilir)."""
    names = {d.name for d in LIBRARY.iterdir() if d.is_dir()} if LIBRARY.exists() else set()
    if name not in names:
        abort(404)
    return BookStore(LIBRARY, dirname=name, lang=_lang())


@app.get("/api/library")
def library():
    out = []
    for d in sorted(LIBRARY.glob("*/kitap.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        meta = json.loads(d.read_text("utf-8"))
        st = BookStore(LIBRARY, dirname=d.parent.name, lang=_lang())
        out.append({"id": d.parent.name, "title": meta.get("title", d.parent.name), "url": meta.get("url", ""),
                    **st.counts(), "terms": len(st.load_glossary())})
    return jsonify(out)


@app.get("/api/library/<name>/glossary")
def get_glossary(name: str):
    st = _book(name)
    return jsonify({"glossary": st.load_glossary(), "memory": st.load_memory(), "notes": st.load_notes()})


@app.post("/api/library/<name>/notes")
def put_notes(name: str):
    st = _book(name)
    st.save_notes(str(request.get_json(force=True).get("notes") or "")[:8000])
    return jsonify({"ok": True})


@app.post("/api/library/<name>/glossary")
def put_glossary(name: str):
    st = _book(name)
    g = request.get_json(force=True).get("glossary")
    if not isinstance(g, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in g.items()):
        return jsonify({"error": 'Sözlük {"kaynak": "karşılık", ...} biçiminde olmalı'}), 400
    st.save_glossary({k.strip(): v.strip() for k, v in g.items() if k.strip() and v.strip()})
    return jsonify({"ok": True, "terms": len(st.load_glossary())})


@app.post("/api/library/<name>/retranslate")
def retranslate(name: str):
    st = _book(name)
    data = request.get_json(force=True)
    try:
        a, b = int(data["start"]), int(data["end"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Bölüm aralığı gir"}), 400
    n = sum(st.drop_tr(i) for i in range(a, b + 1))
    return jsonify({"ok": True, "removed": n})


@app.post("/api/library/<name>/restore")
def restore(name: str):
    st = _book(name)
    data = request.get_json(force=True)
    try:
        a, b = int(data["start"]), int(data["end"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Bölüm aralığı gir"}), 400
    n = sum(st.restore_tr(i) for i in range(a, b + 1))
    return jsonify({"ok": True, "restored": n})


@app.get("/api/books")
def books():
    OUTPUT.mkdir(exist_ok=True)
    files = sorted((f for f in OUTPUT.iterdir() if f.is_file() and f.suffix[1:].lower() in EXTENSIONS),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return jsonify([{"name": f.name, "mb": round(f.stat().st_size / 1e6, 2), "format": EXTENSIONS[f.suffix[1:].lower()]}
                    for f in files])


@app.get("/indir/<path:name>")
def download(name: str):
    fmt = EXTENSIONS.get(Path(name).suffix[1:].lower())
    if not fmt:
        abort(404)
    return send_from_directory(OUTPUT.resolve(), name, as_attachment=True, mimetype=FORMATS[fmt][2])


def _is_local() -> bool:
    return request.remote_addr in ("127.0.0.1", "::1")


# Ağdaki başka cihazlar (telefon) yalnız bunları okuyabilir: sayfa, kitap listesi, kitap indirme.
_LAN_READ = {"/", "/api/info", "/api/books", "/api/languages", "/api/settings"}


def _host_ok(host: str) -> bool:
    """DNS yeniden bağlama saldırısına karşı: yalnız IP adresi ya da localhost ile gelinebilir."""
    import ipaddress

    name = host.rsplit(":", 1)[0] if host.count(":") == 1 or host.startswith("[") else host
    name = name.strip("[]")
    if name == "localhost":
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False


@app.before_request
def _guard():
    if not _host_ok(request.host or ""):
        abort(403)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("Origin")
        # başka bir sitenin sayfası, kullanıcının tarayıcısından buraya istek gönderemesin (CSRF)
        if origin is not None and urlsplit(origin).netloc != request.host:
            abort(403)
    if not _is_local():
        if request.method in ("GET", "HEAD") and (request.path in _LAN_READ or request.path.startswith("/indir/")):
            return None
        abort(403)
    return None


@app.get("/api/info")
def info():
    port = APP_MODE.get("port") or request.host.rsplit(":", 1)[-1]
    return jsonify({"app": bool(APP_MODE), "local": _is_local(), "android": ANDROID, "version": __version__,
                    "phone_url": f"http://{lan_ip()}:{port}",
                    "home": str(BASE) if _is_local() else ""})


@app.post("/api/open-folder")
def open_folder():
    """Çıktı (ya da veri) klasörünü Dosya Gezgini'nde açar; yalnızca bu PC'den çağrılabilir."""
    if not _is_local():
        abort(403)
    target = OUTPUT if (request.get_json(silent=True) or {}).get("which") != "home" else BASE
    target.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(target)  # noqa: S606 — yerel klasör
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(target)])
    return jsonify({"ok": True})


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def serve(host: str = "0.0.0.0", port: int = 5000) -> None:
    OUTPUT.mkdir(exist_ok=True)
    LIBRARY.mkdir(exist_ok=True)
    print(f"\n  WebNovel Downloader & Translator hazır.\n  Bu PC'de:      http://127.0.0.1:{port}")
    if host == "0.0.0.0":
        print(f"  Telefonda (aynı Wi‑Fi): http://{lan_ip()}:{port}\n")
    app.run(host=host, port=port, threaded=True)
