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
    soup = BeautifulSoup(PAGE, "html.parser")
    paras = clean_paragraphs(extract_paragraphs(soup.select_one("#article")), "Chapter 7 - The Gate")
    assert paras == ["The old man raised his hand.", '"Go," he said, and the gate opened.']


def test_generic_picks_content():
    soup = BeautifulSoup(PAGE, "html.parser")
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
    tr._init_state("sahte", max_retries=1)
    seen = []

    def fake_call(payload, *a, **k):
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
    assert parse_models("a, b,,a") == ["gemini/a", "gemini/b"]
    assert parse_models("openai/gpt-5, gemini/x") == ["openai/gpt-5", "gemini/x"]


def test_model_fallback_on_quota():
    from novel_epub.translator import QuotaExhausted

    tr = GeminiTranslator.__new__(GeminiTranslator)
    tr._init_state("m1, m2")
    used = []

    def fake_model_call(payload, schema=None, bad_retries=None, system=None):
        used.append(tr.model)
        if tr.model == "gemini/m1":
            raise QuotaExhausted("dolu")
        return {"title": "t", "paragraphs": payload["paragraphs"], "new_terms": []}

    tr._call_model = fake_model_call
    assert tr._call({"paragraphs": ["x"]})["paragraphs"] == ["x"]
    assert used == ["gemini/m1", "gemini/m2"] and tr.model == "gemini/m2"


def test_exhausted_best_model_is_retried_after_an_hour():
    from novel_epub.translator import QuotaExhausted

    tr = GeminiTranslator.__new__(GeminiTranslator)
    tr._init_state("iyi, orta, kotu", log=lambda m: None)
    now = [1000.0]
    tr.clock = lambda: now[0]
    full = {"gemini/iyi"}

    def fake(payload, schema=None, bad_retries=None, system=None):
        if tr.model in full:
            raise QuotaExhausted("dolu")
        return {"title": "t", "paragraphs": [tr.model.split("/")[1]], "new_terms": []}

    tr._call_model = fake
    assert tr._call({"paragraphs": ["x"]})["paragraphs"] == ["orta"]
    now[0] += 1800  # yarım saat: iyi model hâlâ dışarıda
    assert tr._call({"paragraphs": ["x"]})["paragraphs"] == ["orta"]
    full.clear()  # kota yenilendi
    now[0] += 1900
    assert tr._call({"paragraphs": ["x"]})["paragraphs"] == ["iyi"]
    assert tr.models == ["gemini/iyi", "gemini/orta", "gemini/kotu"]


def test_partial_epub_when_quota_runs_out(tmp_path: Path, monkeypatch):
    from novel_epub import pipeline, translator
    from novel_epub.store import BookStore

    class FakeTr:
        def __init__(self, *a, **k):
            self.model, self.n = "sahte", 0

        def plan_batch(self, pending, cap):
            return pending[:cap]

        def translate_batch(self, chs, glossary, context, lookahead=None):
            self.n += 1
            if self.n > 1:
                raise translator.QuotaExhausted("kota doldu")
            return [Chapter(c.index, "TR " + c.title, c.url, ["tr"]) for c in chs], {}

    monkeypatch.setattr(translator, "GeminiTranslator", FakeTr)
    job = pipeline.Job(pipeline.Options(url="u", translate=True, batch=2, edit=False))
    store = BookStore(tmp_path, Novel(url="u", title="k", source="t"))
    chs = [Chapter(i, f"c{i}", "u", ["en"]) for i in range(1, 6)]
    out = job._translate(chs, store)
    assert [c.title for c in out] == ["TR c1", "TR c2"] and job.p.error.startswith("Kısmi")


def _fake_translator():
    tr = GeminiTranslator.__new__(GeminiTranslator)
    tr._init_state("m", max_retries=1)
    tr.thinking = False
    return tr


def test_batch_translation_one_request():
    tr = _fake_translator()
    calls = []

    def fake(payload, schema=None, bad_retries=None, system=None):
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

    def fake(payload, schema=None, bad_retries=None, system=None):
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

    def fake(payload, schema=None, bad_retries=None, system=None):
        if tr.model == "yok":
            raise ModelUnusable("404")
        return {"title": "t", "paragraphs": payload["paragraphs"], "new_terms": []}

    tr._call_model = fake
    assert tr._call({"paragraphs": ["x"]})["paragraphs"] == ["x"] and tr.model == "var"


def test_auto_batch_by_word_count():
    tr = _fake_translator()
    long_ch = lambda i, words: Chapter(i, str(i), "u", [" ".join(["kelime"] * words)])
    # ~2.000 kelimelik bölümler: 24k bütçe / (2.000 × 2.0) ≈ 5 bölüm
    group = tr.plan_batch([long_ch(i, 2000) for i in range(1, 20)])
    assert 5 <= len(group) <= 6
    # Çok uzun bölümler (6.000 kelime) → daha az bölüm; tavan 2 verilirse 2'yi geçmez
    assert len(tr.plan_batch([long_ch(i, 6000) for i in range(1, 9)])) <= 3
    assert len(tr.plan_batch([long_ch(i, 100) for i in range(1, 30)], 2)) == 2
    # Ardışık olmayan bölümler aynı pakete girmez
    assert len(tr.plan_batch([long_ch(1, 100), long_ch(5, 100)])) == 1


def test_learning_adjusts_budget_and_ratio():
    tr = _fake_translator()
    chs = [Chapter(1, "1", "u", [" ".join(["w"] * 1000)])]
    tr.last_usage = (3000, 500)  # gerçek: kelime başına 3 token
    tr.learn(chs, ok=True)
    assert tr.ratio["latin"] > 2.0 and tr.budget > 24000
    b = tr.budget
    tr.learn(chs, ok=False)
    assert tr.budget < b


class _Resp:
    """LiteLLM ModelResponse benzeri."""

    def __init__(self, text, finish="stop", usage=None):
        msg = type("M", (), {"content": text})()
        self.choices = [type("C", (), {"message": msg, "finish_reason": finish})()]
        self.usage = usage


def _client(behaviour):
    """behaviour(model, n) → yanıt metni ya da fırlatılacak istisna; sahte litellm.completion döner."""
    calls = []

    def complete(model, messages, **kw):
        calls.append(model)
        r = behaviour(model, len(calls))
        if isinstance(r, Exception):
            raise r
        return _Resp(r)

    return complete, calls


def test_network_error_waits_max_60s_and_retries():
    tr = _fake_translator()
    waits = []
    tr.sleep, tr.max_retries = waits.append, 10
    ok = json.dumps({"title": "t", "paragraphs": ["x"], "new_terms": []})
    tr.complete, calls = _client(lambda m, n: ConnectionError("koptu") if n <= 6 else ok)
    assert tr._call({"paragraphs": ["x"]})["paragraphs"] == ["x"]
    assert len(calls) == 7 and max(waits) == 60 and waits[:3] == [10, 20, 40]


