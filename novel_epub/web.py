"""PC'de çalışan yerel web arayüzü. Aynı Wi‑Fi'deki telefondan da açılır, hazır kitaplar oradan indirilir."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import uuid
import zipfile
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
# Her açılışta yeni bir erişim anahtarı: yalnız uygulamanın kendi penceresi bilir (adresin #t= kısmı, sunucuya
# gitmez). Bilgisayardaki/telefondaki başka bir program 127.0.0.1'e bağlansa da ayarlara ve işlere dokunamaz.
API_TOKEN = os.environ.get("NOVEL_EPUB_TOKEN") or secrets.token_urlsafe(24)
SERVER: dict = {"srv": None, "port": 0, "lan": False}  # çalışan sunucu; lan: aynı Wi‑Fi'deki cihazlara açık mı
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
    # Dosyadaki anahtarlar dosyadan okunur: s["keys"] ortam değişkeni anahtarlarını da içerir (onları diske yazma),
    # ortam değişkeni varken de dosyadaki diğer anahtarlar silinmesin.
    old = _read_file()
    file_keys = dict(old.get("keys") or {})
    if old.get("api_key"):
        file_keys.setdefault("gemini", old["api_key"])
    if s.get("key_store") == "dosya":  # anahtarların tamamı dosyadan geldiyse (ortamdan değil) aynen korunur
        file_keys.update(s.get("keys") or {})
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
    from .providers import BY_ID, PROVIDERS

    provs = []
    for pid, info in s.get("providers", {}).items():
        p = BY_ID.get(pid)
        if not p:
            continue
        key = s["keys"].get(pid, "")
        provs.append({"id": pid, "name": p.name, "prefix": p.prefix, "has_key": bool(key) or p.auth == "none",
                      "hint": (f"…{key[-4:]}" if key and not key.startswith("http") else key),
                      "available": info.get("models") or [], "key_url": p.key_url})
    hidden = ("api_key", "keys", "providers", "drive")  # drive: Google oturumu (yenileme anahtarı) asla arayüze gitmez
    where = s.get("key_store")
    if where == "kasa" and sys.platform == "win32":
        where = "windows"
    elif where == "dosya" and ANDROID:
        where = "android"
    return {**{k: v for k, v in s.items() if k not in hidden}, "providers": provs, "key_store": where,
            "has_key": any(x["has_key"] for x in provs),
            "formats": [{"id": k, "name": v[0]} for k, v in FORMATS.items()],
            "all_providers": [{"id": p.id, "name": p.name} for p in PROVIDERS if p.auth != "none"]}


@app.get("/api/settings")
def get_settings():
    data = _public_settings(load_settings())
    if not _trusted():
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
    limits = {"temperature": (float, 0.0, 1.5), "delay": (float, 0.0, 30.0), "workers": (int, 1, 8),
              "batch": (int, 0, MAX_AUTO_CHAPTERS)}
    for k, (typ, lo, hi) in limits.items():
        if data.get(k) in (None, ""):
            continue
        try:
            v = typ(float(data[k]))
        except (TypeError, ValueError, OverflowError):
            return jsonify({"error": f"Geçersiz değer: {k}"}), 400
        if v != v:  # NaN
            return jsonify({"error": f"Geçersiz değer: {k}"}), 400
        s[k] = max(lo, min(hi, v))
    s["batch_set"] = True
    save_settings(s)
    return get_settings()


@app.post("/api/keys")
def add_key():
    """Anahtarı yapıştır: sağlayıcı tanınır, erişilen modeller listelenir, en iyi 5'i seçili gelir (ilk kez)."""
    from .providers import KeyError_, UnknownFormat, detect, rank

    data = request.get_json(force=True)
    key = (data.get("key") or "").strip()
    if not key:
        return jsonify({"error": "Anahtar boş"}), 400
    try:
        prov, available = detect(key, provider=str(data.get("provider") or ""))
    except UnknownFormat as e:
        return jsonify({"error": str(e), "choose_provider": True}), 400
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
    if not _trusted():
        abort(403)
    from .history import scan

    return jsonify(scan(_supported))


def _supported(u: str):
    from .sources import SOURCES

    return next((c.name for c in SOURCES if c.matches(u)), None)


@app.get("/api/phone/status")
def phone_status():
    """Root'lu Android telefon: adb var mı, bağlı cihaz ve izin durumu (yalnız yerel)."""
    if not _trusted():
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
    if not _trusted():
        abort(403)
    from .history import download_adb

    try:
        return jsonify({"ok": True, "adb": download_adb(BASE)})
    except Exception as e:
        return jsonify({"error": f"adb indirilemedi: {e}"}), 400


