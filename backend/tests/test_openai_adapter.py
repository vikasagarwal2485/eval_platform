"""3.3: OpenAI adapter contract tests against the fake server."""

import json

import httpx
import pytest

from app.core.scoring.judge import JudgeCall, rubric_schema, run_judge
from app.providers.errors import ProviderAuthError, ProviderError, ProviderUnavailable
from app.providers.openai import OpenAIBackend, strictify
from tests.fake_providers import FakeOpenAI, Step
from tests.provider_helpers import KEY, collect, make, text_of, thinking_of

MSGS = [{"role": "user", "content": "hi"}]


@pytest.fixture
def server():
    srv = FakeOpenAI()
    url = srv.start()
    yield srv, url
    srv.stop()


def adapter(url, **kw):
    return make(OpenAIBackend, "openai", url, **kw)


# ---------------------------------------------------------------- text, usage, metadata
async def test_streams_text_as_ollama_shaped_chunks_with_a_final_usage_chunk(server):
    srv, url = server
    srv.answer = "Final answer: 5"
    chunks = await collect(adapter(url).chat_stream(model="gpt-4o", messages=MSGS, options={"temperature": 0}))
    assert text_of(chunks) == "Final answer: 5"
    assert all(c["done"] is False for c in chunks[:-1]) and chunks[-1]["done"] is True
    final = chunks[-1]
    assert final["prompt_eval_count"] == 21 and final["eval_count"] == 3 and final["done_reason"] == "stop"
    assert final["message"]["content"] == ""
    assert not {"eval_duration", "load_duration", "total_duration", "prompt_eval_duration"} & set(final)  # not reported


async def test_reports_resolved_model_version_and_attempts(server):
    srv, url = server
    srv.script.append(Step(model="gpt-4o-2025-01-01"))
    final = (await collect(adapter(url).chat_stream(model="gpt-4o", messages=MSGS)))[-1]
    meta = final["_provider"]
    assert meta["model_version"] == "gpt-4o-2025-01-01" and meta["attempts"] == 1 and meta["retry_wait_ms"] >= 0
    assert (meta["provider"], meta["kind"], meta["finish_reason"]) == ("prov", "openai", "stop")


async def test_reasoning_tokens_are_reported_exactly(server):
    srv, url = server
    srv.script.append(
        Step(
            usage={
                "prompt_tokens": 30,
                "completion_tokens": 250,
                "completion_tokens_details": {"reasoning_tokens": 200},
            }
        )
    )
    final = (await collect(adapter(url).chat_stream(model="o3", messages=MSGS, reasoning=True)))[-1]
    assert final["eval_count"] == 250 and final["_provider"]["reasoning_tokens"] == 200


async def test_reasoning_text_from_compatible_gateways_becomes_thinking():
    body = (
        "\n\n".join(
            "data: " + json.dumps(d)
            for d in [
                {"model": "m", "choices": [{"delta": {"reasoning_content": "hmm "}}]},
                {"model": "m", "choices": [{"delta": {"content": "42"}, "finish_reason": None}]},
                {"model": "m", "choices": [{"delta": {}, "finish_reason": "stop"}]},
                {"model": "m", "choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 9}},
            ]
        )
        + "\n\ndata: [DONE]\n\n"
    )
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})
    )
    chunks = await collect(adapter("http://gw.test", transport=transport).chat_stream(model="m", messages=MSGS))
    assert thinking_of(chunks) == "hmm " and text_of(chunks) == "42" and chunks[-1]["eval_count"] == 9


# ---------------------------------------------------------------- parameters
async def test_applies_temperature_seed_and_token_limit_and_records_them(server):
    srv, url = server
    opts = {"temperature": 0.2, "seed": 7, "num_predict": 256, "num_ctx": 8192}
    final = (await collect(adapter(url).chat_stream(model="gpt-4o", messages=MSGS, options=opts)))[-1]
    body = srv.chat_requests()[0]["body"]
    assert (body["temperature"], body["seed"], body["max_tokens"]) == (0.2, 7, 256)  # custom base URL -> max_tokens
    assert body["stream"] is True and body["stream_options"] == {"include_usage": True} and body["model"] == "gpt-4o"
    meta = final["_provider"]
    assert meta["params_applied"]["temperature"] == 0.2 and meta["params_applied"]["seed"] == 7
    assert "best effort" in meta["params_applied"]["seed_note"] and meta["params_applied"]["max_output_tokens"] == 256
    assert [i["name"] for i in meta["params_ignored"]] == ["num_ctx"] and "context" in meta["params_ignored"][0][
        "reason"
    ]


def test_official_endpoint_uses_max_completion_tokens():
    b = adapter(None)
    assert b.official
    body, applied, _ = b.build_body("o3", MSGS, {"num_predict": 100}, None, None, False)
    assert body["max_completion_tokens"] == 100 and "max_tokens" not in body and applied["max_output_tokens"] == 100
    gw = adapter("https://gw.example/v1")
    body, _, _ = gw.build_body("m", MSGS, {"num_predict": 100}, None, None, False)
    assert body["max_tokens"] == 100 and "max_completion_tokens" not in body


