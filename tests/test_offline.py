"""Ağ ve API gerektirmeyen testler: python -m pytest -q"""
import json
import zipfile
from pathlib import Path

from bs4 import BeautifulSoup

from novel_epub.cleaner import check_book, clean_paragraphs, extract_paragraphs
from novel_epub.epub_builder import build_epub
from novel_epub.models import Chapter, Novel
from novel_epub.sources import source_for
from novel_epub.sources.generic import best_content
from novel_epub.translator import GeminiTranslator, chunk_paragraphs, relevant_glossary

PAGE = """<html><body><div class="nav">Home | Library</div>
<div id="article"><p>Chapter 7 - The Gate</p><p>The old man raised his hand.</p>
<div class="reader-ad-skip">ad</div><script>x()</script>
<p>Translated by: someone</p><p>Read latest chapters at freewebnovel.com</p>
<p>"Go," he said, and the gate opened.</p><p>"Go," he said, and the gate opened.</p></div></body></html>"""


def test_extract_and_clean():
    soup = BeautifulSoup(PAGE, "lxml")
    paras = clean_paragraphs(extract_paragraphs(soup.select_one("#article")), "Chapter 7 - The Gate")
    assert paras == ["The old man raised his hand.", '"Go," he said, and the gate opened.']


def test_generic_picks_content():
    soup = BeautifulSoup(PAGE, "lxml")
    assert best_content(soup).get("id") == "article"


def test_source_routing():
    assert source_for("https://freewebnovel.com/novel/x/chapter-3", None).name == "freewebnovel"
    assert source_for("https://novelbin.me/novel-book/x", None).name == "novelbin"
    assert source_for("https://example.org/story", None).name == "genel"


def test_check_book():
    chs = [Chapter(1, "Chapter 1", "u1", ["a" * 400]), Chapter(2, "Chapter 2", "u2", ["a" * 400]),
           Chapter(3, "Chapter 4", "u4", ["kısa"])]
    r = check_book(chs)
    assert r["kopya"] == [(1, 2)]
    assert r["eksik_numaralar"] == [3]
    assert 3 in r["sorunlu"]


def test_chunk_and_glossary():
    assert chunk_paragraphs(["aaaa", "bbbb", "cc"], 6) == [["aaaa"], ["bbbb", "cc"]]
    assert relevant_glossary({"Qi Condensation": "Qi Yoğunlaştırma", "Nascent Soul": "Doğan Ruh"},
                             "he reached qi condensation") == {"Qi Condensation": "Qi Yoğunlaştırma"}


def test_translate_with_fake_model():
    tr = GeminiTranslator.__new__(GeminiTranslator)
    tr.model, tr.target, tr.log, tr.max_retries = "sahte", "Türkçe", print, 1
    seen = []

    def fake_call(payload):
        seen.append(payload)
        return {"title": "Bölüm 7 - Kapı", "paragraphs": [f"TR:{p}" for p in payload["paragraphs"]],
                "new_terms": [{"source": "Gate", "target": "Kapı"}]}

    tr._call = fake_call
    ch = Chapter(7, "Chapter 7 - The Gate", "u", ["p1", "p2"])
    out, terms = tr.translate_chapter(ch, {"old man": "ihtiyar"}, ["önceki"])
    assert out.title == "Bölüm 7 - Kapı" and out.paragraphs == ["TR:p1", "TR:p2"]
    assert terms == {"Gate": "Kapı"} and seen[0]["context"] == ["önceki"]


def test_build_epub(tmp_path: Path):
    novel = Novel(url="https://x/novel/a", title="Deneme", source="t", author="A, B", description="Açıklama")
    out = build_epub(novel, [Chapter(1, "Bölüm 1", "u", ["Merhaba <dünya> & selam"])], tmp_path / "a.epub")
    z = zipfile.ZipFile(out)
    assert z.read("mimetype") == b"application/epub+zip"
    body = z.read("EPUB/b00001.xhtml").decode()
    assert "&lt;dünya&gt; &amp; selam" in body


def test_store_roundtrip(tmp_path: Path):
    from novel_epub.store import BookStore

    st = BookStore(tmp_path, Novel(url="u", title="Ölü Şehir", source="t"))
    st.save_raw(Chapter(3, "t", "u", ["x"]))
    assert st.load_raw(3).paragraphs == ["x"] and st.dir.name == "t-olu-sehir"
    st.save_glossary({"b": "2", "A": "1"})
    assert list(json.loads(st.glossary_path.read_text("utf-8"))) == ["A", "b"]