@app.post("/api/phone/scan")
def phone_scan():
    """Telefondan (root, USB) tarayıcı geçmişi + yer işaretlerini PC'ye kopyalar ve tarar."""
    if not _trusted():
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
    except Exception as e:  # telefon çıkarıldı, adb takıldı…
        return jsonify({"error": f"Telefondan okunamadı: {type(e).__name__}: {e}"}), 400
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
    try:
        start = int(data["start"]) if data.get("start") else None
        end = int(data["end"]) if data.get("end") else None
    except (TypeError, ValueError, OverflowError):
        return jsonify({"error": "Bölüm aralığı sayı olmalı"}), 400
    if (start is not None and start < 1) or (start and end and end < start):
        return jsonify({"error": "Bölüm aralığı geçersiz"}), 400
    s = load_settings()
    lang = data.get("lang") if data.get("lang") in LANGUAGES else s.get("lang", "tr")
    opts = Options(
        url=url,
        file=str(file_path) if file_path else "",
        lang=lang,
        start=start,
        end=end,
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
        audit=bool(data.get("audit")),
    )
    if opts.translate and (not opts.model or (not opts.keys and not opts.model.startswith("ollama_chat/"))):
        return jsonify({"error": "Çeviri için önce Ayarlar'dan bir API anahtarı ekle ve en az bir model seç"}), 400
    source = f"dosya:{file_path.name}" if file_path else url
    for jid, j in JOBS.items():  # aynı kitap aynı dile zaten işleniyorsa ikinci iş açma, ona bağlan
        if j.p.phase not in DONE_PHASES and getattr(j, "source_key", None) == (source, lang):
            return jsonify({"error": "Bu kitap zaten işleniyor", "id": jid}), 409
    _prune_jobs()
    job_id = uuid.uuid4().hex[:10]
    job = Job(opts, on_log=print)
    job.source_key = (source, lang)
    job.started = time.time()
    JOBS[job_id] = job
    threading.Thread(target=_run_job, args=(job,), daemon=True).start()
    return jsonify({"id": job_id})


def _run_job(job: Job) -> None:
    """İşi çalıştırır; Google Drive'a bağlıysa ve otomatik yükleme açıksa biten kitabı Drive'a yükler."""
    out = job.run()
    if not out or not _drive_state().get("auto", True) or not _drive().signed_in():
        return
    try:
        job.log("Google Drive'a yükleniyor…")
        _drive().upload(Path(out), mime=_mime(Path(out)))
        job.log(f"Google Drive'a yüklendi: {Path(out).name}")
    except Exception as e:  # yükleme olmasa da kitap hazır
        job.log(f"Google Drive'a yüklenemedi: {e}")


MAX_FINISHED_JOBS = 10


def _prune_jobs() -> None:
    """Biten işler bellekte birikmesin: en yeni 10'u kalır (sonuçları kitaplıkta/çıktıda zaten duruyor)."""
    done = [jid for jid, j in JOBS.items() if j.p.phase in DONE_PHASES]
    for jid in done[:-MAX_FINISHED_JOBS] if len(done) > MAX_FINISHED_JOBS else []:
        JOBS.pop(jid, None)


@app.get("/api/jobs")
def job_list():
    """Sayfa yenilenince ya da pencere yeniden açılınca süren işe yeniden bağlanmak için (en yeni önce)."""
    items = [{"id": jid, "title": j.p.title, "phase": j.p.phase, "running": j.p.phase not in DONE_PHASES,
              "started": getattr(j, "started", 0)} for jid, j in JOBS.items()]
    return jsonify(sorted(items, key=lambda x: x["started"], reverse=True))


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
    a, b = _range(data)
    if a is None:
        return jsonify({"error": "Bölüm aralığı gir (ör. 10–25; en çok 10000 bölüm)"}), 400
    n = sum(st.drop_tr(i) for i in range(a, b + 1))
    return jsonify({"ok": True, "removed": n})


