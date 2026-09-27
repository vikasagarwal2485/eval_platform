"""4.2: the run worker with local and enterprise models (capability-aware, model-grouped)."""

import pytest

from tests.fakes import FakeOllama, make_stream, make_tag
from tests.runner_harness import CLS, Harness, ref

WARMUP = "Reply with the single word"


def ollama_answering(label="positive"):
    def responder(model, messages, options):
        if messages[-1]["content"].startswith(WARMUP):
            return make_stream("OK", eval_count=1)
        return make_stream(label)

    return FakeOllama([make_tag("qwen3:8b"), make_tag("gemma:test")], responder)


@pytest.fixture
async def h(tmp_path):
    harness = await Harness(tmp_path, ollama_answering()).start()
    harness.oa.answer = "positive"
    yield harness
    await harness.stop()


def kinds(calls):
    return [(c[0], c[1]) for c in calls]


async def test_local_then_cloud_warms_and_unloads_only_the_local_model(h):
    h.ollama.ps_data = [{"name": "qwen3:8b", "size": 5_000_000_000, "size_vram": 5_000_000_000}]
    run_id = h.add_run(["qwen3:8b", ref("oa", "gpt-4o")], [CLS])
    run = await h.run(run_id)
    assert run.status == "completed"
    # local: warm-up + one measured request, then unloaded before the cloud model starts
    assert kinds(h.ollama.calls) == [("chat", "qwen3:8b"), ("chat", "qwen3:8b"), ("unload", "qwen3:8b")]
    # cloud: exactly one billable request, no warm-up
    reqs = h.oa.chat_requests()
    assert len(reqs) == 1 and not any(WARMUP in m["content"] for m in reqs[0]["body"]["messages"])
    assert run.footprints == {str(next(k for k in run.footprints)): {"size": 5_000_000_000, "size_vram": 5_000_000_000}}
    assert len(run.footprints) == 1  # only the local model has a footprint


async def test_cloud_then_local_sends_no_unload_at_all(h):
    run_id = h.add_run([ref("oa", "gpt-4o"), "qwen3:8b"], [CLS])
    assert (await h.run(run_id)).status == "completed"
    assert kinds(h.ollama.calls) == [("chat", "qwen3:8b"), ("chat", "qwen3:8b")]  # warm-up + request, nothing unloaded
    assert len(h.oa.chat_requests()) == 1


async def test_two_cloud_models_get_no_warmup_and_no_unload(h):
    h.an.answer = "negative"
    run_id = h.add_run([ref("oa", "gpt-4o"), ref("an", "claude")], [CLS, CLS])
    assert (await h.run(run_id)).status == "completed"
    assert h.ollama.calls == []  # Ollama never touched
    assert len(h.oa.chat_requests()) == 2 and len(h.an.chat_requests()) == 2
    assert not any(WARMUP in str(r["body"]) for r in h.oa.chat_requests() + h.an.chat_requests())


async def test_execution_stays_grouped_by_model_across_local_and_cloud(h):
    run_id = h.add_run(
        [ref("oa", "gpt-4o"), "qwen3:8b", ref("an", "claude")], [CLS, CLS], config={"warmup": False, "repeats": 2}
    )
    assert (await h.run(run_id)).status == "completed"
    order = [name for name, _ in h.results(run_id)]
    assert order == [ref("oa", "gpt-4o")] * 4 + ["qwen3:8b"] * 4 + [ref("an", "claude")] * 4


async def test_cloud_results_carry_client_metrics_provenance_and_recorded_parameters(h):
    run_id = h.add_run(
        ["qwen3:8b", ref("oa", "gpt-4o")], [CLS], config={"warmup": True, "temperature": 0, "seed": 7, "num_ctx": 8192}
    )
    await h.run(run_id)
    by = h.by_model(run_id)
    (cloud,), (local,) = by[ref("oa", "gpt-4o")], by["qwen3:8b"]
    assert cloud.status == "ok" and cloud.output == "positive" and cloud.is_cold is False
    m = cloud.metrics
    assert m["is_cloud"] is True and m["provider"] == "oa" and m["model_version"] == "gpt-4o-2024-08-06"
    assert (
        m["load_ms"] is None
        and m["tokens_per_s_source"] == "client"
        and m["output_tokens"] == 1
        and m["prompt_tokens"] == 21
    )
    assert m["params_applied"]["seed"] == 7 and [i["name"] for i in m["params_ignored"]] == ["num_ctx"]
    assert cloud.latency_ms is not None and cloud.ttft_ms is not None  # typed columns are filled from the same metrics
    assert "is_cloud" not in local.metrics and local.metrics["load_ms"] is not None  # local unchanged


async def test_reasoning_flag_controls_the_think_option_for_cloud_models(h):
    run_id = h.add_run(
        [ref("oa", "o3"), ref("oa", "gpt-4o")], [CLS], config={"warmup": False, "think": True, "temperature": 0}
    )
    await h.run(run_id)
    by = h.by_model(run_id)
    o3, plain = by[ref("oa", "o3")][0].metrics, by[ref("oa", "gpt-4o")][0].metrics
    assert "think" in [i["name"] for i in o3["params_ignored"]] and "temperature" in [
        i["name"] for i in o3["params_ignored"]
    ]
    assert "think" not in [i["name"] for i in plain["params_ignored"]] and plain["params_applied"]["temperature"] == 0
    bodies = {r["body"]["model"]: r["body"] for r in h.oa.chat_requests()}
    assert "temperature" not in bodies["o3"] and bodies["gpt-4o"]["temperature"] == 0  # reasoning models get none


async def test_progress_and_events_report_the_model_source(h):
    run_id = h.add_run(["qwen3:8b", ref("oa", "gpt-4o")], [CLS], config={"warmup": False})
    events = []
    original = h.hub.publish

    def record(run, type_, data=None):
        events.append((type_, data or {}))
        return original(run, type_, data)

    h.hub.publish = record
    await h.run(run_id)
    started = [d for t, d in events if t == "model_started"]
    assert [(d["model"], d["source"]) for d in started] == [("qwen3:8b", "local"), (ref("oa", "gpt-4o"), "cloud")]
    assert [d["completed"] for t, d in events if t == "progress"] == [1, 2]


async def test_cloud_only_run_works_while_ollama_is_down(tmp_path):
    harness = await Harness(tmp_path, FakeOllama([], down=True)).start()
    try:
        harness.oa.answer = "positive"
        run_id = harness.add_run([ref("oa", "gpt-4o")], [CLS])
        run = await harness.run(run_id)
        assert run.status == "completed" and run.ollama_version is None  # no version, and no failure
        assert harness.by_model(run_id)[ref("oa", "gpt-4o")][0].status == "ok"
    finally:
        await harness.stop()


async def test_recorded_latency_excludes_the_rate_limit_wait(h):
    """3.5: a 0.4 s Retry-After wait is reported as retry_wait_ms, not folded into the request's latency."""
    from tests.fake_providers import Step

    h.oa.script.append(Step(kind="status", status=429, headers={"retry-after": "0.4"}))
    run_id = h.add_run([ref("oa", "gpt-4o")], [CLS], config={"warmup": False})
    assert (await h.run(run_id)).status == "completed"
    (r,) = h.by_model(run_id)[ref("oa", "gpt-4o")]
    assert r.status == "ok" and r.metrics["attempts"] == 2
    assert r.metrics["retry_wait_ms"] >= 400.0
    assert r.latency_ms < 400.0 and r.ttft_ms < 400.0  # the wait was taken out; only the successful attempt is timed
    assert len(h.oa.chat_requests()) == 2
