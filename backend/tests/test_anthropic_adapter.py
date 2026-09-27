"""3.4: Anthropic adapter contract tests against the fake server (formats re-checked against current docs)."""

import json

import httpx
import pytest

from app.core.scoring.judge import JudgeCall, run_judge
from app.providers.anthropic import AnthropicBackend, thinking_config
from app.providers.errors import ProviderAuthError, ProviderRateLimited, ProviderUnavailable
from tests.fake_providers import FakeAnthropic, Step
from tests.provider_helpers import KEY, collect, make, text_of, thinking_of

MSGS = [{"role": "user", "content": "hi"}]


@pytest.fixture
def server():
    srv = FakeAnthropic()
    url = srv.start()
    yield srv, url
    srv.stop()


def adapter(url, **kw):
    return make(AnthropicBackend, "anthropic", url, **kw)


def sse(*events) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def mock(body: bytes):
    return httpx.MockTransport(
        lambda req: httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})
    )


# ---------------------------------------------------------------- text and usage
async def test_streams_text_and_reports_cumulative_usage_and_model_version(server):
    srv, url = server
    srv.answer = "Final answer: 5"
    chunks = await collect(
        adapter(url).chat_stream(model="claude", messages=MSGS, options={"temperature": 0, "num_predict": 300})
    )
    assert text_of(chunks) == "Final answer: 5" and chunks[-1]["done"] and not any(c["done"] for c in chunks[:-1])
    final = chunks[-1]
    assert final["prompt_eval_count"] == 25 and final["eval_count"] == 3 and final["done_reason"] == "stop"
    assert not {"eval_duration", "load_duration", "total_duration"} & set(final)
    meta = final["_provider"]
    assert (
        meta["model_version"] == "claude-sonnet-4-20250514"
        and meta["finish_reason"] == "end_turn"
        and meta["attempts"] == 1
    )


async def test_ping_and_signature_events_are_ignored():
    body = sse(
        {"type": "message_start", "message": {"model": "m1", "usage": {"input_tokens": 7, "output_tokens": 1}}},
        {"type": "ping"},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hi"}},
        {"type": "ping"},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}, "usage": {"output_tokens": 15}},
        {"type": "message_stop"},
    )
    chunks = await collect(adapter("http://x.test", transport=mock(body)).chat_stream(model="m", messages=MSGS))
    assert text_of(chunks) == "Hi" and chunks[-1]["eval_count"] == 15 and chunks[-1]["done_reason"] == "length"


async def test_cache_token_counts_are_part_of_the_input_total():
    body = sse(
        {
            "type": "message_start",
            "message": {
                "model": "m",
                "usage": {"input_tokens": 10, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 5},
            },
        },
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 3}},
        {"type": "message_stop"},
    )
    final = (await collect(adapter("http://x.test", transport=mock(body)).chat_stream(model="m", messages=MSGS)))[-1]
    assert final["prompt_eval_count"] == 115


# ---------------------------------------------------------------- request shape and parameters
async def test_system_prompt_is_separate_and_headers_are_correct(server):
    srv, url = server
    msgs = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "hi"}]
    await collect(adapter(url).chat_stream(model="claude", messages=msgs))
    rec = srv.chat_requests()[0]
    assert rec["body"]["system"] == "Be brief." and rec["body"]["messages"] == [{"role": "user", "content": "hi"}]
    assert rec["headers"]["x-api-key"] == KEY and rec["headers"]["anthropic-version"] == "2023-06-01"
    assert "authorization" not in rec["headers"] and rec["query"] == "" and KEY not in json.dumps(rec["body"])


async def test_max_tokens_is_always_sent_and_seed_and_context_are_recorded_as_ignored(server):
    srv, url = server
    final = (
        await collect(
            adapter(url).chat_stream(
                model="claude", messages=MSGS, options={"temperature": 0.3, "seed": 9, "num_ctx": 8192}
            )
        )
    )[-1]
    body = srv.chat_requests()[0]["body"]
    assert body["max_tokens"] == 4096 and body["temperature"] == 0.3 and "seed" not in body and body["stream"] is True
    meta = final["_provider"]
    assert meta["params_applied"]["temperature"] == 0.3 and meta["params_applied"]["max_output_tokens"] == 4096
    assert {i["name"] for i in meta["params_ignored"]} == {"seed", "num_ctx"}
    assert "seed" in next(i for i in meta["params_ignored"] if i["name"] == "seed")["reason"]


