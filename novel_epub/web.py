"""PC'de çalışan yerel web arayüzü. Aynı Wi‑Fi'deki telefondan da açılır, EPUB oradan indirilir."""
from __future__ import annotations

import json
import os
import socket
import threading
import uuid
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_from_directory

from .pipeline import Job, Options
from .store import BookStore
from .translator import DEFAULT_MODEL, DEFAULT_MODELS, DEFAULT_TEMPERATURE, MAX_AUTO_CHAPTERS, THINKING_LEVELS

BASE = Path(os.environ.get("NOVEL_EPUB_HOME", Path.cwd()))
SETTINGS_PATH = BASE / "ayarlar.json"
LIBRARY = BASE / "kutuphane"
OUTPUT = BASE / "cikti"

app = Flask(__name__)
JOBS: dict[str, Job] = {}


KEYRING_SERVICE, KEYRING_USER = "novel-epub", "gemini_api_key"


def _keyring():
    """İşletim sisteminin şifre kasası (Windows: Kimlik Bilgisi Yöneticisi); yoksa None."""
    try:
        import keyring
        from keyring.backends.fail import Keyring as FailKeyring

        return None if isinstance(keyring.get_keyring(), FailKeyring) else keyring
    except Exception:
        return None


def _read_file() -> dict:
    return json.loads(SETTINGS_PATH.read_text("utf-8")) if SETTINGS_PATH.exists() else {}


def load_settings() -> dict:
    s = {"model": os.environ.get("GEMINI_MODEL", DEFAULT_MODELS), "delay": 0.7, "workers": 3, "batch": 0,
         "thinking": "medium", "temperature": DEFAULT_TEMPERATURE}
    file = _read_file()
    s.update(file)
    kr = _keyring()
    key, store = "", "yok"
    if kr:
        try:
            if file.get("api_key"):  # eski sürümden kalan düz metin anahtarı kasaya taşı
                kr.set_password(KEYRING_SERVICE, KEYRING_USER, file["api_key"])
                file.pop("api_key")
                SETTINGS_PATH.write_text(json.dumps(file, ensure_ascii=False, indent=1), encoding="utf-8")
            key, store = kr.get_password(KEYRING_SERVICE, KEYRING_USER) or "", "kasa"
        except Exception:
            kr = None
    if not kr:
        key, store = file.get("api_key", ""), "dosya"
    if os.environ.get("GEMINI_API_KEY"):
        key, store = os.environ["GEMINI_API_KEY"], "ortam"
    s["api_key"], s["key_store"] = key, store
    if s.get("batch") == 3 and not s.get("batch_set"):  # eski sabit varsayılan → otomatik
        s["batch"] = 0
    if s.get("model") == DEFAULT_MODEL:  # eski tek-model varsayılanı: yedek modeli ekle
        s["model"] = DEFAULT_MODELS
    return s


def save_settings(s: dict, new_key: str = "") -> None:
    """Ayarları ayarlar.json'a yazar; anahtar kasa varsa kasaya, yoksa dosyaya gider."""
    out = {k: v for k, v in s.items() if k not in ("api_key", "key_store")}
    key = new_key or (s.get("api_key") if s.get("key_store") == "dosya" else "")
    kr = _keyring()
    if new_key and kr:
        try:
            kr.set_password(KEYRING_SERVICE, KEYRING_USER, new_key)
            key = ""
        except Exception:
            pass
    if key:
        out["api_key"] = key
    SETTINGS_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/settings")
def get_settings():
    s = load_settings()
    key = s.get("api_key", "")
    return jsonify({**s, "api_key": "", "has_key": bool(key), "key_hint": f"…{key[-4:]}" if key else ""})



@app.post("/api/settings")
def post_settings():
    s = load_settings()
    data = request.get_json(force=True)
    new_key = (data.get("api_key") or "").strip()
    for k in ("model",):
        if data.get(k):
            s[k] = data[k].strip()
    if data.get("thinking") in THINKING_LEVELS:
        s["thinking"] = data["thinking"]
    if data.get("temperature") not in (None, ""):
        s["temperature"] = max(0.0, min(1.5, float(data["temperature"])))
    for k, typ in (("delay", float), ("workers", int), ("batch", int)):
        if data.get(k) not in (None, ""):
            s[k] = typ(data[k])
    s["batch_set"] = True
    save_settings(s, new_key)
    return get_settings()


@app.get("/api/models")
def models():
    from .translator import list_models

    key = load_settings().get("api_key")
    if not key:
        return jsonify({"error": "Önce API anahtarını kaydet"}), 400
    try:
        return jsonify({"models": list_models(key)})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/jobs")
def start_job():
    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()
    if not url.startswith("http"):
        return jsonify({"error": "Geçerli bir link gir"}), 400
    s = load_settings()
    opts = Options(
        url=url,
        start=int(data["start"]) if data.get("start") else None,
        end=int(data["end"]) if data.get("end") else None,
        translate=bool(data.get("translate")),
        api_key=s.get("api_key", ""),
        model=s.get("model") or DEFAULT_MODELS,
        delay=float(s.get("delay", 0.7)),
        workers=int(s.get("workers", 3)),
        batch=max(0, min(MAX_AUTO_CHAPTERS, int(s.get("batch", 0)))),
        edit=bool(data.get("edit", True)),
        thinking=s.get("thinking", "medium"),
        temperature=float(s.get("temperature", DEFAULT_TEMPERATURE)),
        review_after=20 if data.get("review") else 0,
        library=LIBRARY,
        output=OUTPUT,
    )
    if opts.translate and not opts.api_key:
        return jsonify({"error": "Çeviri için önce Ayarlar'dan Gemini API anahtarını kaydet"}), 400
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
        "running": p.phase not in ("bitti", "hata", "iptal edildi"),
    })


@app.post("/api/jobs/<job_id>/cancel")
def job_cancel(job_id: str):
    (JOBS.get(job_id) or abort(404)).cancel()
    return jsonify({"ok": True})


def _book(name: str) -> BookStore:
    """Kitaplıktaki bir kitap klasörü (yalnızca var olan klasör adları kabul edilir)."""
    names = {d.name for d in LIBRARY.iterdir() if d.is_dir()} if LIBRARY.exists() else set()
    if name not in names:
        abort(404)
    return BookStore(LIBRARY, dirname=name)


@app.get("/api/library")
def library():
    out = []
    for d in sorted(LIBRARY.glob("*/kitap.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        meta = json.loads(d.read_text("utf-8"))
        st = BookStore(LIBRARY, dirname=d.parent.name)
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
    files = sorted(OUTPUT.glob("*.epub"), key=lambda p: p.stat().st_mtime, reverse=True)
    return jsonify([{"name": f.name, "mb": round(f.stat().st_size / 1e6, 2)} for f in files])


@app.get("/indir/<path:name>")
def download(name: str):
    return send_from_directory(OUTPUT.resolve(), name, as_attachment=True, mimetype="application/epub+zip")


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
    print(f"\n  Novel → EPUB hazır.\n  Bu PC'de:      http://127.0.0.1:{port}")
    if host == "0.0.0.0":
        print(f"  Telefonda (aynı Wi‑Fi): http://{lan_ip()}:{port}\n")
    app.run(host=host, port=port, threaded=True)