def _range(data: dict) -> tuple[int | None, int | None]:
    try:
        a, b = int(data["start"]), int(data["end"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None, None
    if a < 1 or b < a or b - a >= 10000:
        return None, None
    return a, b


@app.post("/api/library/<name>/restore")
def restore(name: str):
    st = _book(name)
    data = request.get_json(force=True)
    a, b = _range(data)
    if a is None:
        return jsonify({"error": "Bölüm aralığı gir (ör. 10–25; en çok 10000 bölüm)"}), 400
    n = sum(st.restore_tr(i) for i in range(a, b + 1))
    return jsonify({"ok": True, "restored": n})


@app.get("/api/books")
def books():
    OUTPUT.mkdir(exist_ok=True)
    files = sorted((f for f in OUTPUT.iterdir() if f.is_file() and f.suffix[1:].lower() in EXTENSIONS),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    prog = _progress().all()

    def pct(name: str):
        r = prog.get(name)
        return round(100 * (r["ch"] + r["frac"]) / r["total"]) if r and r.get("total") else None

    return jsonify([{"name": f.name, "mb": round(f.stat().st_size / 1e6, 2), "format": EXTENSIONS[f.suffix[1:].lower()],
                     "read": pct(f.name)} for f in files])


def _epub(name: str) -> Path:
    """Çıktı klasöründeki bir EPUB (yalnız var olan dosya adları; klasör dışına çıkılamaz)."""
    path = (OUTPUT / Path(name).name).resolve()
    if path.suffix.lower() != ".epub" or path.parent != OUTPUT.resolve() or not path.is_file():
        abort(404)
    return path


def _progress():
    from .reader import Progress

    return Progress(BASE / "okuma.json")


@app.get("/api/read/<name>")
def read_book(name: str):
    """Okuyucu: kitabın başlığı, içindekiler ve kaldığın yer."""
    from .reader import open_book

    try:
        book = open_book(_epub(name))
    except (OSError, ValueError, KeyError, AttributeError, zipfile.BadZipFile):
        return jsonify({"error": "Bu EPUB açılamadı"}), 400
    return jsonify({"name": name, "title": book.title, "author": book.author, "language": book.language,
                    "toc": book.toc(), "cover": bool(book.cover), "progress": _progress().get(name)})


@app.get("/api/read/<name>/<int:index>")
def read_chapter(name: str, index: int):
    from .reader import open_book

    book = open_book(_epub(name))
    if not 0 <= index < len(book.items):
        abort(404)
    return jsonify(book.chapter(index))


@app.get("/api/read/<name>/cover")
def read_cover(name: str):
    from .reader import open_book

    got = open_book(_epub(name)).cover_bytes()
    if not got:
        abort(404)
    return app.response_class(got[0], mimetype=got[1], headers={"Cache-Control": "max-age=86400"})


@app.post("/api/read/<name>/progress")
def read_progress(name: str):
    _epub(name)
    data = request.get_json(force=True)
    try:
        return jsonify(_progress().set(name, data.get("ch", 0), data.get("frac", 0), data.get("t"), data.get("total", 0)))
    except (TypeError, ValueError):
        return jsonify({"error": "Geçersiz konum"}), 400


# --- Google Drive ---------------------------------------------------------------------------------------------
_DRIVE: dict = {}
_DRIVE_TASK: dict = {"busy": "", "last": "", "error": ""}
_DRIVE_KR = "google_drive_refresh"


def _drive_state() -> dict:
    return dict(_read_file().get("drive") or {})


def _drive_load() -> dict:
    st = _drive_state()
    kr = _keyring()
    if kr and not st.get("refresh"):
        try:
            st["refresh"] = kr.get_password(KEYRING_SERVICE, _DRIVE_KR) or ""
        except Exception:
            pass
    return st


def _drive_save(new: dict) -> None:
    """Yenileme anahtarı kasaya (yoksa ayarlar dosyasına); e-posta, klasör ve otomatik yükleme ayarı dosyaya."""
    file = _read_file()
    old = dict(file.get("drive") or {})
    st = {"auto": old.get("auto", True), **{k: v for k, v in new.items() if k != "refresh"}}
    refresh = new.get("refresh", "")
    kr = _keyring()
    stored = False
    if kr:
        try:
            if refresh:
                kr.set_password(KEYRING_SERVICE, _DRIVE_KR, refresh)
            elif "refresh" not in new or not refresh:
                try:
                    kr.delete_password(KEYRING_SERVICE, _DRIVE_KR)
                except Exception:
                    pass
            stored = True
        except Exception:
            stored = False
    if refresh and not stored:
        st["refresh"] = refresh
    file["drive"] = st
    _write_file(file)


def _drive():
    from .drive import Drive

    if "d" not in _DRIVE:
        _DRIVE["d"] = Drive(_drive_load, _drive_save)
    return _DRIVE["d"]


def _mime(path: Path) -> str:
    fmt = EXTENSIONS.get(path.suffix[1:].lower())
    return FORMATS[fmt][2] if fmt else "application/zip"


def _drive_bg(label: str, fn) -> None:
    """Uzun Drive işlerini (yedek) arka planda yürüt; durum /api/drive'da görünür."""
    if _DRIVE_TASK["busy"]:
        raise RuntimeError("Drive'da başka bir iş sürüyor")
    _DRIVE_TASK.update(busy=label, error="")

    def run():
        try:
            _DRIVE_TASK["last"] = fn() or ""
        except Exception as e:
            _DRIVE_TASK["error"] = str(e)
        finally:
            _DRIVE_TASK["busy"] = ""
    threading.Thread(target=run, daemon=True).start()


@app.get("/api/drive")
def drive_status():
    from .drive import client

    d = _drive()
    return jsonify({"available": bool(client()), "signed_in": d.signed_in(), "email": d.email(),
                    "auto": _drive_state().get("auto", True), **_DRIVE_TASK})


@app.post("/api/drive/login")
def drive_login():
    from .drive import DriveError

    port = request.host.rsplit(":", 1)[-1] if ":" in request.host else "80"
    try:
        url = _drive().auth_url(f"http://127.0.0.1:{port}/oauth2cb")
    except DriveError as e:
        return jsonify({"error": str(e)}), 400
    opened = False
    if not ANDROID:  # Google gömülü pencerede girişe izin vermez: bilgisayarın tarayıcısında aç
        import webbrowser

        try:
            opened = webbrowser.open(url)
        except Exception:
            opened = False
    return jsonify({"url": url, "opened": opened})


@app.get("/oauth2cb")
def drive_callback():
    from .drive import DriveError

    msg, ok = "", False
    if request.args.get("error"):
        msg = "Giriş iptal edildi."
    else:
        try:
            email = _drive().finish(request.args.get("state", ""), request.args.get("code", ""))
            msg, ok = f"Google Drive bağlandı: {email}", True
        except DriveError as e:
            msg = str(e)
    color = "#2a7d5f" if ok else "#b4483c"
    from html import escape

    return (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>WebNovel Downloader &amp; Translator</title><body style='font:16px/1.5 system-ui,sans-serif;"
            f"max-width:32em;margin:15vh auto;padding:0 20px;text-align:center'><h2 style='color:{color}'>{escape(msg)}</h2>"
            f"<p>Bu sekmeyi kapatıp uygulamaya dönebilirsin.</p></body>")


@app.post("/api/drive/logout")
def drive_logout():
    _drive().logout()
    return drive_status()


@app.post("/api/drive/settings")
def drive_settings():
    data = request.get_json(force=True)
    file = _read_file()
    st = dict(file.get("drive") or {})
    if "auto" in data:
        st["auto"] = bool(data["auto"])
    file["drive"] = st
    _write_file(file)
    return drive_status()


@app.post("/api/drive/upload")
def drive_upload():
    from .drive import DriveError

    name = (request.get_json(force=True).get("name") or "")
    path = (OUTPUT / Path(name).name).resolve()
    if path.parent != OUTPUT.resolve() or not path.is_file() or path.suffix[1:].lower() not in EXTENSIONS:
        abort(404)
    try:
        fid = _drive().upload(path, mime=_mime(path))
    except DriveError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, "id": fid})


@app.post("/api/drive/backup")
def drive_backup():
    """Kitaplık (indirilen ve çevrilen bölümler, sözlükler, hafıza) + okuma yerleri tek zip olarak Drive'a."""
    def work():
        tmp = BASE / "kitaplik-yedek.zip"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for f in sorted(LIBRARY.rglob("*")) if LIBRARY.exists() else []:
                if f.is_file():
                    z.write(f, Path("kutuphane") / f.relative_to(LIBRARY))
            if (BASE / "okuma.json").exists():
                z.write(BASE / "okuma.json", "okuma.json")
        try:
            _drive().upload(tmp, "kitaplik-yedek.zip", "application/zip")
        finally:
            tmp.unlink(missing_ok=True)
        return f"Kitaplık yedeklendi ({time.strftime('%d.%m.%Y %H:%M')})"
    try:
        _drive_bg("Kitaplık yedekleniyor…", work)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409
    return drive_status()


@app.get("/api/drive/files")
def drive_files():
    from .drive import DriveError

    try:
        files = _drive().files()
    except DriveError as e:
        return jsonify({"error": str(e)}), 400
    have = {f.name for f in OUTPUT.iterdir()} if OUTPUT.exists() else set()
    return jsonify([{**f, "here": f["name"] in have} for f in files
                    if f["name"].rsplit(".", 1)[-1].lower() in EXTENSIONS])


@app.post("/api/drive/download")
def drive_download():
    from .drive import DriveError

    data = request.get_json(force=True)
    name = Path(str(data.get("name") or "")).name
    if not name or name.rsplit(".", 1)[-1].lower() not in EXTENSIONS or not data.get("id"):
        return jsonify({"error": "Geçersiz dosya"}), 400
    OUTPUT.mkdir(parents=True, exist_ok=True)
    try:
        _drive().download(str(data["id"]), OUTPUT / name)
    except DriveError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, "name": name})