# ---------------------------------------------------------------- thinking
def test_thinking_budget_rules():
    assert thinking_config("enabled", 4096) == {"type": "enabled", "budget_tokens": 2048}
    assert thinking_config("enabled", 1500) == {"type": "enabled", "budget_tokens": 1024}
    assert thinking_config("enabled", 1024) is None  # budget must be >= 1024 and < max_tokens
    assert thinking_config("adaptive", 100) == {"type": "adaptive"}
    cfg = thinking_config("enabled", 65536)
    assert cfg["budget_tokens"] < 65536


async def test_thinking_enabled_streams_reasoning_separately_and_drops_temperature(server):
    srv, url = server
    srv.script.append(
        Step(
            thinking="Let me work it out.",
            usage={"output_tokens": 300, "output_tokens_details": {"thinking_tokens": 210}},
        )
    )
    chunks = await collect(
        adapter(url).chat_stream(
            model="claude", messages=MSGS, options={"temperature": 0, "num_predict": 4000}, think=True, reasoning=True
        )
    )
    body = srv.chat_requests()[0]["body"]
    assert body["thinking"] == {"type": "enabled", "budget_tokens": 2000} and "temperature" not in body
    assert thinking_of(chunks) == "Let me work it out." and text_of(chunks) == "Hello from the fake provider"
    meta = chunks[-1]["_provider"]
    assert meta["reasoning_tokens"] == 210 and chunks[-1]["eval_count"] == 300  # exact, from output_tokens_details
    assert meta["params_applied"]["thinking"].startswith("enabled (budget 2000")
    assert any(i["name"] == "temperature" and "thinking" in i["reason"] for i in meta["params_ignored"])


async def test_thinking_is_only_sent_for_models_flagged_as_reasoning(server):
    srv, url = server
    final = (await collect(adapter(url).chat_stream(model="claude", messages=MSGS, think=True, reasoning=False)))[-1]
    assert "thinking" not in srv.chat_requests()[0]["body"]
    assert any(i["name"] == "think" and "not flagged" in i["reason"] for i in final["_provider"]["params_ignored"])
    await collect(adapter(url).chat_stream(model="claude", messages=MSGS, think=None, reasoning=True))
    assert "thinking" not in srv.chat_requests()[1]["body"]  # the run's thinking option is off


async def test_thinking_is_skipped_when_the_token_limit_is_too_low(server):
    srv, url = server
    final = (
        await collect(
            adapter(url).chat_stream(
                model="claude", messages=MSGS, options={"num_predict": 800}, think=True, reasoning=True
            )
        )
    )[-1]
    assert "thinking" not in srv.chat_requests()[0]["body"]
    assert any("1,024" in i["reason"] for i in final["_provider"]["params_ignored"])


async def test_falls_back_to_adaptive_when_the_model_rejects_manual_thinking_and_remembers_it(server):
    srv, url = server
    msg = '"thinking.type.enabled" is not supported for this model. Use "thinking.type.adaptive" and "output_config.effort" to control thinking behavior.'
    srv.script.append(
        Step(
            kind="status",
            status=400,
            body={"type": "error", "error": {"type": "invalid_request_error", "message": msg}},
        )
    )
    b = adapter(url)
    chunks = await collect(
        b.chat_stream(model="claude-new", messages=MSGS, options={"num_predict": 4000}, think=True, reasoning=True)
    )
    reqs = srv.chat_requests()
    assert [r["body"]["thinking"]["type"] for r in reqs] == ["enabled", "adaptive"] and "budget_tokens" not in reqs[1][
        "body"
    ]["thinking"]
    meta = chunks[-1]["_provider"]
    assert meta["params_applied"]["thinking"] == "adaptive"
    assert any(i["name"] == "thinking_mode" and "'enabled' was rejected" in i["reason"] for i in meta["params_ignored"])
    await collect(
        b.chat_stream(model="claude-new", messages=MSGS, options={"num_predict": 4000}, think=True, reasoning=True)
    )
    assert (
        srv.chat_requests()[-1]["body"]["thinking"]["type"] == "adaptive" and len(srv.chat_requests()) == 3
    )  # learned, no retry