def test_daily_quota_detection():
    from novel_epub.translator import is_daily_quota, parse_models

    daily = ("429 RESOURCE_EXHAUSTED. {'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier', "
             "'retryDelay': '27476s'}")
    assert is_daily_quota(Exception(daily))
    assert not is_daily_quota(Exception("429 RESOURCE_EXHAUSTED. {'retryDelay': '12s'}"))
    assert is_daily_quota(Exception("429 {'retryDelay': '27476s'}"))
    assert parse_models("a, b,,a") == ["a", "b"]


def test_model_fallback_on_quota():
    from novel_epub.translator import QuotaExhausted

    tr = GeminiTranslator.__new__(GeminiTranslator)
    tr.models, tr.model, tr.log = ["m1", "m2"], "m1", print
    used = []

    def fake_model_call(payload, schema=None, bad_retries=None):
        used.append(tr.model)
        if tr.model == "m1":
            raise QuotaExhausted("dolu")
        return {"title": "t", "paragraphs": payload["paragraphs"], "new_terms": []}

    tr._call_model = fake_model_call
    assert tr._call({"paragraphs": ["x"]})["paragraphs"] == ["x"]
    assert used == ["m1", "m2"] and tr.model == "m2"


def test_partial_epub_when_quota_runs_out(tmp_path: Path, monkeypatch):
    from novel_epub import pipeline, translator
    from novel_epub.store import BookStore

    class FakeTr:
        def __init__(self, *a, **k):
            self.model, self.n = "sahte", 0

        def batch_limit(self, ch):
            return 10**6

        def translate_batch(self, chs, glossary, context):
            self.n += 1
            if self.n > 1:
                raise translator.QuotaExhausted("kota doldu")
            return [Chapter(c.index, "TR " + c.title, c.url, ["tr"]) for c in chs], {}

    monkeypatch.setattr(translator, "GeminiTranslator", FakeTr)
    job = pipeline.Job(pipeline.Options(url="u", translate=True, batch=2))
    store = BookStore(tmp_path, Novel(url="u", title="k", source="t"))
    chs = [Chapter(i, f"c{i}", "u", ["en"]) for i in range(1, 6)]
    out = job._translate(chs, store)
    assert [c.title for c in out] == ["TR c1", "TR c2"] and job.p.error.startswith("Kısmi")


def _fake_translator():
    tr = GeminiTranslator.__new__(GeminiTranslator)
    tr.models, tr.model, tr.target, tr.log, tr.max_retries, tr.thinking = ["m"], "m", "Türkçe", print, 1, False
    return tr


def test_batch_translation_one_request():
    tr = _fake_translator()
    calls = []

    def fake(payload, schema=None, bad_retries=None):
        calls.append(payload)
        return {"chapters": [{"title": "T" + c["chapter_title"], "paragraphs": [p.upper() for p in c["paragraphs"]]}
                             for c in payload["chapters"]], "new_terms": [{"source": "Qi", "target": "Qi"}]}

    tr._call_model = fake
    chs = [Chapter(i, str(i), "u", ["abc"]) for i in (1, 2, 3)]
    outs, terms = tr.translate_batch(chs, {}, [])
    assert len(calls) == 1 and [o.title for o in outs] == ["T1", "T2", "T3"] and outs[0].paragraphs == ["ABC"]
    assert terms == {"Qi": "Qi"}


def test_batch_falls_back_to_single_on_short_answer():
    tr = _fake_translator()

    def fake(payload, schema=None, bad_retries=None):
        if "chapters" in payload:  # model bir bölümü atladı
            return {"chapters": [{"title": "x", "paragraphs": ["abc"]}], "new_terms": []}
        return {"title": "tek", "paragraphs": payload["paragraphs"], "new_terms": []}

    tr._call_model = fake
    outs, _ = tr.translate_batch([Chapter(1, "1", "u", ["abc"]), Chapter(2, "2", "u", ["def"])], {}, [])
    assert [o.title for o in outs] == ["tek", "tek"]


def test_unknown_model_is_skipped():
    from novel_epub.translator import ModelUnusable

    tr = _fake_translator()
    tr.models, tr.model = ["yok", "var"], "yok"

    def fake(payload, schema=None, bad_retries=None):
        if tr.model == "yok":
            raise ModelUnusable("404")
        return {"title": "t", "paragraphs": payload["paragraphs"], "new_terms": []}

    tr._call_model = fake
    assert tr._call({"paragraphs": ["x"]})["paragraphs"] == ["x"] and tr.model == "var"