@app.get("/indir/<path:name>")
def download(name: str):
    fmt = EXTENSIONS.get(Path(name).suffix[1:].lower())
    if not fmt:
        abort(404)
    return send_from_directory(OUTPUT.resolve(), name, as_attachment=True, mimetype=FORMATS[fmt][2])


def _is_local() -> bool:
    return request.remote_addr in ("127.0.0.1", "::1")


def _trusted() -> bool:
    """Uygulamanın kendi penceresi: bu cihazdan ve erişim anahtarıyla gelen istek."""
    return _is_local() and hmac.compare_digest(request.headers.get("X-Token", ""), API_TOKEN)


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
    if _trusted():
        return None
    if request.path == "/oauth2cb" and request.method == "GET" and _is_local():  # Google girişinin dönüşü (state ile doğrulanır)
        return None
    if request.method in ("GET", "HEAD") and (request.path in _LAN_READ or request.path.startswith(("/indir/", "/api/read/"))):
        if _is_local() or SERVER["lan"]:  # paylaşım kapalıyken ağdan gelen istek hiç kabul edilmez
            return None
    abort(403)


@app.get("/api/info")
def info():
    port = APP_MODE.get("port") or request.host.rsplit(":", 1)[-1]
    trusted = _trusted()
    return jsonify({"app": bool(APP_MODE), "local": trusted, "loopback": _is_local(), "android": ANDROID,
                    "version": __version__, "lan": SERVER["lan"],
                    "phone_url": f"http://{lan_ip()}:{port}" if trusted else "",
                    "home": str(BASE) if trusted else ""})


