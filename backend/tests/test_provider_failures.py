"""4.3: provider failures are isolated to that provider's models; Ollama unreachability still fails the run."""

import pytest

from app.ollama.client import OllamaUnreachable
from tests.fake_providers import Step
from tests.fakes import FakeOllama, make_stream, make_tag
from tests.runner_harness import CLS, KEY, Harness, ref

GPT, O3, CLAUDE = ref("oa", "gpt-4o"), ref("oa", "o3"), ref("an", "claude")


def ollama():
    return FakeOllama([make_tag("qwen3:8b")], lambda m, msgs, o: make_stream("positive"))


@pytest.fixture
async def h(tmp_path):
    harness = await Harness(tmp_path, ollama()).start()
    harness.oa.answer = harness.an.answer = "positive"
    yield harness
    await harness.stop()


def statuses(h, run_id):
    return {name: [(r.status, r.error) for r in rs] for name, rs in h.by_model(run_id).items()}


# ---------------------------------------------------------------- authentication
async def test_auth_failure_stops_that_models_requests_and_other_models_continue(h):
    h.env["OA_KEY"] = "wrong-key"
    run_id = h.add_run(["qwen3:8b", GPT, CLAUDE], [CLS, CLS, CLS], config={"warmup": False})
    run = await h.run(run_id)
    st = statuses(h, run_id)
    assert run.status == "completed"
    assert [s for s, _ in st[GPT]] == ["error", "error", "error"]
    assert "invalid" in st[GPT][0][1].lower() or "incorrect" in st[GPT][0][1].lower()  # the provider's own message
    assert all("authentication failed earlier in this run" in e for _, e in st[GPT][1:])  # recorded, not sent
    assert len(h.oa.chat_requests()) == 1  # only the first request ever went out
    assert [s for s, _ in st["qwen3:8b"]] == ["ok"] * 3 and [s for s, _ in st[CLAUDE]] == ["ok"] * 3


async def test_errors_count_as_failed_answers_in_scoring(h):
    h.env["OA_KEY"] = "wrong-key"
    run_id = h.add_run([GPT], [CLS, CLS], config={"warmup": False})
    await h.run(run_id)
    from app import repo

    with h.sf() as s:
        scores = repo.list_scores(s, run_id)
    assert [(x.kind, x.value, x.outcome) for x in scores] == [("auto", 0.0, "error")] * 2


async def test_a_bad_key_for_one_model_does_not_block_another_provider_or_the_next_run(h):
    h.env["OA_KEY"] = "wrong-key"
    first = await h.run(h.add_run([GPT, CLAUDE], [CLS], config={"warmup": False}))
    assert first.status == "completed"
    h.env["OA_KEY"] = KEY  # the user fixed the environment and restarted
    second_id = h.add_run([GPT], [CLS], config={"warmup": False})
    await h.run(second_id)
    assert statuses(h, second_id)[GPT] == [("ok", None)]  # circuits are per run


async def test_the_warning_is_announced_once(h):
    h.env["OA_KEY"] = "wrong-key"
    run_id = h.add_run([GPT], [CLS, CLS, CLS], config={"warmup": False})
    warnings = []
    original = h.hub.publish
    h.hub.publish = lambda r, t, d=None: (warnings.append(d) if t == "warning" else None, original(r, t, d))[1]
    await h.run(run_id)
    assert len(warnings) == 1 and "authentication failed" in warnings[0]["message"] and warnings[0]["model"] == GPT


# ---------------------------------------------------------------- outages and rate limits
async def test_provider_outage_after_retries_blocks_the_whole_provider_for_the_rest_of_the_run(h):
    h.oa.script.extend([Step(kind="status", status=503)] * 20)
    run_id = h.add_run([GPT, O3, CLAUDE, "qwen3:8b"], [CLS, CLS], config={"warmup": False})
    run = await h.run(run_id)
    st = statuses(h, run_id)
    assert run.status == "completed"
    assert len(h.oa.chat_requests()) == 3  # 1 attempt + 2 retries on the very first request, then nothing more
    assert all(s == "error" for s, _ in st[GPT] + st[O3])
    assert "gave up after 3 attempts" in st[GPT][0][1]
    assert all("provider 'oa' was unavailable" in e for _, e in st[GPT][1:] + st[O3])  # other oa model blocked too
    assert [s for s, _ in st[CLAUDE]] == ["ok", "ok"] and [s for s, _ in st["qwen3:8b"]] == ["ok", "ok"]


async def test_rate_limit_exhaustion_is_an_error_but_never_opens_a_circuit(h):
    h.oa.script.extend([Step(kind="status", status=429)] * 3)  # exactly the attempts of the first request
    run_id = h.add_run([GPT], [CLS, CLS, CLS], config={"warmup": False})
    run = await h.run(run_id)
    st = statuses(h, run_id)[GPT]
    assert run.status == "completed"
    assert st[0][0] == "error" and "gave up after 3 attempts" in st[0][1]
    assert [s for s, _ in st[1:]] == ["ok", "ok"]  # the limit cleared: later requests are still sent
    assert len(h.oa.chat_requests()) == 3 + 2


async def test_non_transient_client_errors_are_per_request_and_do_not_block(h):
    h.oa.script.append(
        Step(
            kind="status", status=400, body={"error": {"message": "This model's maximum context length is 8192 tokens"}}
        )
    )
    run_id = h.add_run([GPT], [CLS, CLS], config={"warmup": False})
    await h.run(run_id)
    assert [s for s, _ in statuses(h, run_id)[GPT]] == ["error", "ok"]


# ---------------------------------------------------------------- results are preserved; Ollama keeps its behaviour
async def test_completed_results_survive_and_ollama_unreachable_still_fails_the_run(tmp_path):
    def responder(model, messages, options):
        raise OllamaUnreachable("connection refused")

    harness = await Harness(tmp_path, FakeOllama([make_tag("qwen3:8b")], responder)).start()
    try:
        harness.oa.answer = "positive"
        run_id = harness.add_run([GPT, "qwen3:8b"], [CLS, CLS], config={"warmup": False})
        run = await harness.run(run_id)
        st = statuses(harness, run_id)
        assert run.status == "failed" and "connection refused" in run.error
        assert [s for s, _ in st[GPT]] == ["ok", "ok"]  # the cloud results completed before the local outage are kept
    finally:
        await harness.stop()


async def test_an_outage_of_one_provider_does_not_fail_the_run_even_when_it_is_the_only_one(h):
    h.oa.script.extend([Step(kind="status", status=503)] * 20)
    run_id = h.add_run([GPT], [CLS, CLS], config={"warmup": False})
    run = await h.run(run_id)
    assert run.status == "completed" and run.error is None  # errors are visible per result, the run itself finishes


async def test_the_key_never_appears_in_stored_errors(h):
    secret = "sk-proj-Zz9Yy8Xx7Ww6Vv5Uu4Tt3Ss2"
    h.env["OA_KEY"] = secret
    h.oa.expected_key = "something-else"  # the fake rejects this key and its error text mentions it
    h.oa.script.append(
        Step(kind="status", status=401, body={"error": {"message": f"Incorrect API key provided: {secret}"}})
    )
    run_id = h.add_run([GPT], [CLS], config={"warmup": False})
    await h.run(run_id)
    ((status, error),) = statuses(h, run_id)[GPT]
    assert status == "error" and secret not in error and "[REDACTED]" in error