def test_persistent_error_moves_request_to_next_model():
    tr = _fake_translator()
    tr.models, tr.sleep, tr.max_retries = ["a", "b"], lambda s: None, 2
    ok = json.dumps({"title": "t", "paragraphs": ["x"], "new_terms": []})
    tr.complete, calls = _client(lambda m, n: TimeoutError() if m == "a" else ok)
    assert tr._call({"paragraphs": ["x"]})["paragraphs"] == ["x"]
    assert calls == ["a", "a", "a", "b"]
    assert tr.models == ["a", "b"]  # geçici hata modeli listeden atmaz; sonraki istek yine "a" ile başlar


def test_pipeline_skips_failed_group_and_continues(tmp_path: Path, monkeypatch):
    from novel_epub import pipeline, translator
    from novel_epub.store import BookStore

    class FakeTr:
        def __init__(self, *a, **k):
            self.model = "sahte"

        def plan_batch(self, pending, cap):
            return pending[:1]

        def translate_batch(self, chs, glossary, context, lookahead=None):
            if chs[0].index == 2:
                raise translator.TransientFailure("hep hata")
            return [Chapter(c.index, "TR", c.url, ["tr"]) for c in chs], {}

        def translate_chapter(self, ch, glossary, context, lookahead=None):
            if ch.index == 2 and self.always_fail:
                raise translator.TransientFailure("yine hata")
            return Chapter(ch.index, "TR2", ch.url, ["tr"]), {}

    FakeTr.always_fail = True
    monkeypatch.setattr(translator, "GeminiTranslator", FakeTr)
    job = pipeline.Job(pipeline.Options(url="u", translate=True, edit=False))
    store = BookStore(tmp_path, Novel(url="u", title="k", source="t"))
    out = job._translate([Chapter(i, f"c{i}", "u", ["en"]) for i in range(1, 5)], store)
    assert [c.title for c in out] == ["TR", "[Çevrilemedi] c2", "TR", "TR"]
    assert job.p.report["cevrilemeyen"] == [2] and not job.p.error and "1 bölüm çevrilemedi" in job.p.notice
    # İkinci denemede olursa EPUB'da boşluk kalmaz
    FakeTr.always_fail = False
    job = pipeline.Job(pipeline.Options(url="u", translate=True, edit=False))
    store = BookStore(tmp_path / "b", Novel(url="u", title="k", source="t"))
    out = job._translate([Chapter(i, f"c{i}", "u", ["en"]) for i in range(1, 5)], store)
    assert [c.title for c in out] == ["TR", "TR2", "TR", "TR"] and "cevrilemeyen" not in job.p.report


def test_untranslated_paragraphs_are_detected_and_repaired():
    from novel_epub.translator import untranslated_paragraphs

    src = ["Even the deputy dean said that they would come with him.", "The wind howled through the valley and the trees.",
           "Kai.", "第一章 风起"]
    out = ["Dekan yardımcısı bile onların geleceğini söyledi.", "Even the deputy dean said that they would come with him.",
           "Kai.", "The wind was howling and they could hear it from there."]
    assert untranslated_paragraphs(src[:3], out, "tr") == [1, 3]
    assert untranslated_paragraphs(src[:3], out, "en") == []  # hedef İngilizceyse sorun yok
    assert untranslated_paragraphs(["他说：我们走吧。今天天气很好。"], ["他说：我们走吧。今天天气很好。"], "tr") == [0]
    # Türkçe metindeki "her/his/in" kelimeleri yanlış alarm vermez
    assert untranslated_paragraphs(src, ["Her gün onun için bir his vardı ve in cin top oynuyordu orada."], "tr") == []
    # Kaynakla aynı kısa ad/sayı satırları çevrilmeden kalabilir; kısa ama cümle olanlar yakalanır
    short = ["Lorem Ipsum Dolor Sit", "[Bonus: +1,020 Credits]", "He was not there."]
    assert untranslated_paragraphs(short, ["Lorem Ipsum Dolor Sit", "[Bonus: +1,020 Credits]", "He was not there."], "tr") == [2]

    tr = _fake_translator()
    tr.log = lambda m: None
    sent = []

    def fake(payload, schema=None, bad_retries=None, system=None):
        sent.append(payload["paragraphs"])
        return {"title": "", "paragraphs": ["ÇEVRİLDİ " + str(k) for k in range(len(payload["paragraphs"]))], "new_terms": []}

    tr._call_model = fake
    fixed = tr.repair(Chapter(1, "c", "u", src[:3]), Chapter(1, "B", "u", out, edited=True), {})
    assert sent == [[out[1], out[3]]]  # yalnız sorunlu paragraflar gider
    assert fixed.paragraphs == [out[0], "ÇEVRİLDİ 0", "Kai.", "ÇEVRİLDİ 1"] and fixed.edited


def test_pipeline_repairs_old_translations_on_start(tmp_path: Path, monkeypatch):
    from novel_epub import pipeline, translator
    from novel_epub.store import BookStore

    eng = "He opened the gate and they said that the wind would come from there."

    class FakeTr:
        def __init__(self, *a, **k):
            self.model = "sahte"

        def repair(self, src, out, glossary):
            return Chapter(out.index, out.title, out.url, ["onarıldı"], edited=out.edited)

    monkeypatch.setattr(translator, "GeminiTranslator", FakeTr)
    store = BookStore(tmp_path, Novel(url="u", title="k", source="t"))
    store.save_tr(Chapter(1, "B1", "u", ["Kapıyı açtı."], edited=True))
    store.save_tr(Chapter(2, "B2", "u", [eng], edited=True))  # yarım kalmış çeviri
    job = pipeline.Job(pipeline.Options(url="u", translate=True, edit=True))
    out = job._translate([Chapter(1, "c1", "u", [eng.replace("He", "She")]), Chapter(2, "c2", "u", [eng])], store)
    assert [c.paragraphs for c in out] == [["Kapıyı açtı."], ["onarıldı"]] and store.load_tr(2).paragraphs == ["onarıldı"]


def test_cancel_interrupts_wait(tmp_path: Path, monkeypatch):
    import pytest
    from novel_epub import pipeline, translator
    from novel_epub.store import BookStore

    job = pipeline.Job(pipeline.Options(url="u", translate=True))

    class FakeTr:
        def __init__(self, *a, **k):
            self.model = "sahte"

        def plan_batch(self, pending, cap):
            return pending[:1]

        def translate_batch(self, chs, glossary, context, lookahead=None):
            job.cancel()
            self.sleep(60)  # iptal edildiği için hemen dönmeli

    monkeypatch.setattr(translator, "GeminiTranslator", FakeTr)
    store = BookStore(tmp_path, Novel(url="u", title="k", source="t"))
    with pytest.raises(pipeline.Cancelled):
        job._translate([Chapter(1, "c", "u", ["en"])], store)



