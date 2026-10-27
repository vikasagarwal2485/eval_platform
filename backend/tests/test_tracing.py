"""add-otel-tracing 3.2: tracer setup is a graceful no-op, and a span's own failure never
propagates into the code it wraps."""

from __future__ import annotations

import dataclasses

import pytest

from app.config import Settings
from app.core.tracing import SpanRef, is_enabled, setup_tracing, traced_span


def test_unset_endpoint_disables_tracing():
    setup_tracing(Settings(otel_endpoint=None))
    assert is_enabled() is False
    with traced_span("eval.request") as ref:
        assert ref is None


def test_unreachable_endpoint_sets_up_without_raising_and_never_blocks_on_export():
    """Construction never contacts the endpoint - only a later flush would, and that's the SDK's own
    background batch processor's problem, not this call's."""
    setup_tracing(Settings(otel_endpoint="http://127.0.0.1:1"))  # nothing listens here
    assert is_enabled() is True
    with traced_span("eval.request") as ref:
        assert ref is not None and len(ref.trace_id) == 32 and len(ref.span_id) == 16  # a real span was still created
    setup_tracing(Settings(otel_endpoint=None))  # restore for later tests in this process


def test_a_caller_exception_inside_the_span_always_propagates():
    setup_tracing(Settings(otel_endpoint=None))
    with pytest.raises(ValueError, match="boom"):
        with traced_span("eval.request"):
            raise ValueError("boom")


def test_a_broken_span_creation_never_propagates_into_the_caller(monkeypatch):
    """Simulates a bug in our own instrumentation code (not a network failure) - the span setup
    itself raises. traced_span must swallow that and yield None, never fail the request it wraps."""
    import app.core.tracing as tracing_mod

    setup_tracing(Settings(otel_endpoint="http://127.0.0.1:1"))
    assert is_enabled() is True

    class _BrokenProvider:
        def get_tracer(self, *_a, **_kw):
            raise RuntimeError("instrumentation bug")

    monkeypatch.setattr(tracing_mod, "_provider", _BrokenProvider())
    ran = False
    with traced_span("eval.request") as ref:
        assert ref is None
        ran = True
    assert ran  # the wrapped code still executed normally
    setup_tracing(Settings(otel_endpoint=None))  # restore for later tests in this process


def test_nested_spans_share_the_same_trace_id():
    setup_tracing(Settings(otel_endpoint="http://127.0.0.1:1"))
    with traced_span("eval.request") as outer:
        with traced_span("eval.generate") as inner:
            assert inner.trace_id == outer.trace_id
            assert inner.span_id != outer.span_id
    setup_tracing(Settings(otel_endpoint=None))  # restore for later tests in this process


def test_continuing_by_trace_id_joins_the_trace_with_a_synthetic_parent():
    """The judge-call case: only `trace_id` survived a round trip through storage, no real span id."""
    setup_tracing(Settings(otel_endpoint="http://127.0.0.1:1"))
    with traced_span("eval.generate") as generate_ref:
        pass
    with traced_span("eval.judge", trace_id=generate_ref.trace_id) as judge_ref:
        assert judge_ref.trace_id == generate_ref.trace_id
        assert judge_ref.span_id != generate_ref.span_id  # joined the trace, but with no real parent edge
    setup_tracing(Settings(otel_endpoint=None))  # restore for later tests in this process


def test_continuing_by_parent_ref_gives_a_genuine_parent_child_edge():
    """The warm-up-then-generate case: the caller still holds the exact SpanRef to continue from."""
    setup_tracing(Settings(otel_endpoint="http://127.0.0.1:1"))
    with traced_span("eval.warmup") as warmup_ref:
        pass
    with traced_span("eval.generate", parent=warmup_ref) as generate_ref:
        assert generate_ref.trace_id == warmup_ref.trace_id
    setup_tracing(Settings(otel_endpoint=None))  # restore for later tests in this process


def test_settings_default_otel_endpoint_is_unset_and_env_var_overrides(monkeypatch):
    from app.config import load_settings

    assert Settings().otel_endpoint is None
    monkeypatch.setenv("EVAL_OTEL_ENDPOINT", "http://localhost:4317")
    assert load_settings().otel_endpoint == "http://localhost:4317"
    monkeypatch.delenv("EVAL_OTEL_ENDPOINT")
    assert load_settings().otel_endpoint is None


def test_settings_is_frozen_and_otel_endpoint_defaults_carry_through_replace():
    s = dataclasses.replace(Settings(), otel_endpoint="http://localhost:4317")
    assert s.otel_endpoint == "http://localhost:4317"


def test_span_ref_is_a_plain_comparable_tuple():
    a = SpanRef("1" * 32, "2" * 16)
    b = SpanRef("1" * 32, "2" * 16)
    assert a == b
