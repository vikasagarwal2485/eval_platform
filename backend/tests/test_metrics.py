import pytest

from app.core.metrics import COLD_LOAD_THRESHOLD_NS, StreamCollector, compute_metrics, describe, percentile, perf_stats
from tests.fakes import load_fixture, make_stream


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def run(chunks, step=0.1):
    clock = Clock()
    col = StreamCollector(clock=clock)
    for ch in chunks:
        clock.t += step
        col.feed(ch)
    return col


# ------------------------------------------------------------------ 7.1 capture
def test_fixture_stream_captures_counters_and_timings():
    chunks = load_fixture("chat_stream_think.ndjson")
    col = run(chunks, step=0.01)
    m = col.finish()
    final = chunks[-1]
    assert m["output_tokens"] == final["eval_count"]
    assert m["prompt_tokens"] == final["prompt_eval_count"]
    assert m["eval_ms"] == pytest.approx(final["eval_duration"] / 1e6)
    assert m["load_ms"] == pytest.approx(final["load_duration"] / 1e6)
    assert m["ttft_ms"] == pytest.approx(10.0)  # first chunk with thinking text
    assert m["ttft_answer_ms"] > m["ttft_ms"]  # answer starts after thinking
    assert m["latency_ms"] == pytest.approx(len(chunks) * 10.0)
    assert col.text.startswith("Final answer") and col.thinking_text


def test_ttft_ignores_empty_leading_chunks():
    chunks = [{"message": {"content": ""}, "done": False}] + make_stream("hello there")
    col = run(chunks, step=0.5)
    m = col.finish()
    assert m["ttft_ms"] == pytest.approx(1000.0)  # second chunk (first with text)
    assert m["ttft_answer_ms"] == pytest.approx(1000.0)


def test_failed_before_first_token_has_none_not_zero():
    col = StreamCollector(clock=Clock())
    m = col.failed()
    assert m["failed"] is True
    for k in ("latency_ms", "ttft_ms", "ttft_answer_ms", "tokens_per_s", "output_tokens"):
        assert m[k] is None


def test_failed_after_partial_output_keeps_observed_ttft():
    col = run(make_stream("a b c")[:2], step=0.2)
    m = col.failed()
    assert m["ttft_ms"] == pytest.approx(200.0) and m["latency_ms"] is None


def test_missing_counters_yield_none():
    m = compute_metrics({}, latency_ms=5.0, ttft_ms=1.0, ttft_answer_ms=1.0)
    assert m["tokens_per_s"] is None and m["output_tokens"] is None and m["load_ms"] is None and m["is_cold"] is False


# ------------------------------------------------------------------ 7.2 formulas
def test_tokens_per_second_formula():
    m = compute_metrics({"eval_count": 200, "eval_duration": 4_000_000_000}, latency_ms=1, ttft_ms=1, ttft_answer_ms=1)
    assert m["tokens_per_s"] == pytest.approx(50.0)


def test_zero_duration_does_not_divide():
    m = compute_metrics({"eval_count": 10, "eval_duration": 0}, latency_ms=1, ttft_ms=1, ttft_answer_ms=1)
    assert m["tokens_per_s"] is None


def test_thinking_tokens_apportioned_and_flagged_approximate():
    m = compute_metrics(
        {"eval_count": 100}, latency_ms=1, ttft_ms=1, ttft_answer_ms=1, thinking_chars=300, answer_chars=100
    )
    assert m["thinking_tokens"] == 75 and m["thinking_tokens_approx"] is True


def test_no_thinking_means_zero_thinking_tokens_exact():
    m = compute_metrics({"eval_count": 100}, latency_ms=1, ttft_ms=1, ttft_answer_ms=1)
    assert m["thinking_tokens"] == 0 and m["thinking_tokens_approx"] is False


def test_cold_flag_from_load_duration():
    cold = compute_metrics({"load_duration": COLD_LOAD_THRESHOLD_NS + 1}, latency_ms=1, ttft_ms=1, ttft_answer_ms=1)
    warm = compute_metrics({"load_duration": 20_000_000}, latency_ms=1, ttft_ms=1, ttft_answer_ms=1)
    assert cold["is_cold"] is True and warm["is_cold"] is False


def test_fixture_first_request_is_cold():
    """The recorded fixture had a ~4.8 s model load."""
    col = run(load_fixture("chat_stream_think.ndjson"))
    assert col.finish()["is_cold"] is True


# ------------------------------------------------------------------ 7.4 aggregates
def test_percentile_and_describe_hand_computed():
    v = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert percentile(v, 50) == 5.5
    assert percentile(v, 95) == pytest.approx(9.55)  # 9 + 0.55 * (10 - 9)
    d = describe(v)
    assert (d["n"], d["mean"], d["median"], d["min"], d["max"]) == (10, 5.5, 5.5, 1, 10)
    assert d["stdev"] == pytest.approx(3.0276503)


def test_describe_ignores_none_and_handles_empty():
    assert describe([None, 4.0, None])["mean"] == 4.0
    assert describe([None])["n"] == 0 and describe([])["median"] is None
    assert describe([7.0])["stdev"] == 0.0 and describe([7.0])["p95"] == 7.0


class Row:
    def __init__(self, latency, tps, cold=False, status="ok", load=None):
        self.status, self.is_cold, self.latency_ms, self.ttft_ms = (
            status,
            cold,
            latency,
            latency / 10 if latency else None,
        )
        self.tokens_per_s, self.output_tokens = tps, 10
        self.metrics = {"load_ms": load}


def test_perf_stats_excludes_cold_and_failed_by_default():
    rows = [Row(3000, 20, cold=True, load=2500), Row(100, 50), Row(200, 40), Row(None, None, status="error")]
    s = perf_stats(rows)
    assert (s["requests"], s["warm_requests"], s["cold_requests"]) == (4, 2, 1)
    assert s["latency_ms"]["mean"] == 150 and s["latency_ms"]["n"] == 2
    assert s["tokens_per_s"]["median"] == 45
    assert s["cold_load_ms"]["mean"] == 2500


def test_perf_stats_include_cold_option():
    rows = [Row(3000, 20, cold=True, load=2500), Row(100, 50)]
    assert perf_stats(rows, include_cold=True)["latency_ms"]["n"] == 2