def test_memory_goes_into_payload_and_updates():
    tr = _fake_translator()
    tr.memory = {"summary": "Qin Yu yola çıktı.", "characters": {"Qin Yu": "ana karakter", "Lin Mengmeng": "x"}}
    seen = []

    def fake(payload, schema=None, bad_retries=None, system=None):
        seen.append(payload)
        return {"title": "t", "paragraphs": payload["paragraphs"], "new_terms": [],
                "story_summary": "Qin Yu şehre vardı.", "character_notes": [{"name": "Hou Fei", "note": "maymun"}]}

    tr._call_model = fake
    tr.translate_chapter(Chapter(1, "c", "u", ["Qin Yu walked."]), {}, [])
    assert seen[0]["story_so_far"] == "Qin Yu yola çıktı." and list(seen[0]["characters"]) == ["Qin Yu"]
    assert tr.memory["summary"] == "Qin Yu şehre vardı." and tr.memory["characters"]["Hou Fei"] == "maymun"


def test_edit_batch_keeps_draft_when_editor_shortens():
    from novel_epub.translator import EDIT_PROMPT

    tr = _fake_translator()
    systems = []

    def fake(payload, schema=None, bad_retries=None, system=None):
        systems.append(system)
        a, b = payload["chapters"]
        return {"chapters": [{"title": "Düzeltilmiş", "paragraphs": [p + "!" for p in a["draft"]]},
                             {"title": "kısa", "paragraphs": ["x"]}]}

    tr._call_model = fake
    src = [Chapter(1, "a", "u", ["en1", "en2"]), Chapter(2, "b", "u", ["en3", "en4"])]
    drafts = [Chapter(1, "A", "u", ["taslak bir", "taslak iki"]), Chapter(2, "B", "u", ["taslak üç", "taslak dört"])]
    out = tr.edit_batch(src, drafts, {})
    assert systems == [EDIT_PROMPT]
    assert out[0].edited and out[0].paragraphs == ["taslak bir!", "taslak iki!"]
    assert not out[1].edited and out[1].paragraphs == drafts[1].paragraphs


def test_pipeline_edits_and_pauses_for_review(tmp_path: Path, monkeypatch):
    from novel_epub import pipeline, translator
    from novel_epub.store import BookStore

    class FakeTr:
        def __init__(self, *a, **k):
            self.model, self.memory = "sahte", {"summary": "", "characters": {}}

        def plan_batch(self, pending, cap):
            return pending[:2]

        def translate_batch(self, chs, glossary, context, lookahead=None):
            self.memory["summary"] = f"{chs[-1].index}. bölüme kadar"
            return [Chapter(c.index, "TR", c.url, ["tr"]) for c in chs], {}

        def edit_batch(self, sources, drafts, glossary, context=None):
            return [Chapter(d.index, "RED", d.url, d.paragraphs, edited=True) for d in drafts]

    monkeypatch.setattr(translator, "GeminiTranslator", FakeTr)
    job = pipeline.Job(pipeline.Options(url="u", translate=True, review_after=4))
    store = BookStore(tmp_path, Novel(url="u", title="k", source="t"))
    out = job._translate([Chapter(i, f"c{i}", "u", ["en"]) for i in range(1, 9)], store)
    assert [c.title for c in out] == ["RED"] * 4 and all(c.edited for c in out)
    assert "İlk 4 bölüm" in job.p.notice and store.load_memory()["summary"] == "4. bölüme kadar"
    assert store.counts() == {"ham": 0, "ceviri": 4, "redakte": 4, "yedek": 0}


def test_fancy_unicode_watermark_and_end_notes_removed():
    paras = ["Qin Yu smiled. 𝐟𝗿𝐞𝚎𝚠𝐞𝚋𝕟𝐨𝚟𝐞𝕝.𝕔𝕠𝚖 He left.", "𝐟𝗿𝐞𝚎𝚠𝐞𝚋𝕟𝐨𝚟𝐞𝕝.𝕔𝕠𝚖", "End of b1c7",
             "The free web of the novel was vast."]
    assert clean_paragraphs(paras) == ["Qin Yu smiled. He left.", "The free web of the novel was vast."]


def test_retranslate_backs_up_and_restore_swaps(tmp_path: Path):
    from novel_epub.store import BookStore

    st = BookStore(tmp_path, Novel(url="u", title="k", source="t"))
    st.save_tr(Chapter(5, "eski", "u", ["e"]))
    assert st.drop_tr(5) and st.load_tr(5) is None and st.backup_count() == 1
    st.save_tr(Chapter(5, "yeni", "u", ["y"]))
    assert st.restore_tr(5) and st.load_tr(5).title == "eski"
    assert st.restore_tr(5) and st.load_tr(5).title == "yeni"  # yer değiştirir; hiçbir sürüm kaybolmaz
    assert not st.restore_tr(6)


def test_lookahead_and_notes_and_temperature():
    from novel_epub.translator import EDIT_PROMPT, SYSTEM_PROMPT

    tr = _fake_translator()
    tr.thinking, tr.book_notes = False, "Big brother → Ağabey"
    seen = []

    def fake(payload, schema=None, bad_retries=None, system=None):
        seen.append(payload)
        return {"title": "t", "paragraphs": payload["paragraphs"], "new_terms": []}

    tr._call_model = fake
    tr.translate_batch([Chapter(1, "c", "u", ["a"])], {}, [], ["next p1", "next p2"])
    assert seen[0]["next_context"] == ["next p1", "next p2"]
    cfg = tr._config(RESPONSE_SCHEMA_FOR_TEST(), SYSTEM_PROMPT)
    assert cfg["temperature"] == 0.7 and "Big brother → Ağabey" in cfg["system"]
    assert tr._config(RESPONSE_SCHEMA_FOR_TEST(), EDIT_PROMPT)["temperature"] == 0.5


def RESPONSE_SCHEMA_FOR_TEST():
    from novel_epub.translator import RESPONSE_SCHEMA

    return RESPONSE_SCHEMA


def test_pipeline_sends_next_chapter_start(tmp_path: Path, monkeypatch):
    from novel_epub import pipeline, translator
    from novel_epub.store import BookStore

    got = []

    class FakeTr:
        def __init__(self, *a, **k):
            self.model, self.memory = "sahte", {}

        def plan_batch(self, pending, cap):
            return pending[:2]

        def translate_batch(self, chs, glossary, context, lookahead=None):
            got.append(lookahead)
            return [Chapter(c.index, "TR", c.url, ["tr"]) for c in chs], {}

    monkeypatch.setattr(translator, "GeminiTranslator", FakeTr)
    job = pipeline.Job(pipeline.Options(url="u", translate=True, edit=False))
    store = BookStore(tmp_path, Novel(url="u", title="k", source="t"))
    job._translate([Chapter(i, f"c{i}", "u", [f"p{i}a", f"p{i}b", f"p{i}c", f"p{i}d"]) for i in range(1, 5)], store)
    assert got == [["p3a", "p3b", "p3c"], []]