@app.post("/api/open-folder")
def open_folder():
    """Çıktı (ya da veri) klasörünü Dosya Gezgini'nde açar; yalnızca bu PC'den çağrılabilir."""
    if not _trusted():
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


_srv_lock = threading.Lock()


def start_server(port: int, lan: bool = False):
    """Sunucuyu başlatır ya da (paylaşım değişince) yeniden başlatır: kapalıyken yalnız 127.0.0.1 dinlenir."""
    from werkzeug.serving import make_server

    with _srv_lock:
        old = SERVER["srv"]
        if old is not None:
            old.shutdown()
            old.server_close()
        try:
            srv = make_server("0.0.0.0" if lan else "127.0.0.1", port, app, threaded=True)
        except OSError:
            if not lan:
                raise
            print("Ağ paylaşımı açılamadı (port kullanımda); yalnız bu bilgisayar.")
            srv, lan = make_server("127.0.0.1", port, app, threaded=True), False
        SERVER.update(srv=srv, port=port, lan=lan)
        threading.Thread(target=srv.serve_forever, name="novel-epub-sunucu", daemon=True).start()
    return srv


def local_url(port: int) -> str:
    """Uygulama penceresinin açacağı adres (erişim anahtarı # kısmında: sunucu kayıtlarına düşmez)."""
    return f"http://127.0.0.1:{port}/#t={API_TOKEN}"


def serve(host: str | None = None, port: int = 5000) -> None:
    OUTPUT.mkdir(exist_ok=True)
    LIBRARY.mkdir(exist_ok=True)
    lan = host != "127.0.0.1"  # varsayılan: aynı Wi‑Fi'deki telefon hazır kitapları indirebilir
    start_server(port, lan)
    print(f"\n  WebNovel Downloader & Translator hazır.\n  Bu PC'de: {local_url(port)}")
    if SERVER["lan"]:
        print(f"  Telefonda (aynı Wi‑Fi, yalnız hazır kitaplar): http://{lan_ip()}:{port}\n")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