def test_reasoning_models_get_no_temperature_and_it_is_recorded():
    body, applied, ignored = adapter(None).build_body("o3", MSGS, {"temperature": 0.0, "seed": 1}, None, None, True)
    assert "temperature" not in body and "temperature" not in applied and body["seed"] == 1
    assert ignored == [{"name": "temperature", "reason": "reasoning models do not accept a temperature setting"}]


def test_think_setting_is_recorded_as_ignored_not_sent():
    body, _, ignored = adapter(None).build_body("m", MSGS, {}, True, None, False)
    assert "think" not in body and "reasoning_effort" not in body
    assert [i["name"] for i in ignored] == ["think"]
    assert adapter(None).build_body("m", MSGS, {}, None, None, False)[2] == []  # unset -> nothing to report


# ---------------------------------------------------------------- structured output
def test_strictify_adds_the_constraints_strict_mode_needs_and_does_not_mutate():
    schema = rubric_schema([{"name": "Relevance"}, {"name": "Fluency"}])
    original = json.dumps(schema, sort_keys=True)
    strict = strictify(schema)
    assert json.dumps(schema, sort_keys=True) == original  # input untouched

    def objects(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                yield node
            for v in node.values():
                yield from objects(v)

    objs = list(objects(strict))
    assert len(objs) == 4  # root, scores, and one object per criterion
    for o in objs:
        assert o["additionalProperties"] is False and o["required"] == list(o["properties"])
    assert "minimum" not in json.dumps(strict) and "maximum" not in json.dumps(strict)


async def test_structured_output_sends_a_strict_json_schema_and_the_judge_can_use_it(server):
    srv, url = server
    srv.judge_score = 4
    call = JudgeCall(
        task="Write a haiku", response="Rain taps the glass", rubric=[{"name": "Relevance"}, {"name": "Fluency"}]
    )
    res, metrics = await run_judge(adapter(url), "gpt-4o", call, think=None)
    assert res.outcome == "judged" and res.value == pytest.approx(0.75)
    assert res.detail["criteria"]["Relevance"]["score"] == 4 and res.detail["attempts"] == 1
    rf = srv.chat_requests()[0]["body"]["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"]["additionalProperties"] is False
    assert metrics and metrics[0]["eval_count"] is not None


def test_plain_json_format_string_maps_to_json_object():
    body, applied, _ = adapter(None).build_body("m", MSGS, {}, None, "json", False)
    assert body["response_format"] == {"type": "json_object"} and applied["structured_output"] == "json_object"


# ---------------------------------------------------------------- auth, urls, listing
async def test_key_goes_only_in_the_authorization_header(server):
    srv, url = server
    await collect(adapter(url).chat_stream(model="gpt-4o", messages=MSGS))
    rec = srv.chat_requests()[0]
    assert rec["headers"]["authorization"] == f"Bearer {KEY}" and rec["query"] == ""
    assert KEY not in json.dumps(rec["body"]) and KEY not in rec["path"]


async def test_missing_key_is_an_auth_error_naming_the_variable(server):
    srv, url = server
    with pytest.raises(ProviderAuthError, match="PROV_KEY is empty"):
        await collect(adapter(url, key=None).chat_stream(model="gpt-4o", messages=MSGS))
    assert srv.requests == []  # nothing was sent


async def test_key_is_read_at_call_time_so_rotation_takes_effect(server):
    srv, url = server
    b = adapter(url)
    await collect(b.chat_stream(model="gpt-4o", messages=MSGS))
    b.env["PROV_KEY"] = "rotated-key"
    with pytest.raises(ProviderAuthError):  # the fake still expects the old key
        await collect(b.chat_stream(model="gpt-4o", messages=MSGS))
    assert srv.chat_requests()[1]["headers"]["authorization"] == "Bearer rotated-key"


async def test_base_url_ending_in_v1_is_not_doubled(server):
    srv, url = server
    chunks = await collect(adapter(url + "/v1").chat_stream(model="gpt-4o", messages=MSGS))
    assert text_of(chunks) and srv.chat_requests()[0]["path"] == "/v1/chat/completions"


async def test_lists_models_sorted_and_ping_works(server):
    srv, url = server
    b = adapter(url)
    assert await b.list_models() == ["gpt-4o", "gpt-4o-mini", "o3"]
    await b.ping()
    with pytest.raises(ProviderAuthError):
        await adapter(url, key="wrong").ping()


# ---------------------------------------------------------------- failures while streaming
async def test_error_event_mid_stream_is_a_provider_error_without_a_final_chunk(server):
    srv, url = server
    srv.script.append(Step(kind="midstream_error"))
    seen = []
    with pytest.raises(ProviderUnavailable, match="mid-stream"):
        async for c in adapter(url).chat_stream(model="gpt-4o", messages=MSGS):
            seen.append(c)
    assert seen and not any(c["done"] for c in seen)


async def test_stream_that_ends_early_is_a_provider_error(server):
    srv, url = server
    srv.script.append(Step(kind="truncate"))
    with pytest.raises(ProviderUnavailable, match="ended before"):
        await collect(adapter(url).chat_stream(model="gpt-4o", messages=MSGS))


async def test_non_retryable_client_error_surfaces_the_providers_message(server):
    srv, url = server
    srv.script.append(Step(kind="status", status=400, body={"error": {"message": "Unsupported parameter: 'seed'"}}))
    with pytest.raises(ProviderError, match="Unsupported parameter") as ei:
        await collect(adapter(url).chat_stream(model="gpt-4o", messages=MSGS))
    assert ei.value.status == 400 and not isinstance(ei.value, ProviderUnavailable)
    assert len(srv.chat_requests()) == 1  # 400 is not retried


async def test_closing_the_generator_early_releases_the_connection(server):
    srv, url = server
    srv.answer = " ".join(["word"] * 50)
    agen = adapter(url).chat_stream(model="gpt-4o", messages=MSGS)
    first = await agen.__anext__()
    assert first["done"] is False
    await agen.aclose()  # cancellation path: must not raise or hang


# ---------------------------------------------------------------- parameters a model rejects (checked against current docs)
async def test_a_rejected_optional_parameter_is_dropped_retried_and_recorded(server):
    srv, url = server
    srv.script.append(
        Step(
            kind="status",
            status=400,
            body={"error": {"message": "Unsupported parameter: 'seed' is not supported with this model."}},
        )
    )
    chunks = await collect(adapter(url).chat_stream(model="o3", messages=MSGS, options={"seed": 3, "temperature": 0.5}))
    reqs = srv.chat_requests()
    assert (
        len(reqs) == 2
        and "seed" in reqs[0]["body"]
        and "seed" not in reqs[1]["body"]
        and reqs[1]["body"]["temperature"] == 0.5
    )
    meta = chunks[-1]["_provider"]
    assert "seed" not in meta["params_applied"] and "seed_note" not in meta["params_applied"]
    assert (
        meta["params_ignored"][0]["name"] == "seed"
        and "rejected by the provider" in meta["params_ignored"][0]["reason"]
    )
    assert text_of(chunks)


async def test_several_rejections_in_a_row_are_handled_one_at_a_time(server):
    srv, url = server
    msg = (
        "Unsupported value: 'temperature' does not support 0 with this model. Only the default (1) value is supported."
    )
    srv.script.extend(
        [
            Step(kind="status", status=400, body={"error": {"message": msg}}),
            Step(kind="status", status=400, body={"error": {"message": "Unsupported parameter: 'seed'"}}),
        ]
    )
    chunks = await collect(adapter(url).chat_stream(model="o3", messages=MSGS, options={"seed": 1, "temperature": 0}))
    assert [i["name"] for i in chunks[-1]["_provider"]["params_ignored"]] == ["temperature", "seed"]
    assert {"temperature", "seed"}.isdisjoint(srv.chat_requests()[-1]["body"])


async def test_max_tokens_is_renamed_when_the_model_requires_the_newer_name(server):
    srv, url = server
    msg = "Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead."
    srv.script.append(Step(kind="status", status=400, body={"error": {"message": msg}}))
    await collect(adapter(url).chat_stream(model="o3", messages=MSGS, options={"num_predict": 500}))
    last = srv.chat_requests()[-1]["body"]
    assert last["max_completion_tokens"] == 500 and "max_tokens" not in last


async def test_other_400s_and_non_droppable_parameters_are_not_swallowed(server):
    srv, url = server
    srv.script.append(Step(kind="status", status=400, body={"error": {"message": "Unsupported parameter: 'messages'"}}))
    with pytest.raises(ProviderError, match="messages"):
        await collect(adapter(url).chat_stream(model="o3", messages=MSGS))
    srv.script.append(
        Step(
            kind="status", status=400, body={"error": {"message": "This model's maximum context length is 8192 tokens"}}
        )
    )
    with pytest.raises(ProviderError, match="context length"):
        await collect(adapter(url).chat_stream(model="o3", messages=MSGS, options={"seed": 1}))


def test_strict_schema_also_drops_pattern_and_reasoning_details_are_read_from_either_name():
    strict = strictify({"type": "object", "properties": {"a": {"type": "string", "pattern": "^x", "minLength": 2}}})
    assert "pattern" not in json.dumps(strict) and "minLength" not in json.dumps(strict)


async def test_reasoning_tokens_under_the_responses_style_name_are_also_read(server):
    srv, url = server
    srv.script.append(
        Step(usage={"prompt_tokens": 3, "completion_tokens": 40, "output_tokens_details": {"reasoning_tokens": 25}})
    )
    final = (await collect(adapter(url).chat_stream(model="o3", messages=MSGS)))[-1]
    assert final["_provider"]["reasoning_tokens"] == 25