def test_api_key_moves_from_file_to_keyring(tmp_path: Path, monkeypatch):
    from novel_epub import web

    class FakeKR:
        store = {}

        def set_password(self, s, u, p):
            self.store[(s, u)] = p

        def get_password(self, s, u):
            return self.store.get((s, u))

    kr = FakeKR()
    monkeypatch.setattr(web, "SETTINGS_PATH", tmp_path / "ayarlar.json")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    (tmp_path / "ayarlar.json").write_text(json.dumps({"api_key": "AIzaGIZLI", "model": "m"}), "utf-8")
    monkeypatch.setattr(web, "_keyring", lambda: kr)
    s = web.load_settings()
    assert s["api_key"] == "AIzaGIZLI" and s["key_store"] == "kasa" and s["keys"] == {"gemini": "AIzaGIZLI"}
    assert s["models"] == ["gemini/m"]  # eski "model" metni LiteLLM adına taşındı
    assert "AIzaGIZLI" not in (tmp_path / "ayarlar.json").read_text("utf-8")
    web.save_settings(s, {"gemini": "AIzaYENI"})
    assert kr.get_password(web.KEYRING_SERVICE, "gemini_api_key") == "AIzaYENI"  # eski sürümle aynı kasa adı
    assert "AIza" not in (tmp_path / "ayarlar.json").read_text("utf-8")
    # Kasa yoksa dosyaya düşer
    monkeypatch.setattr(web, "_keyring", lambda: None)
    web.save_settings({"models": ["gemini/m"], "key_store": "dosya", "keys": {"gemini": "AIzaDOSYA"}})
    assert web.load_settings()["api_key"] == "AIzaDOSYA"


FAKE_OPENAI = "sk-proj-" + "TEST" * 10  # uydurma anahtar biçimi


