"""Contract tests for the Ollama client against recorded fixtures."""

import json

import httpx
import pytest

from app.ollama.client import HttpOllamaClient, OllamaError, OllamaUnreachable, is_thinking_capable
from tests.fakes import FIXTURES, load_fixture


def make_client(handler) -> HttpOllamaClient:
    return HttpOllamaClient("http://ollama.test", transport=httpx.MockTransport(handler))


async def test_version_tags_show_ps():
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/api/version":
            return httpx.Response(200, json=load_fixture("version.json"))
        if path == "/api/tags":
            return httpx.Response(200, json=load_fixture("tags.json"))
        if path == "/api/show":
            assert json.loads(req.content)["model"] == "qwen3:8b"
            return httpx.Response(200, json=load_fixture("show.json"))
        if path == "/api/ps":
            return httpx.Response(200, json=load_fixture("ps.json"))
        return httpx.Response(404)

    c = make_client(handler)
    assert await c.version()
    models = await c.list_models()
    assert models[0]["name"] == "qwen3:8b"
    assert is_thinking_capable((await c.show("qwen3:8b")).get("capabilities"))
    ps = await c.ps()
    assert ps[0]["size_vram"] > 0


async def test_chat_stream_parses_ndjson_fixture():
    body = (FIXTURES / "chat_stream_think.ndjson").read_bytes()

    def handler(req: httpx.Request) -> httpx.Response:
        payload = json.loads(req.content)
        assert payload["stream"] is True and payload["think"] is True
        assert payload["options"]["temperature"] == 0
        return httpx.Response(200, content=body)

    c = make_client(handler)
    chunks = [
        ch
        async for ch in c.chat_stream(
            model="qwen3:8b",
            messages=[{"role": "user", "content": "hi"}],
            options={"temperature": 0},
            think=True,
        )
    ]
    assert chunks[-1]["done"] is True
    assert chunks[-1]["eval_count"] > 0
    assert "".join(c["message"].get("content", "") for c in chunks).startswith("Final answer")
    assert any(c["message"].get("thinking") for c in chunks)


async def test_unreachable_raises_specific_error():
    def handler(req):
        raise httpx.ConnectError("refused")

    c = make_client(handler)
    with pytest.raises(OllamaUnreachable):
        await c.list_models()
    with pytest.raises(OllamaUnreachable):
        async for _ in c.chat_stream(model="m", messages=[]):
            pass


async def test_http_error_and_error_chunk():
    def handler(req):
        if req.url.path == "/api/show":
            return httpx.Response(404, json={"error": "model 'x' not found"})
        return httpx.Response(200, content=b'{"error":"model requires more system memory"}\n')

    c = make_client(handler)
    with pytest.raises(OllamaError, match="not found") as ei:
        await c.show("x")
    assert ei.value.status == 404
    with pytest.raises(OllamaError, match="memory"):
        async for _ in c.chat_stream(model="m", messages=[]):
            pass


async def test_unload_sends_keep_alive_zero():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"done": True})

    await make_client(handler).unload("qwen3:8b")
    assert seen["keep_alive"] == 0 and seen["model"] == "qwen3:8b"
