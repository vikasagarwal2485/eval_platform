"""3.2: the fake provider servers behave like the real wire formats (self-test)."""

import json

import httpx
import pytest

from tests.fake_providers import FakeAnthropic, FakeOpenAI, Step


@pytest.fixture
def openai():
    srv = FakeOpenAI()
    url = srv.start()
    yield srv, url
    srv.stop()


@pytest.fixture
def anthropic():
    srv = FakeAnthropic()
    url = srv.start()
    yield srv, url
    srv.stop()


def sse_events(text: str):
    out = []
    for block in text.strip().split("\n\n"):
        event, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = line[6:]
        if data is not None:
            out.append((event, data if data == "[DONE]" else json.loads(data)))
    return out


def openai_post(url, body=None, key="test-key-123"):
    body = body or {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    return httpx.post(f"{url}/v1/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"}, timeout=10)


def anthropic_post(url, body=None, key="test-key-123", version=True):
    body = body or {
        "model": "claude",
        "max_tokens": 100,
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }
    headers = {"x-api-key": key, **({"anthropic-version": "2023-06-01"} if version else {})}
    return httpx.post(f"{url}/v1/messages", json=body, headers=headers, timeout=10)


# ---------------------------------------------------------------- OpenAI
def test_openai_streams_text_usage_and_done(openai):
    srv, url = openai
    srv.answer = "Final answer: 5"
    r = openai_post(url)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    ev = sse_events(r.text)
    assert ev[-1][1] == "[DONE]"
    deltas = [e[1]["choices"][0]["delta"].get("content", "") for e in ev[:-1] if e[1]["choices"]]
    assert "".join(deltas) == "Final answer: 5"
    usage = [e[1]["usage"] for e in ev[:-1] if e[1].get("usage")]
    assert usage and usage[0]["prompt_tokens"] == 21 and usage[0]["completion_tokens"] == 3
    assert ev[0][1]["model"] == "gpt-4o-2024-08-06"


def test_openai_captures_auth_header_and_body_and_never_a_query_key(openai):
    srv, url = openai
    openai_post(url)
    rec = srv.chat_requests()[0]
    assert rec["headers"]["authorization"] == "Bearer test-key-123"
    assert rec["body"]["stream"] is True and rec["body"]["messages"][0]["content"] == "hi"
    assert rec["query"] == ""


def test_openai_rejects_a_wrong_key_with_401(openai):
    srv, url = openai
    r = openai_post(url, key="wrong")
    assert r.status_code == 401 and "Incorrect API key" in r.json()["error"]["message"]


def test_openai_structured_output_returns_json_for_the_requested_criteria(openai):
    srv, url = openai
    schema = {
        "type": "object",
        "properties": {"scores": {"type": "object", "properties": {"Relevance": {}, "Fluency": {}}}},
    }
    body = {
        "model": "gpt-4o",
        "messages": [],
        "stream": True,
        "stream_options": {"include_usage": True},
        "response_format": {"type": "json_schema", "json_schema": {"name": "s", "schema": schema}},
    }
    ev = sse_events(openai_post(url, body).text)
    text = "".join(e[1]["choices"][0]["delta"].get("content", "") for e in ev[:-1] if e[1]["choices"])
    assert json.loads(text)["scores"]["Relevance"] == {"score": 4, "reason": "fine"}


def test_openai_scripted_rate_limit_then_success(openai):
    srv, url = openai
    srv.script.extend([Step(kind="status", status=429, headers={"retry-after": "2"})])
    r = openai_post(url)
    assert r.status_code == 429 and r.headers["retry-after"] == "2"
    assert openai_post(url).status_code == 200  # script exhausted -> normal answers again


def test_openai_midstream_error_and_truncation(openai):
    srv, url = openai
    srv.script.extend([Step(kind="midstream_error"), Step(kind="truncate")])
    ev = sse_events(openai_post(url).text)
    assert any("error" in e[1] for e in ev if isinstance(e[1], dict))
    ev = sse_events(openai_post(url).text)
    assert ev[-1][1] != "[DONE]"  # ended without the terminator