def test_add_key_detects_provider_and_preselects_best_models(tmp_path: Path, monkeypatch):
    from novel_epub import providers, web

    monkeypatch.setattr(web, "SETTINGS_PATH", tmp_path / "ayarlar.json")
    monkeypatch.setattr(web, "_keyring", lambda: None)
    for env in providers.ENV_KEYS.values():
        monkeypatch.delenv(env, raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    (tmp_path / "ayarlar.json").write_text(json.dumps({"models": []}), "utf-8")
    models = ["gpt-4o-mini", "gpt-5", "text-embedding-3-large", "gpt-5-nano", "gpt-4.1", "whisper-1", "gpt-5-mini",
              "gpt-4o", "o4-mini"]

    def fake_get(url, headers):
        if "openai.com" in url and headers.get("Authorization") == "Bearer " + FAKE_OPENAI:
            return 200, {"data": [{"id": m} for m in models]}
        return 401, {}

    monkeypatch.setattr(providers, "_http_get", fake_get)
    c = web.app.test_client()
    r = c.post("/api/keys", json={"key": FAKE_OPENAI}).get_json()
    assert r["provider"] == "openai"
    avail = r["providers"][0]["available"]
    assert "openai/text-embedding-3-large" not in avail and "openai/whisper-1" not in avail
    assert r["models"][0] == "openai/gpt-5" and len(r["models"]) == 5
    # Kullanıcı sırasız seçer; sıra otomatik en iyiden kötüye
    r = c.post("/api/models", json={"models": ["openai/gpt-5-nano", "openai/gpt-5", "openai/yok"]}).get_json()
    assert r["models"] == ["openai/gpt-5", "openai/gpt-5-nano"]
    assert c.post("/api/keys", json={"key": "tanimsiz"}).status_code == 400
    r = c.delete("/api/keys/openai").get_json()
    assert r["models"] == [] and r["providers"] == []


def test_provider_guess_and_rank():
    from novel_epub.providers import guess, rank

    assert [p.id for p in guess("AIza" + "X" * 35)] == ["gemini"]
    assert [p.id for p in guess("AQ." + "Y" * 30)] == ["gemini"]
    assert [p.id for p in guess("sk-ant-" + "Z" * 30)] == ["anthropic"]
    assert [p.id for p in guess("sk-or-" + "Z" * 30)] == ["openrouter"]
    assert [p.id for p in guess("gsk_" + "Z" * 30)] == ["groq"]
    assert len(guess("bilinmeyen-bicim")) > 3  # tanınmayan biçim: hepsi denenir
    g = ["gemini/gemini-3.1-flash-lite", "gemini/gemini-3.8-flash", "gemini/gemini-4-hydrogen",
         "gemini/gemini-3.5-flash-lite", "gemini/gemini-4-argon"]
    assert rank(g) == ["gemini/gemini-4-argon", "gemini/gemini-4-hydrogen", "gemini/gemini-3.8-flash",
                       "gemini/gemini-3.5-flash-lite", "gemini/gemini-3.1-flash-lite"]
    a = ["anthropic/claude-haiku-4-5", "anthropic/claude-opus-4-5", "anthropic/claude-sonnet-4-5"]
    assert rank(a) == ["anthropic/claude-opus-4-5", "anthropic/claude-sonnet-4-5", "anthropic/claude-haiku-4-5"]


def _err(name, code, msg=""):
    return type(name, (Exception,), {"status_code": code})(msg)


def test_litellm_errors_map_to_actions():
    from novel_epub.translator import ModelUnusable, QuotaExhausted, _classify

    assert _classify(_err("AuthenticationError", 401)) == "auth"
    assert _classify(_err("BadRequestError", 400, "API key not valid. Please pass a valid API key.")) == "auth"
    assert _classify(_err("NotFoundError", 404)) == "missing"
    assert _classify(_err("RateLimitError", 429, "Quota exceeded ... PerDay")) == "quota"
    assert _classify(_err("RateLimitError", 429, "try again in 3s")) == "busy"
    assert _classify(_err("RateLimitError", 429, "You exceeded your current quota: insufficient_quota")) == "quota"
    assert _classify(_err("ServiceUnavailableError", 503)) == "busy"
    assert _classify(ConnectionError("koptu")) == "net"

    tr = _fake_translator()
    tr._init_state("openai/gpt-5, gemini/g", log=lambda m: None)
    tr.keys, tr.sleep = {"openai": "o-test", "gemini": "g-test"}, lambda s: None

    def complete(model, messages, **kw):
        if model.startswith("openai/"):
            raise _err("AuthenticationError", 401, "Incorrect API key provided")
        assert kw["api_key"] == "g-test"
        return _Resp('```json\n{"title": "t", "paragraphs": ["ok"], "new_terms": []}\n```')

    tr.complete = complete
    assert tr._call({"paragraphs": ["x"]})["paragraphs"] == ["ok"]  # kod bloğu içindeki JSON da okunur
    assert tr.all_models == ["gemini/g"]  # anahtarı geçersiz sağlayıcı zincirden çıktı
    assert issubclass(ModelUnusable, QuotaExhausted)


def test_schema_falls_back_to_prompt_when_unsupported(monkeypatch):
    import novel_epub.translator as T

    tr = _fake_translator()
    tr._init_state("deepseek/deepseek-chat", log=lambda m: None)
    tr.keys, tr.sleep = {"deepseek": "d-test"}, lambda s: None
    seen = []

    def complete(model, messages, **kw):
        seen.append(kw["response_format"]["type"])
        if kw["response_format"]["type"] == "json_schema":
            raise _err("BadRequestError", 400, "response_format json_schema unsupported")
        assert "JSON şemasına" in messages[0]["content"]
        return _Resp('{"title": "t", "paragraphs": ["ok"], "new_terms": []}')

    tr.complete = complete
    monkeypatch.setattr(T, "_supports", lambda model, fn, default=False: fn == "supports_response_schema")
    assert tr._call({"paragraphs": ["x"]})["paragraphs"] == ["ok"]
    assert seen == ["json_schema", "json_object"]


def test_name_matching_aliases_without_false_positives():
    from novel_epub.translator import mentions

    assert mentions("Hou Fei (Fei Fei)", "then fei fei laughed")
    assert mentions("Üçüncü Prens Qin Yu", "qin yu walked in")
    assert not mentions("Hou Fei", "the house was quiet for an hour")
    assert mentions("秦羽", "秦羽说")


def test_address_forms_are_sticky_and_sent_when_both_present():
    tr = _fake_translator()
    tr.absorb_memory({"address_forms": [{"speaker": "Qin Yu", "listener": "Hou Fei", "form": "sen"},
                                        {"speaker": "Guard", "listener": "Qin Yu", "form": "siz"}]})
    tr.absorb_memory({"address_forms": [{"speaker": "Qin Yu", "listener": "Hou Fei", "form": "siz"}]})
    assert tr.memory["address"]["Qin Yu → Hou Fei"] == "sen"  # ilk kayıt kalıcı
    ctx = tr.memory_context("Qin Yu told Hou Fei to wait.")
    assert ctx["address_forms"] == {"Qin Yu → Hou Fei": "sen"}


def test_untranslated_suspects():
    from novel_epub.translator import untranslated_suspects

    src = ["Qin Yu enters an ethereal state and goes berserk at the Azure Dragon Palace."]
    draft = ["Qin Yu ethereal bir duruma girdi ve Azure Ejderha Sarayı'nda berserk oldu, dantian titredi."]
    assert untranslated_suspects(src, draft, {"dantian": "dantian"}) == ["berserk", "ethereal"]


def test_end_notes_and_lone_dot_removed_but_scene_breaks_kept():
    from novel_epub.cleaner import clean_output_paragraphs

    src = ["He left.", ".", "End of c1b13", "C6B2", "***", "...", "Next chapter"]
    assert clean_paragraphs(src) == ["He left.", "***", "..."]
    out = ["Gitti.", "C6B2'nin sonu.", "C1B13 Sonu", ".", "* * *", "...", "Bölüm sonu."]
    assert clean_output_paragraphs(out) == ["Gitti.", "* * *", "..."]


def test_edit_batch_gets_context_and_suspects():
    tr = _fake_translator()
    seen = []

    def fake(payload, schema=None, bad_retries=None, system=None):
        seen.append(payload)
        return {"chapters": [{"title": "t", "paragraphs": c["draft"]} for c in payload["chapters"]]}

    tr._call_model = fake
    tr.edit_batch([Chapter(1, "a", "u", ["he went berserk"])], [Chapter(1, "A", "u", ["berserk oldu"])], {},
                  ["önceki paragraf"])
    assert seen[0]["context"] == ["önceki paragraf"]
    assert seen[0]["chapters"][0]["possibly_untranslated"] == ["berserk"]


def test_data_home_portable_or_documents(tmp_path: Path, monkeypatch):
    from novel_epub import app

    monkeypatch.delenv("NOVEL_EPUB_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(app, "_documents_dir", lambda: tmp_path / "Belgeler")
    assert app.data_home() == tmp_path / "Belgeler" / "WebNovel Downloader & Translator"
    (tmp_path / "Belgeler" / "Novel EPUB").mkdir(parents=True)  # eski sürümün verisi varsa o kullanılır
    assert app.data_home() == tmp_path / "Belgeler" / "Novel EPUB"
    (tmp_path / "kutuphane").mkdir()  # eski kurulum klasöründen açıldıysa orası kullanılır
    assert app.data_home() == tmp_path


def test_open_folder_only_from_this_pc(monkeypatch):
    from novel_epub import web

    opened = []
    monkeypatch.setattr(web.subprocess, "Popen", lambda args: opened.append(args))
    monkeypatch.setattr(web.os, "startfile", lambda p: opened.append(p), raising=False)
    c = web.app.test_client()
    assert c.post("/api/open-folder", json={}, environ_base={"REMOTE_ADDR": "192.168.1.50"}).status_code == 403
    assert c.post("/api/open-folder", json={}).status_code == 200 and opened
    info = c.get("/api/info", environ_base={"REMOTE_ADDR": "192.168.1.50"}).get_json()
    assert info["local"] is False and info["home"] == ""


def _lorem(n: int, seed: str) -> list[str]:
    return [f"{seed} paragraph {i}: the lantern swayed while Arin counted the steps to the mill." for i in range(n)]


def _write_docx(path: Path, title: str, sections: list) -> None:
    """Word'ün yazdığı yapıda küçük bir .docx: Başlık 1 stili kimliği "Heading1", adı "heading 1"."""
    from xml.sax.saxutils import escape

    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    paras = ""
    for head, body in sections:
        paras += f'<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>{escape(head)}</w:t></w:r></w:p>'
        paras += "".join(f"<w:p><w:r><w:t>{escape(t)}</w:t></w:r></w:p>" for t in body)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f"<w:document {w}><w:body>{paras}</w:body></w:document>")
        z.writestr("word/styles.xml", f'<w:styles {w}><w:style w:styleId="Heading1"><w:name w:val="heading 1"/></w:style></w:styles>')
        z.writestr("docProps/core.xml", '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                   f'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{escape(title)}</dc:title></cp:coreProperties>')


def test_files_txt_docx_epub_split_into_chapters(tmp_path: Path):
    from novel_epub.files import load_file

    (tmp_path / "a.txt").write_text("\n\n".join(["Chapter 1: Start", *_lorem(3, "a"), "Chapter 2: Mill", *_lorem(2, "b")]), "utf-8")
    n, chs, _ = load_file(tmp_path / "a.txt")
    assert [(c.title, len(c.paragraphs)) for c in chs] == [("Chapter 1: Start", 3), ("Chapter 2: Mill", 2)]

    _write_docx(tmp_path / "b.docx", "Belge", [("Ön Söz", _lorem(2, "x")), ("Asıl Kısım", _lorem(2, "y"))])
    n, chs, _ = load_file(tmp_path / "b.docx")
    assert n.title == "Belge" and [c.title for c in chs] == ["Ön Söz", "Asıl Kısım"]

    build_epub(Novel(url="x", title="Kitap E", source="t", author="Yazar"),
               [Chapter(1, "One", "u", _lorem(3, "c")), Chapter(2, "Two", "u", _lorem(2, "d"))], tmp_path / "c.epub")
    n, chs, _ = load_file(tmp_path / "c.epub")
    assert n.title == "Kitap E" and n.author == "Yazar" and [(c.title, len(c.paragraphs)) for c in chs] == [("One", 3), ("Two", 2)]


def test_pdf_reflow_and_header_removal():
    from novel_epub.files import reflow, split_by_headings

    lines = ["Chapter 1", "The lantern swayed while Arin", "counted the steps to the old", "mill.", "",
             "He waited.", "Chapter 2", "A new day be-", "gan quietly."]
    paras = reflow(lines)
    assert paras == ["Chapter 1", "The lantern swayed while Arin counted the steps to the old mill.", "He waited.",
                     "Chapter 2", "A new day began quietly."]
    assert [t for t, _ in split_by_headings(paras)] == ["Chapter 1", "Chapter 2"]
    assert len(split_by_headings(["kelime " * 1000] * 7)) == 3  # başlık yoksa ~3000 kelimelik parçalar


def test_unsupported_file_type(tmp_path: Path):
    import pytest

    from novel_epub.files import FileError, load_file

    (tmp_path / "x.exe").write_bytes(b"MZ")
    with pytest.raises(FileError):
        load_file(tmp_path / "x.exe")


def test_store_is_separate_per_target_language(tmp_path: Path):
    from novel_epub.store import BookStore

    nv = Novel(url="u", title="k", source="t")
    tr_st, en_st = BookStore(tmp_path, nv), BookStore(tmp_path, nv, lang="en")
    tr_st.save_tr(Chapter(1, "tr", "u", ["a"]))
    tr_st.save_glossary({"Gate": "Kapı"})
    assert en_st.load_tr(1) is None and en_st.load_glossary() == {}
    assert tr_st.glossary_path.name == "sozluk.json" and en_st.glossary_path.name == "sozluk-en.json"


def test_turkish_rules_only_for_turkish_target():
    from novel_epub.translator import SYSTEM_PROMPT, TURKISH_RULES

    tr = _fake_translator()
    assert "Cilt N Bölüm M" in tr._config(RESPONSE_SCHEMA_FOR_TEST(), SYSTEM_PROMPT)["system"]
    en = GeminiTranslator.__new__(GeminiTranslator)
    en._init_state("m", lang="en")
    en.thinking = False
    instr = en._config(RESPONSE_SCHEMA_FOR_TEST(), SYSTEM_PROMPT)["system"]
    assert "İngilizce (English)" in instr and TURKISH_RULES.strip() not in instr


def test_history_scan_reads_history_and_bookmarks(tmp_path: Path, monkeypatch):
    import sqlite3

    from novel_epub import history

    prof = tmp_path / "Default"
    prof.mkdir()
    con = sqlite3.connect(prof / "History")
    con.execute("create table urls(url text, title text, visit_count int)")
    con.executemany("insert into urls values(?,?,?)", [
        ("https://freewebnovel.com/novel/a/chapter-1", "A1", 3), ("https://freewebnovel.com/novel/a/chapter-2", "A2", 1),
        ("https://www.google.com/search?q=chapter", "g", 9), ("https://news.example/article", "n", 4)])
    con.commit()
    con.close()
    (prof / "Bookmarks").write_text(json.dumps({"roots": {"synced": {"children": [
        {"type": "url", "url": "https://other-novels.net/series/xyz/", "name": "XYZ"}]}}}), "utf-8")
    monkeypatch.setattr(history, "_user_data_dirs", lambda: {"Brave": tmp_path})
    r = history.scan(lambda u: "freewebnovel" if "freewebnovel" in u else None)
    sites = {s["domain"]: s for s in r["sites"]}
    assert r["browsers"] == ["Brave/Default"] and set(sites) == {"freewebnovel.com", "other-novels.net"}
    assert sites["freewebnovel.com"]["urls"] == 2 and sites["freewebnovel.com"]["novels"] == 1
    assert sites["other-novels.net"]["bookmarks"] == 1 and sites["other-novels.net"]["supported"] is None


def test_upload_endpoint_rejects_and_accepts(tmp_path: Path, monkeypatch):
    import io

    from novel_epub import web

    monkeypatch.setattr(web, "UPLOADS", tmp_path / "up")
    c = web.app.test_client()
    bad = c.post("/api/upload", data={"file": (io.BytesIO(b"MZ"), "x.exe")}, content_type="multipart/form-data")
    assert bad.status_code == 400
    txt = "\n\n".join(["Chapter 1", *_lorem(2, "a"), "Chapter 2", *_lorem(2, "b")]).encode()
    ok = c.post("/api/upload", data={"file": (io.BytesIO(txt), "kitap.txt")}, content_type="multipart/form-data").get_json()
    assert ok["chapters"] == 2 and (tmp_path / "up" / ok["id"]).exists()


def test_pull_android_with_fake_adb(tmp_path: Path):
    import sqlite3

    import pytest

    from novel_epub import history

    class R:
        def __init__(self, out=b"", code=0):
            self.stdout, self.returncode = out, code

    db = tmp_path / "src.sqlite"
    con = sqlite3.connect(db)
    con.execute("create table urls(url text, title text, visit_count int)")
    con.execute("insert into urls values('https://freewebnovel.com/novel/a/chapter-3','A3',2)")
    con.commit()
    con.close()
    history_bytes = db.read_bytes()

    def run(args, timeout=120):
        cmd = " ".join(args)
        if args[-1] == "devices":
            return R(b"List of devices attached\nABC123\tdevice\n")
        if "su -c id" in cmd:
            return R(b"uid=0(root)")
        if "com.brave.browser/app_chrome/Default/History'" in cmd:
            return R(history_bytes)
        return R(b"cat: No such file or directory", 1)

    dirs = history.pull_android("adb", tmp_path / "tel", run)
    assert list(dirs) == ["Brave (telefon)"]
    r = history.scan(lambda u: "freewebnovel", dirs)
    assert r["sites"][0]["domain"] == "freewebnovel.com" and r["browsers"] == ["Brave (telefon)/Default"]

    with pytest.raises(history.PhoneError, match="izin"):
        history.pull_android("adb", tmp_path / "x", lambda a, timeout=0: R(b"List\nABC\tunauthorized\n"))
    with pytest.raises(history.PhoneError, match="Root"):
        history.pull_android("adb", tmp_path / "x", lambda a, timeout=0: R(b"List\nABC\tdevice\n") if a[-1] == "devices" else R(b"", 1))
    with pytest.raises(history.PhoneError, match="görünmüyor"):
        history.pull_android("adb", tmp_path / "x", lambda a, timeout=0: R(b"List of devices attached\n"))


class _HTTP:
    def __init__(self, status, data):
        self.status_code, self._data = status, data
        self.text = json.dumps(data)

    def json(self):
        return self._data


def test_llm_requests_and_responses_per_provider():
    from novel_epub import llm

    msgs = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "U"}]
    schema = {"type": "object", "properties": {"p": {"type": "array", "items": {"type": "string"}}}}
    rf = {"type": "json_schema", "json_schema": {"name": "c", "schema": schema}}
    url, h, b = llm.build_request("gemini/gemini-3.8-flash", msgs, "g-test", None, 0.7, 1000, rf, "medium")
    assert url.endswith("/models/gemini-3.8-flash:generateContent") and h["x-goog-api-key"] == "g-test"
    assert b["systemInstruction"]["parts"][0]["text"] == "SYS" and b["contents"][0]["parts"][0]["text"] == "U"
    cfg = b["generationConfig"]
    assert cfg["responseSchema"]["type"] == "OBJECT" and cfg["responseSchema"]["properties"]["p"]["items"]["type"] == "STRING"
    assert cfg["thinkingConfig"] == {"thinkingLevel": "medium"} and cfg["maxOutputTokens"] == 1000

    url, h, b = llm.build_request("openai/gpt-5", msgs, "o-test", None, 0.7, 1000, rf, "medium")
    assert url == "https://api.openai.com/v1/chat/completions" and h["Authorization"] == "Bearer o-test"
    assert "temperature" not in b and b["max_completion_tokens"] == 1000 and b["reasoning_effort"] == "medium"
    url, h, b = llm.build_request("deepseek/deepseek-chat", msgs, "d", None, 0.7, 500, {"type": "json_object"})
    assert url.startswith("https://api.deepseek.com") and b["max_tokens"] == 500 and b["temperature"] == 0.7
    url, h, b = llm.build_request("anthropic/claude-sonnet-4-5", msgs, "a", None, 0.7, 500, {"type": "json_object"})
    assert url.endswith("/v1/messages") and b["system"] == "SYS" and b["messages"] == [msgs[1]] and h["x-api-key"] == "a"
    url, _, _ = llm.build_request("ollama_chat/qwen3", msgs, None, "http://localhost:11434")
    assert url == "http://localhost:11434/v1/chat/completions"

    gem = {"candidates": [{"content": {"parts": [{"text": "düşünce", "thought": True}, {"text": '{"a": 1}'}]},
                           "finishReason": "MAX_TOKENS"}], "usageMetadata": {"candidatesTokenCount": 10, "thoughtsTokenCount": 5}}
    r = llm.completion("gemini/x", msgs, "k", post=lambda *a: _HTTP(200, gem))
    assert r.choices[0].message.content == '{"a": 1}' and r.choices[0].finish_reason == "length"
    assert (r.usage.completion_tokens, r.usage.completion_tokens_details.reasoning_tokens) == (15, 5)
    ant = {"content": [{"type": "text", "text": "{}"}], "stop_reason": "end_turn", "usage": {"output_tokens": 7}}
    assert llm.completion("anthropic/c", msgs, "k", post=lambda *a: _HTTP(200, ant)).usage.completion_tokens == 7

    from novel_epub.translator import _classify

    def fail(status, body):
        try:
            llm.completion("gemini/x", msgs, "k", post=lambda *a: _HTTP(status, body))
        except Exception as e:
            return _classify(e)

    assert fail(400, {"error": {"message": "API key not valid. Please pass a valid API key."}}) == "auth"
    assert fail(429, {"error": {"details": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}}) == "quota"
    assert fail(429, {"error": {"message": "Please retry in 12.5s."}}) == "busy"
    assert fail(404, {"error": {"message": "models/x is not found"}}) == "missing"
    assert fail(503, {"error": {"message": "overloaded"}}) == "busy"
    assert _classify(llm.APIConnectionError("koptu")) == "net"


