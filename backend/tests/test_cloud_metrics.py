"""4.1: metrics for client-timed (enterprise) requests; local metrics stay exactly as they were."""

import pytest

from app.core.metrics import StreamCollector, compute_cloud_metrics, compute_metrics
from tests.fakes import load_fixture, make_stream


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def run(chunks_with_times):
    """Feed (time, chunk) pairs to a collector whose clock starts at 100.0."""
    clock = Clock()
    col = StreamCollector(clock=clock)
    for t, chunk in chunks_with_times:
        clock.t = t
        col.feed(chunk)
    return col


def text(piece):
    return {"message": {"role": "assistant", "content": piece}, "done": False}


def thought(piece):
    return {"message": {"role": "assistant", "content": "", "thinking": piece}, "done": False}


def final(eval_count=100, prompt=20, **provider):
    meta = {
        "provider": "oa",
        "kind": "openai",
        "model_version": "gpt-4o-2024-08-06",
        "attempts": 1,
        "retry_wait_ms": 0.0,
        "params_applied": {"temperature": 0},
        "params_ignored": [],
        "reasoning_tokens": None,
        "finish_reason": "stop",
    }
    meta.update(provider)
    c = {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop", "_provider": meta}
    if eval_count is not None:
        c["eval_count"] = eval_count
    if prompt is not None:
        c["prompt_eval_count"] = prompt
    return c


# ---------------------------------------------------------------- formulas
def test_cloud_tokens_per_second_is_output_tokens_over_first_token_to_end():
    m = run([(100.5, text("Hello")), (102.5, final(eval_count=100))]).finish()
    assert m["ttft_ms"] == pytest.approx(500.0) and m["latency_ms"] == pytest.approx(2500.0)
    assert m["tokens_per_s"] == pytest.approx(100 / 2.0)  # window: 500 ms -> 2500 ms
    assert m["tokens_per_s_source"] == "client" and m["output_tokens"] == 100 and m["prompt_tokens"] == 20


def test_load_and_evaluation_durations_are_absent_not_zero_and_never_cold():
    m = run([(100.2, text("x")), (101.0, final())]).finish()
    for k in ("load_ms", "total_ms", "prompt_eval_ms", "eval_ms"):
        assert m[k] is None
    assert m["is_cold"] is False and m["is_cloud"] is True


def test_retry_wait_is_removed_from_latency_and_ttft_and_reported_separately():
    # 1.5 s went on a rate-limit wait before the request that succeeded
    m = run([(102.0, text("Hi")), (103.5, final(eval_count=30, retry_wait_ms=1500.0, attempts=2))]).finish()
    assert m["ttft_ms"] == pytest.approx(500.0) and m["latency_ms"] == pytest.approx(2000.0)
    assert m["retry_wait_ms"] == 1500.0 and m["attempts"] == 2
    assert m["tokens_per_s"] == pytest.approx(30 / 1.5)  # the wait never inflates or deflates generation speed


def test_answer_time_after_thinking_is_measured_from_the_visible_stream():
    m = run([(100.4, thought("hmm")), (101.4, text("42")), (102.4, final(eval_count=60, reasoning_tokens=50))]).finish()
    assert m["ttft_ms"] == pytest.approx(400.0) and m["ttft_answer_ms"] == pytest.approx(1400.0)


def test_hidden_reasoning_tokens_are_kept_out_of_the_speed_window():
    """OpenAI does not stream reasoning: 200 of 300 tokens happened before the first visible token."""
    m = run([(103.0, text("Answer")), (105.0, final(eval_count=300, reasoning_tokens=200))]).finish()
    assert m["thinking_tokens"] == 200 and m["thinking_tokens_approx"] is False
    assert m["tokens_per_s"] == pytest.approx(100 / 2.0)  # 100 visible tokens in the 2 s after the first one


def test_streamed_reasoning_counts_in_full_and_is_exact_when_reported():
    m = run([(100.2, thought("t")), (101.2, text("x")), (102.2, final(eval_count=300, reasoning_tokens=210))]).finish()
    assert m["thinking_tokens"] == 210 and m["thinking_tokens_approx"] is False
    assert m["tokens_per_s"] == pytest.approx(300 / 2.0)


def test_streamed_thinking_without_a_token_count_is_not_invented():
    m = run([(100.2, thought("a long thought")), (101.0, text("x")), (102.0, final(eval_count=80))]).finish()
    assert m["thinking_tokens"] is None and m["thinking_tokens_approx"] is True  # cannot be apportioned reliably


def test_no_reasoning_means_zero_thinking_tokens():
    m = run([(100.2, text("x")), (101.0, final(eval_count=10))]).finish()
    assert m["thinking_tokens"] == 0 and m["thinking_tokens_approx"] is False


# ---------------------------------------------------------------- absent values
def test_missing_usage_gives_absent_values_not_zeros():
    m = run([(100.2, text("x")), (101.0, final(eval_count=None, prompt=None))]).finish()
    assert m["tokens_per_s"] is None and m["output_tokens"] is None and m["prompt_tokens"] is None
    assert m["thinking_tokens"] is None and m["latency_ms"] is not None


def test_zero_length_window_yields_no_speed_rather_than_a_huge_one():
    m = run([(101.0, text("x")), (101.0, final(eval_count=5))]).finish()
    assert m["tokens_per_s"] is None
    m = run([(101.0, text("x")), (101.0005, final(eval_count=5))]).finish()
    assert m["tokens_per_s"] is None  # under 1 ms


def test_empty_answer_has_no_ttft_and_no_speed():
    m = run([(101.0, final(eval_count=0))]).finish()
    assert m["ttft_ms"] is None and m["tokens_per_s"] is None


def test_failed_before_the_first_token_is_absent_like_local():
    col = StreamCollector(clock=Clock())
    m = col.failed()
    assert m["failed"] is True and m["latency_ms"] is None and m["tokens_per_s"] is None


# ---------------------------------------------------------------- provenance
def test_provenance_and_parameter_records_are_carried_into_the_metrics():
    ignored = [{"name": "seed", "reason": "not supported"}]
    m = run(
        [
            (100.1, text("x")),
            (
                100.9,
                final(
                    params_ignored=ignored,
                    model_version="claude-x-20250101",
                    provider="an",
                    kind="anthropic",
                    finish_reason="end_turn",
                ),
            ),
        ]
    ).finish()
    assert (m["provider"], m["provider_kind"], m["model_version"]) == ("an", "anthropic", "claude-x-20250101")
    assert (
        m["params_ignored"] == ignored
        and m["params_applied"] == {"temperature": 0}
        and m["finish_reason"] == "end_turn"
    )
    assert m["done_reason"] == "stop"


# ---------------------------------------------------------------- local metrics are untouched
LOCAL_KEYS = {
    "latency_ms",
    "ttft_ms",
    "ttft_answer_ms",
    "load_ms",
    "total_ms",
    "prompt_eval_ms",
    "eval_ms",
    "prompt_tokens",
    "output_tokens",
    "thinking_tokens",
    "thinking_tokens_approx",
    "tokens_per_s",
    "is_cold",
    "ollama",
    "done_reason",
}


def test_local_metrics_have_exactly_the_same_keys_and_no_cloud_fields():
    chunks = load_fixture("chat_stream_think.ndjson")
    clock = Clock()
    col = StreamCollector(clock=clock)
    for ch in chunks:
        clock.t += 0.01
        col.feed(ch)
    m = col.finish()
    assert set(m) == LOCAL_KEYS
    assert (
        m["tokens_per_s"] == pytest.approx(182 / 4.305027, rel=1e-3) and m["is_cold"] is True
    )  # recorded stream, real values
    assert "is_cloud" not in m and "tokens_per_s_source" not in m


def test_local_stream_without_provider_block_never_takes_the_cloud_path():
    col = StreamCollector(clock=Clock())
    for ch in make_stream("a b c"):
        col.feed(ch)
    assert "is_cloud" not in col.finish()


def test_compute_functions_are_independent():
    local = compute_metrics(
        {"eval_count": 100, "eval_duration": 2_000_000_000}, latency_ms=1, ttft_ms=1, ttft_answer_ms=1
    )
    cloud = compute_cloud_metrics(
        {"eval_count": 100}, {"retry_wait_ms": 0}, latency_ms=2500.0, ttft_ms=500.0, ttft_answer_ms=500.0
    )
    assert (
        local["tokens_per_s"] == 50.0
        and cloud["tokens_per_s"] == 50.0
        and "is_cloud" not in local
        and cloud["is_cloud"]
    )