def test_openai_models_endpoint(openai):
    srv, url = openai
    r = httpx.get(f"{url}/v1/models", headers={"Authorization": "Bearer test-key-123"})
    assert [m["id"] for m in r.json()["data"]] == ["gpt-4o", "gpt-4o-mini", "o3"]
    assert httpx.get(f"{url}/v1/models", headers={"Authorization": "Bearer nope"}).status_code == 401


# ---------------------------------------------------------------- Anthropic
def test_anthropic_streams_events_in_order_with_usage(anthropic):
    srv, url = anthropic
    srv.answer = "Final answer: 5"
    r = anthropic_post(url)
    ev = sse_events(r.text)
    assert [e[0] for e in ev][0] == "message_start" and ev[-1][0] == "message_stop"
    assert (
        ev[0][1]["message"]["usage"]["input_tokens"] == 25
        and ev[0][1]["message"]["model"] == "claude-sonnet-4-20250514"
    )
    text = "".join(e[1]["delta"]["text"] for e in ev if e[0] == "content_block_delta")
    assert text == "Final answer: 5"
    delta = next(e[1] for e in ev if e[0] == "message_delta")
    assert delta["usage"]["output_tokens"] == 3 and delta["delta"]["stop_reason"] == "end_turn"


def test_anthropic_requires_the_key_and_version_headers(anthropic):
    srv, url = anthropic
    assert anthropic_post(url).status_code == 200
    rec = srv.chat_requests()[0]
    assert rec["headers"]["x-api-key"] == "test-key-123" and rec["headers"]["anthropic-version"] == "2023-06-01"
    assert "authorization" not in rec["headers"] and rec["query"] == ""
    bad = anthropic_post(url, key="wrong")
    assert bad.status_code == 401 and bad.json()["error"]["type"] == "authentication_error"
    assert anthropic_post(url, version=False).status_code == 401


def test_anthropic_thinking_blocks_when_enabled(anthropic):
    srv, url = anthropic
    body = {
        "model": "c",
        "max_tokens": 2000,
        "stream": True,
        "messages": [],
        "thinking": {"type": "enabled", "budget_tokens": 1024},
    }
    ev = sse_events(anthropic_post(url, body).text)
    kinds = [e[1]["delta"]["type"] for e in ev if e[0] == "content_block_delta"]
    assert kinds[0] == "thinking_delta" and "text_delta" in kinds


def test_anthropic_forced_tool_call_streams_the_json_input(anthropic):
    srv, url = anthropic
    schema = {"type": "object", "properties": {"scores": {"type": "object", "properties": {"Relevance": {}}}}}
    body = {
        "model": "c",
        "max_tokens": 500,
        "stream": True,
        "messages": [],
        "tools": [{"name": "record_scores", "description": "d", "input_schema": schema}],
        "tool_choice": {"type": "tool", "name": "record_scores"},
    }
    ev = sse_events(anthropic_post(url, body).text)
    assert any(e[0] == "content_block_start" and e[1]["content_block"]["type"] == "tool_use" for e in ev)
    partial = "".join(e[1]["delta"]["partial_json"] for e in ev if e[0] == "content_block_delta")
    assert json.loads(partial)["scores"]["Relevance"]["score"] == 4


def test_anthropic_scripted_errors_and_midstream_failure(anthropic):
    srv, url = anthropic
    srv.script.extend(
        [
            Step(kind="status", status=529),
            Step(kind="status", status=429, headers={"retry-after": "1"}),
            Step(kind="midstream_error"),
        ]
    )
    assert anthropic_post(url).json()["error"]["type"] == "overloaded_error"
    r = anthropic_post(url)
    assert r.status_code == 429 and r.headers["retry-after"] == "1"
    ev = sse_events(anthropic_post(url).text)
    assert ev[-1][0] == "error"


def test_anthropic_models_endpoint(anthropic):
    srv, url = anthropic
    r = httpx.get(f"{url}/v1/models", headers={"x-api-key": "test-key-123", "anthropic-version": "2023-06-01"})
    assert [m["id"] for m in r.json()["data"]] == ["claude-sonnet-4-20250514", "claude-3-5-haiku-20241022"]