def test_lan_devices_can_only_download_and_cross_site_requests_are_blocked(tmp_path: Path, monkeypatch):
    from novel_epub import web

    monkeypatch.setattr(web, "SETTINGS_PATH", tmp_path / "ayarlar.json")
    monkeypatch.setattr(web, "_keyring", lambda: None)
    monkeypatch.setattr(web, "OUTPUT", tmp_path / "cikti")
    (tmp_path / "cikti").mkdir()
    (tmp_path / "cikti" / "kitap.epub").write_bytes(b"PK")
    web.save_settings({"models": ["gemini/m"], "key_store": "dosya", "keys": {"gemini": "AIzaUYDURMA1234"}})
    c = web.app.test_client()

    # telefon (aynı Wi-Fi): sayfa, kitap listesi ve indirme açık; anahtar ipucu bile gitmez
    phone = {"REMOTE_ADDR": "192.168.1.20"}
    lan = dict(base_url="http://192.168.1.10:5000", environ_base=phone)
    assert c.get("/", **lan).status_code == 200
    assert c.get("/api/books", **lan).get_json()[0]["name"] == "kitap.epub"
    assert c.get("/indir/kitap.epub", **lan).status_code == 200
    assert all(p["hint"] == "" for p in c.get("/api/settings", **lan).get_json()["providers"])
    # ...ama hiçbir şeyi değiştiremez, kitaplığa ya da iş başlatmaya erişemez
    assert c.delete("/api/keys/gemini", **lan).status_code == 403
    assert c.post("/api/settings", json={"theme": "dark"}, **lan).status_code == 403
    assert c.post("/api/jobs", json={"url": "https://example.com/novel/x"}, **lan).status_code == 403
    assert c.get("/api/library", **lan).status_code == 403

    # bu bilgisayar: kendi sayfasından gelen istek geçer, başka siteden gelen (CSRF) geçmez
    assert c.post("/api/settings", json={"theme": "dark"}, headers={"Origin": "http://localhost"}).status_code == 200
    assert c.post("/api/settings", json={"theme": "light"}, headers={"Origin": "https://kotu.example"}).status_code == 403
    assert c.post("/api/settings", json={"theme": "light"}, headers={"Origin": "null"}).status_code == 403
    # DNS yeniden bağlama: alan adıyla gelen istek reddedilir
    assert c.get("/api/settings", base_url="http://kotu.example:5000").status_code == 403
    assert c.get("/api/settings", base_url="http://127.0.0.1:5000").get_json()["providers"][0]["hint"] == "…1234"