async def test_runs_without_thinking_when_the_model_accepts_neither_mode(server):
    srv, url = server
    for mode in ("enabled", "adaptive"):
        m = f'"thinking.type.{mode}" is not supported for this model.'
        srv.script.append(Step(kind="status", status=400, body={"type": "error", "error": {"message": m}}))
    final = (
        await collect(
            adapter(url).chat_stream(
                model="c", messages=MSGS, options={"num_predict": 4000}, think=True, reasoning=True
            )
        )
    )[-1]
    assert "thinking" not in srv.chat_requests()[-1]["body"]
    assert any("neither thinking mode" in i["reason"] for i in final["_provider"]["params_ignored"])


# ---------------------------------------------------------------- structured output
async def test_structured_judge_output_uses_a_forced_tool_call(server):
    srv, url = server
    srv.judge_score = 5
    call = JudgeCall(
        task="Write a haiku", response="Rain taps the glass", rubric=[{"name": "Relevance"}, {"name": "Fluency"}]
    )
    res, metrics = await run_judge(adapter(url), "claude", call, think=False)
    assert res.outcome == "judged" and res.value == pytest.approx(1.0)
    body = srv.chat_requests()[0]["body"]
    assert (
        body["tool_choice"] == {"type": "tool", "name": "record_scores"} and body["tools"][0]["name"] == "record_scores"
    )
    assert set(body["tools"][0]["input_schema"]["properties"]["scores"]["properties"]) == {"Relevance", "Fluency"}
    assert "thinking" not in body and metrics


async def test_thinking_is_dropped_when_combined_with_structured_output(server):
    srv, url = server
    schema = {"type": "object", "properties": {"scores": {"type": "object", "properties": {"Q": {}}}}}
    final = (
        await collect(
            adapter(url).chat_stream(
                model="c", messages=MSGS, options={"num_predict": 4000}, think=True, reasoning=True, format=schema
            )
        )
    )[-1]
    assert "thinking" not in srv.chat_requests()[0]["body"]
    assert any(i["name"] == "think" and "forced tool" in i["reason"] for i in final["_provider"]["params_ignored"])


# ---------------------------------------------------------------- errors inside the stream
@pytest.mark.parametrize(
    "etype,exc",
    [
        ("overloaded_error", ProviderUnavailable),
        ("rate_limit_error", ProviderRateLimited),
        ("authentication_error", ProviderAuthError),
        ("api_error", ProviderUnavailable),
    ],
)
async def test_error_events_map_to_provider_errors(etype, exc):
    body = sse(
        {"type": "message_start", "message": {"model": "m", "usage": {"input_tokens": 1}}},
        {"type": "error", "error": {"type": etype, "message": "boom"}},
    )
    with pytest.raises(exc, match="boom"):
        await collect(adapter("http://x.test", transport=mock(body)).chat_stream(model="m", messages=MSGS))


async def test_stream_ending_without_message_stop_is_an_error(server):
    srv, url = server
    srv.script.append(Step(kind="truncate"))
    with pytest.raises(ProviderUnavailable, match="ended before"):
        await collect(adapter(url).chat_stream(model="claude", messages=MSGS))


async def test_midstream_overload_from_the_fake_server(server):
    srv, url = server
    srv.script.append(Step(kind="midstream_error"))
    with pytest.raises(ProviderUnavailable, match="Overloaded"):
        await collect(adapter(url).chat_stream(model="claude", messages=MSGS))


# ---------------------------------------------------------------- models and connectivity
async def test_lists_models_sorted_and_ping_works(server):
    srv, url = server
    b = adapter(url)
    assert await b.list_models() == ["claude-3-5-haiku-20241022", "claude-sonnet-4-20250514"]
    await b.ping()
    with pytest.raises(ProviderAuthError):
        await adapter(url, key="wrong").ping()


async def test_model_list_follows_pagination():
    pages = {
        "": {"data": [{"id": "b"}, {"id": "a"}], "has_more": True},
        "a": {"data": [{"id": "c"}], "has_more": False},
    }

    def handler(req: httpx.Request):
        return httpx.Response(
            200,
            json=pages[req.url.params.get("after_id", "")]
            if req.url.params.get("after_id", "") in pages
            else pages["a"],
        )

    # first page ends with id 'a' (the last item returned), so the next request asks after_id=a
    b = adapter("http://x.test", transport=httpx.MockTransport(handler))
    assert await b.list_models() == ["a", "b", "c"]


async def test_missing_key_never_sends_anything(server):
    srv, url = server
    with pytest.raises(ProviderAuthError, match="PROV_KEY is empty"):
        await collect(adapter(url, key=None).chat_stream(model="claude", messages=MSGS))
    assert srv.requests == []
