"""Harcama defteri ve sınırı (ağsız)."""
from datetime import datetime, timezone

from novel_epub import usage


def ts(y, mo, d, h):
    return datetime(y, mo, d, h, tzinfo=timezone.utc).timestamp()


def test_parse_limits_and_peak_pricing():
    assert usage.parse_limits("commandcode:5h=3,7d=10") == {"commandcode": {18000: 3.0, 604800: 10.0}}
    m = "commandcode/deepseek/deepseek-v4.1-flash"
    off = usage.cost(m, 1_000_000, 0, 1_000_000, ts(2026, 11, 28, 12))  # cumartesi: yoğun değil
    peak = usage.cost(m, 1_000_000, 0, 1_000_000, ts(2026, 11, 27, 7))  # cuma 07 UTC: yoğun
    assert round(off, 4) == 0.75 and round(peak, 4) == 1.5
    assert usage.cost(m, 1_000_000, 1_000_000, 0, ts(2026, 11, 28, 12)) == 0.003  # tamamı önbellekten


def test_ledger_blocks_provider_after_window_cap(tmp_path):
    led = usage.Ledger(tmp_path / "k.jsonl", usage.parse_limits("commandcode:5h=1,7d=2"))
    m = "commandcode/deepseek/deepseek-v4.1-flash"
    now = ts(2026, 11, 28, 12)
    assert led.tracked(m) and not led.tracked("gemini/gemini-3.8-flash")
    led.record(m, 1_000_000, 0, 1_000_000, ts=now - 6 * 3600)  # 0.75$, 5 saat penceresinin dışında
    assert led.over(m, now) == ""
    led.record(m, 1_000_000, 0, 1_000_000, ts=now - 60)  # 0.75$ daha: hafta 1.5$
    assert led.over(m, now) == ""
    led.record(m, 400_000, 0, 400_000, ts=now - 30)  # 5 saatte 1.05$ → sınır
    assert "5 saat" in led.over(m, now)
    s = led.summary(now - 3600)[m]
    assert s["requests"] == 2 and s["in"] == 1_400_000


def test_translator_stops_using_model_over_spend_cap(tmp_path):
    from types import SimpleNamespace

    from novel_epub.translator import GeminiTranslator, QuotaExhausted
    led = usage.Ledger(tmp_path / "k.jsonl", usage.parse_limits("commandcode:5h=0.001"))
    tr = GeminiTranslator.__new__(GeminiTranslator)
    tr._init_state("commandcode/deepseek/deepseek-v4.1-flash", log=lambda m: None)
    tr.ledger = led
    calls = []

    def fake(**kw):
        calls.append(kw["model"])
        msg = SimpleNamespace(content='{"new_terms": []}')
        use = SimpleNamespace(completion_tokens=2000, prompt_tokens=5000, cached_tokens=0,
                              completion_tokens_details=SimpleNamespace(reasoning_tokens=0))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")], usage=use)

    tr.complete = fake
    schema = {"type": "object", "properties": {"new_terms": {"type": "array"}}}
    tr._call({"x": 1}, schema)  # ilk istek geçer ve deftere yazılır
    assert len(calls) == 1 and len(led.rows()) == 1
    try:
        tr._call({"x": 1}, schema)
        raise AssertionError("sınır aşılmışken istek gitmemeli")
    except QuotaExhausted as e:
        assert "harcama sınırı" in str(e) or "kota" in str(e)
    assert len(calls) == 1