def test_exporters_write_every_format_readably(tmp_path: Path):
    import zipfile as zf

    from novel_epub.exporters import FORMATS, export, normalize
    from novel_epub.files import read_docx, read_epub
    from novel_epub.models import Chapter, Novel

    novel = Novel(url="https://example.com/novel/lorem", title="Lorem & Ipsum", source="test", author="Dolor Sit")
    filler = "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore."
    chs = [Chapter(i, f"Bölüm {i}: Lorem", f"u{i}", [f"Lorem ipsum {i} <dolor> şğüöçı.", "# Sit amet\x0b", "* consectetur", filler])
           for i in (1, 2, 3)]
    assert normalize(None) == "epub" and normalize(".DOCX") == "docx" and normalize("pdf") == "epub"
    out = {f: export(f, novel, chs, tmp_path / "kitap", language="tr", cover=b"\x89PNG\r\n\x1a\n0000") for f in FORMATS}
    assert {p.suffix for p in out.values()} == {".epub", ".docx", ".html", ".txt", ".md"}

    # EPUB ve DOCX uygulamanın kendi okuyucularıyla geri okunur (bölümler ve başlıklar korunur)
    n, back, _ = read_epub(out["epub"])
    assert [c.title for c in back] == [c.title for c in chs]
    n, back, _ = read_docx(out["docx"])
    assert n.title == "Lorem & Ipsum" and [c.title for c in back] == [c.title for c in chs]
    assert back[0].paragraphs[0] == "Lorem ipsum 1 <dolor> şğüöçı." and back[0].paragraphs[1] == "# Sit amet"
    with zf.ZipFile(out["docx"]) as z:
        assert z.testzip() is None and "pageBreakBefore" in z.read("word/styles.xml").decode()

    h = out["html"].read_text("utf-8")
    assert h.startswith("<!DOCTYPE html>") and 'lang="tr"' in h and "&lt;dolor&gt;" in h and "data:image/png;base64," in h
    assert h.count('<section id="b') == 3 and 'href="#b3"' in h
    t = out["txt"].read_text("utf-8")
    assert t.startswith("Lorem & Ipsum") and "Bölüm 2: Lorem\n" in t and "<dolor>" in t
    m = out["md"].read_text("utf-8")
    assert m.startswith("# Lorem & Ipsum") and "## Bölüm 3: Lorem" in m and "\n\\# Sit amet" in m and "\n\\* consectetur" in m


