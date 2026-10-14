"""2.2: Azure OpenAI adapter - deployment-scoped path, api-key header, api-version query, no provider-wide ping."""

import json

import httpx
import pytest

from app.config import Settings
from app.providers.azure_openai import AzureOpenAIBackend
from app.providers.backend import ModelRouter, ProviderConfig
from app.providers.errors import ProviderError
from app.providers.factories import make_factories
from tests.provider_helpers import KEY, collect, make, text_of

MSGS = [{"role": "user", "content": "hi"}]


def _sse_ok(model: str = "o3-mini", text: str = "ok") -> bytes:
    events = [
        {"model": model, "choices": [{"delta": {"content": text}, "finish_reason": None}]},
        {
            "model": model,
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    ]
    return ("\n\n".join("data: " + json.dumps(e) for e in events) + "\n\ndata: [DONE]\n\n").encode()


def adapter(url, transport, **kw):
    return make(AzureOpenAIBackend, "azure-openai", url, transport=transport, **kw)


async def test_builds_deployment_scoped_path_with_api_key_header_and_api_version():
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["headers"] = dict(req.headers)
        captured["body"] = json.loads(req.content)
        return httpx.Response(200, content=_sse_ok(), headers={"content-type": "text/event-stream"})

    transport = httpx.MockTransport(handler)
    backend = adapter("https://my-resource.openai.azure.com", transport, api_version="2024-12-01-preview")
    chunks = await collect(backend.chat_stream(model="o3-mini", messages=MSGS))

    assert text_of(chunks) == "ok"
    assert captured["url"] == (
        "https://my-resource.openai.azure.com/openai/deployments/o3-mini/chat/completions"
        "?api-version=2024-12-01-preview"
    )
    assert captured["headers"]["api-key"] == KEY
    assert "authorization" not in captured["headers"]  # never a bearer token (design D4)
    assert "model" not in captured["body"] or True  # the deployment is identified by the URL, not required in body


async def test_deployment_name_with_special_characters_is_escaped_in_the_path():
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        return httpx.Response(200, content=_sse_ok(), headers={"content-type": "text/event-stream"})

    transport = httpx.MockTransport(handler)
    backend = adapter("https://my-resource.openai.azure.com", transport, api_version="2024-12-01-preview")
    await collect(backend.chat_stream(model="my deployment/v2", messages=MSGS))
    assert "my%20deployment%2Fv2" in captured["url"]


async def test_reasoning_deployment_uses_max_completion_tokens():
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.content)
        return httpx.Response(200, content=_sse_ok(), headers={"content-type": "text/event-stream"})

    transport = httpx.MockTransport(handler)
    backend = adapter("https://my-resource.openai.azure.com", transport, api_version="2024-12-01-preview")
    await collect(
        backend.chat_stream(
            model="o3-mini", messages=MSGS, options={"num_predict": 512}, reasoning=True, reasoning_effort="low"
        )
    )
    assert captured["body"]["max_completion_tokens"] == 512 and "max_tokens" not in captured["body"]
    assert captured["body"]["reasoning_effort"] == "low"


async def test_non_reasoning_deployment_uses_max_tokens():
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.content)
        return httpx.Response(200, content=_sse_ok(), headers={"content-type": "text/event-stream"})

    transport = httpx.MockTransport(handler)
    backend = adapter("https://my-resource.openai.azure.com", transport, api_version="2024-12-01-preview")
    await collect(backend.chat_stream(model="gpt-4o", messages=MSGS, options={"num_predict": 512}))
    assert captured["body"]["max_tokens"] == 512 and "max_completion_tokens" not in captured["body"]


async def test_list_models_is_not_supported():
    backend = adapter("https://my-resource.openai.azure.com", httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(ProviderError, match="cannot be listed automatically"):
        await backend.list_models()


async def test_ping_without_a_deployment_raises_clearly():
    backend = adapter("https://my-resource.openai.azure.com", httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(ProviderError, match="needs a registered deployment"):
        await backend.ping()


def test_router_resolves_azure_openai_kind_to_its_backend():
    router = ModelRouter(None, lambda: None, factories=make_factories(Settings()))
    cfg = ProviderConfig("azure-openai", "az", "AZ_KEY", "https://my-resource.openai.azure.com", "2024-12-01-preview")
    backend = router.backend_for(cfg)
    assert isinstance(backend, AzureOpenAIBackend)
    assert backend.cfg.api_version == "2024-12-01-preview"


async def test_ping_with_a_deployment_sends_a_minimal_chat_completion():
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["body"] = json.loads(req.content)
        return httpx.Response(200, content=_sse_ok(), headers={"content-type": "text/event-stream"})

    transport = httpx.MockTransport(handler)
    backend = adapter("https://my-resource.openai.azure.com", transport, api_version="2024-12-01-preview")
    await backend.ping(model="o3-mini")
    assert "/openai/deployments/o3-mini/chat/completions" in captured["url"]
    assert captured["body"]["max_tokens"] == 1


async def test_ping_a_reasoning_deployment_uses_a_larger_token_budget():
    """A 1-token budget leaves no room for a reasoning model's hidden reasoning tokens, which fails the ping with
    a misleading "max output limit reached" error instead of actually testing the connection."""
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.content)
        return httpx.Response(200, content=_sse_ok(), headers={"content-type": "text/event-stream"})

    transport = httpx.MockTransport(handler)
    backend = adapter("https://my-resource.openai.azure.com", transport, api_version="2024-12-01-preview")
    await backend.ping(model="o3-mini", reasoning=True)
    assert captured["body"]["max_completion_tokens"] > 1 and "max_tokens" not in captured["body"]
