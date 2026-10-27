"""add-otel-tracing 3.3/3.4: the Runner's own spans - names, trace/parent relationships, and
`Result.trace_id` - for a request with all three phases and for one with only generation."""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import app.core.tracing as tracing_mod
from tests.fakes import FakeOllama, make_tag
from tests.helpers import CLS as CLS_DICT
from tests.helpers import make_responder, new_client, start_run, wait_for
from tests.runner_harness import CLS, GEN, Harness, ref


@pytest.fixture
def exporter():
    """Installs an in-memory exporter as the process tracer provider for one test, synchronously
    (SimpleSpanProcessor - no batching delay), and restores the no-tracing default afterward."""
    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exp))
    tracing_mod._provider = provider
    yield exp
    tracing_mod._provider = None
    provider.shutdown()


@pytest.fixture
async def h(tmp_path):
    fake = FakeOllama([make_tag("qwen3:8b")], make_responder())
    harness = await Harness(tmp_path, fake).start()
    harness.oa.answer = "Rain taps the glass"
    harness.oa.judge_score = 5
    yield harness
    await harness.stop()


def by_name(spans, name):
    return [s for s in spans if s.name == name]


async def test_a_request_with_all_three_phases_shares_one_trace_with_a_real_warmup_edge(h, exporter):
    run_id = h.add_run(
        ["qwen3:8b"], [GEN], judge_mode="single", judge_model=ref("oa", "gpt-4o"), config={"warmup": True, "repeats": 1}
    )
    run = await h.run(run_id)
    assert run.status == "completed"

    spans = exporter.get_finished_spans()
    assert {s.name for s in spans} == {"eval.warmup", "eval.generate", "eval.judge"}
    warmup, generate, judge = by_name(spans, "eval.warmup")[0], by_name(spans, "eval.generate")[0], by_name(
        spans, "eval.judge"
    )[0]

    # same trace end to end
    trace_id = format(warmup.context.trace_id, "032x")
    assert format(generate.context.trace_id, "032x") == trace_id
    assert format(judge.context.trace_id, "032x") == trace_id

    # warm-up -> generate: a genuine parent/child edge (both happen live, in the same call stack)
    assert generate.parent is not None
    assert format(generate.parent.span_id, "016x") == format(warmup.context.span_id, "016x")
    # warm-up and generate are still distinct spans (per spec evaluation-runs: "A warm-up request's
    # span is distinguishable") - same trace, different span ids
    assert warmup.context.span_id != generate.context.span_id

    # generate -> judge: same trace, but no real parent edge (only `trace_id` survives into the
    # separate judge stage - design.md decision 3) - the judge span's parent is NOT the generate span
    assert judge.parent is None or judge.parent.span_id != generate.context.span_id

    # `kind` distinguishes the specific phase on every span (not just judge); `type` is the coarser
    # case-vs-judge grouping; `model` is the uniform attribute name for the model a span is about -
    # a Tempo/Grafana query can filter on one attribute name regardless of phase.
    assert warmup.attributes["eval.kind"] == "warmup" and warmup.attributes["eval.type"] == "case"
    assert warmup.attributes["model"] == "qwen3:8b"
    assert generate.attributes["eval.kind"] == "generate" and generate.attributes["eval.type"] == "case"
    assert generate.attributes["model"] == "qwen3:8b"
    assert judge.attributes["eval.kind"] == "judge" and judge.attributes["eval.type"] == "judge"
    assert judge.attributes["model"] == ref("oa", "gpt-4o")
    assert "judge_model" not in judge.attributes

    # the stored Result carries the shared trace id
    (model,) = h.by_model(run_id)
    (result,) = h.by_model(run_id)[model]
    assert result.trace_id == trace_id


async def test_a_request_with_only_generation_has_a_single_span_and_trace_id(h, exporter):
    run_id = h.add_run(["qwen3:8b"], [CLS], config={"warmup": False, "repeats": 1})  # no warm-up, judge_mode="none"
    run = await h.run(run_id)
    assert run.status == "completed"

    spans = exporter.get_finished_spans()
    assert {s.name for s in spans} == {"eval.generate"}
    (generate,) = spans
    assert generate.parent is None  # nothing preceded it - a fresh trace
    assert generate.attributes["eval.kind"] == "generate" and generate.attributes["eval.type"] == "case"

    (model,) = h.by_model(run_id)
    (result,) = h.by_model(run_id)[model]
    assert result.trace_id == format(generate.context.trace_id, "032x")


def test_trace_id_is_exposed_on_the_results_api(settings, file_session_factory):
    """add-otel-tracing: the `/results` endpoint actually serializes `Result.trace_id` - it's easy to
    wire the column through the Runner and forget the one line that puts it on the wire."""
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(InMemorySpanExporter()))
    try:
        fake = FakeOllama([make_tag("qwen3:8b")], make_responder())
        with new_client(settings, file_session_factory, fake) as c:
            tracing_mod._provider = provider  # create_app() above already called setup_tracing(settings)
            run = start_run(c, ["qwen3:8b"], [CLS_DICT], config={"warmup": False})
            wait_for(c, run["id"])
            results = c.get(f"/api/runs/{run['id']}/results").json()["results"]
    finally:
        tracing_mod._provider = None
        provider.shutdown()
    assert len(results) == 1
    assert results[0]["trace_id"] is not None and len(results[0]["trace_id"]) == 32