def test_output_format_setting_drives_jobs_and_book_list(tmp_path: Path, monkeypatch):
    from novel_epub import pipeline, web

    monkeypatch.setattr(web, "SETTINGS_PATH", tmp_path / "ayarlar.json")
    monkeypatch.setattr(web, "_keyring", lambda: None)
    monkeypatch.setattr(web, "OUTPUT", tmp_path / "cikti")
    c = web.app.test_client()
    s = c.get("/api/settings").get_json()
    assert s["output_format"] == "epub" and [f["id"] for f in s["formats"]] == ["epub", "docx", "html", "txt", "md"]
    assert c.post("/api/settings", json={"output_format": "docx"}).get_json()["output_format"] == "docx"
    assert c.post("/api/settings", json={"output_format": "exe"}).get_json()["output_format"] == "docx"  # bilinmeyen yok sayılır

    # dosyadan dönüştürme: ayardaki biçimde yazılır
    src = tmp_path / "lorem.txt"
    src.write_text("Bölüm 1\n\nLorem ipsum dolor.\n\nBölüm 2\n\nSit amet.\n", "utf-8")
    out = pipeline.Job(pipeline.Options(url="", file=str(src), fmt=web.load_settings()["output_format"],
                                        library=tmp_path / "kutuphane", output=tmp_path / "cikti")).run()
    assert out and Path(out).suffix == ".docx"
    # Başlat'ta seçilen biçim ayarı ezer (yalnız bu iş için)
    started = {}
    class FakeJob:
        def __init__(self, opts, on_log=None):
            started["o"] = opts

        def run(self):
            pass

    monkeypatch.setattr(web, "Job", FakeJob)
    assert c.post("/api/jobs", json={"url": "https://example.com/novel/x", "format": "html"}).status_code == 200
    assert started["o"].fmt == "html"
    started.clear()
    c.post("/api/jobs", json={"url": "https://example.com/novel/x"})
    assert started["o"].fmt == "docx"
    (tmp_path / "cikti" / "not.exe").write_bytes(b"MZ")
    books = c.get("/api/books").get_json()
    assert [b["format"] for b in books] == ["docx"]  # yalnız kitap biçimleri listelenir
    r = c.get("/indir/" + books[0]["name"])
    assert r.status_code == 200 and r.mimetype.endswith("wordprocessingml.document")
    assert c.get("/indir/not.exe").status_code == 404


def test_net_without_curl_cffi_works_like_the_desktop_client():
    """Android'de curl_cffi yok: yedek istemci aynı arayüzü vermeli (durum kodu, başlık, metin, json, POST gövdesi)."""
    import http.server
    import threading

    from novel_epub import net

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            code = 404 if self.path == "/yok" else 200
            body = "Şğüöçı lorem".encode("iso-8859-9") if self.path == "/latin" else \
                f"ua={self.headers.get('User-Agent', '')[:11]}|ref={self.headers.get('Referer', '')}".encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=iso-8859-9" if self.path == "/latin" else "text/plain")
            self.send_header("X-Deneme", "evet")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            data = self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(429 if b"kota" in data else 200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"geri": json.loads(data), "ct": self.headers.get("Content-Type")}).encode())

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        net.set_backend("urllib")
        s = net.Session()
        r = s.get(base + "/x", headers={"Referer": "https://ornek.test/"})
        assert r.status_code == 200 and r.headers.get("x-deneme") == "evet" and r.headers.get("X-DENEME") == "evet"
        assert r.text == "ua=Mozilla/5.0|ref=https://ornek.test/"
        assert s.get(base + "/latin").text == "Şğüöçı lorem"
        assert s.get(base + "/yok").status_code == 404  # hata kodu istisna değil, yanıt olarak döner
        r = net.post(base + "/api", headers={"Content-Type": "application/json"}, data=json.dumps({"a": "ş"}).encode())
        assert r.status_code == 200 and r.json() == {"geri": {"a": "ş"}, "ct": "application/json"}
        assert net.post(base + "/api", data=b'{"kota": 1}').status_code == 429
    finally:
        net.set_backend(None)
        srv.shutdown()
