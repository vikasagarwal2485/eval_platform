"""3.1: the model router and capability flags."""

import pytest

from app import repo
from app.providers.backend import CLOUD_CAPS, LOCAL_CAPS, ModelRouter, caps_for_kind
from app.providers.errors import ProviderError
from app.providers.secrets import KeyProvider
from tests.fakes import FakeOllama, make_stream, make_tag


class FakeBackend:
    """A stand-in enterprise backend that records how it is called."""

    def __init__(self, cfg, router):
        self.kind, self.cfg, self.calls, self.closed = cfg.kind, cfg, [], False

    async def chat_stream(
        self, *, model, messages, options=None, think=None, format=None, keep_alive=None, reasoning=False
    ):
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "options": options,
                "think": think,
                "format": format,
                "reasoning": reasoning,
            }
        )
        for c in make_stream(f"cloud:{self.cfg.name}:{model}"):
            yield c

    async def list_models(self):
        return []

    async def ping(self):
        pass

    async def aclose(self):
        self.closed = True


@pytest.fixture
def router(session_factory):
    with session_factory() as s:
        p = repo.create_provider(s, kind="openai", name="oa", key_env="OA_KEY", base_url=None, ack_at=None)
        q = repo.create_provider(
            s, kind="anthropic", name="an", key_env="AN_KEY", base_url="https://gw.example", ack_at=None
        )
        repo.add_registered_model(s, p.id, "gpt-4o")
        repo.add_registered_model(s, p.id, "o3", reasoning=True)
        repo.add_registered_model(s, q.id, "gpt-4o")  # same id, different provider
        repo.add_registered_model(s, p.id, "off", enabled=False)
        s.commit()
    ollama = FakeOllama([make_tag("qwen3:8b")])
    r = ModelRouter(
        ollama,
        session_factory,
        KeyProvider({"OA_KEY": "k1"}),
        factories={"openai": FakeBackend, "anthropic": FakeBackend},
    )
    r.fake_ollama = ollama
    return r


async def collect(agen):
    return [c async for c in agen]


# ---------------------------------------------------------------- capabilities
def test_capability_flags():
    local = caps_for_kind(None)
    assert local == LOCAL_CAPS
    assert local.warmup and local.unload and local.footprint and local.seed and local.context_size
    oa, an = caps_for_kind("openai"), caps_for_kind("anthropic")
    assert not (oa.warmup or oa.unload or oa.footprint or oa.context_size) and oa.seed is True
    assert not (an.warmup or an.unload or an.footprint or an.context_size) and an.seed is False
    assert not any([caps_for_kind("mystery").warmup, caps_for_kind("mystery").unload, caps_for_kind("mystery").seed])
    assert set(CLOUD_CAPS) == {"openai", "anthropic"}


# ---------------------------------------------------------------- routing
async def test_local_names_go_to_ollama_unchanged(router):
    chunks = await collect(
        router.chat_stream(
            model="qwen3:8b",
            messages=[{"role": "user", "content": "hi"}],
            options={"temperature": 0},
            think=True,
            format={"type": "object"},
        )
    )
    assert chunks[-1]["done"]
    assert router.fake_ollama.calls == [("chat", "qwen3:8b", {"temperature": 0}, True, {"type": "object"})]
    assert router._backends == {}  # no enterprise backend was even built


async def test_cloud_refs_go_to_their_backend_with_the_bare_model_id(router):
    chunks = await collect(
        router.chat_stream(
            model="@oa/gpt-4o", messages=[{"role": "user", "content": "hi"}], options={"temperature": 0.1}
        )
    )
    assert "".join(c["message"]["content"] for c in chunks) == "cloud:oa:gpt-4o"
    backend = next(iter(router._backends.values()))
    assert backend.calls[0]["model"] == "gpt-4o" and backend.calls[0]["options"] == {"temperature": 0.1}
    assert router.fake_ollama.calls == []  # Ollama untouched


async def test_reasoning_flag_comes_from_the_registry(router):
    await collect(router.chat_stream(model="@oa/o3", messages=[]))
    await collect(router.chat_stream(model="@oa/gpt-4o", messages=[]))
    calls = next(iter(router._backends.values())).calls
    assert [c["reasoning"] for c in calls] == [True, False]


async def test_same_model_id_under_two_providers_uses_two_backends(router):
    a = await collect(router.chat_stream(model="@oa/gpt-4o", messages=[]))
    b = await collect(router.chat_stream(model="@an/gpt-4o", messages=[]))
    assert a[0]["message"]["content"].startswith("cloud:oa") and b[0]["message"]["content"].startswith("cloud:an")
    assert len(router._backends) == 2
    again = await collect(router.chat_stream(model="@oa/gpt-4o", messages=[]))
    assert again and len(router._backends) == 2  # instances are reused per provider


async def test_backend_is_rebuilt_when_the_provider_configuration_changes(router, session_factory):
    await collect(router.chat_stream(model="@oa/gpt-4o", messages=[]))
    first = next(iter(router._backends.values()))
    with session_factory() as s:
        repo.update_provider(s, repo.get_provider_by_name(s, "oa").id, base_url="https://new.example/v1")
        s.commit()
    await collect(router.chat_stream(model="@oa/gpt-4o", messages=[]))
    backends = [b for b in router._backends.values() if b.cfg.name == "oa"]
    assert len(backends) == 1 and backends[0] is not first and backends[0].cfg.base_url == "https://new.example/v1"


@pytest.mark.parametrize(
    "ref,fragment", [("@ghost/x", "not registered"), ("@oa/nope", "not registered under provider")]
)
async def test_unresolvable_cloud_refs_raise_a_provider_error(router, ref, fragment):
    with pytest.raises(ProviderError, match=fragment):
        await collect(router.chat_stream(model=ref, messages=[]))


async def test_missing_adapter_kind_is_a_provider_error(session_factory):
    with session_factory() as s:
        p = repo.create_provider(s, kind="openai", name="oa", key_env="K", base_url=None, ack_at=None)
        repo.add_registered_model(s, p.id, "m")
        s.commit()
    r = ModelRouter(FakeOllama(), session_factory, KeyProvider({}), factories={})
    with pytest.raises(ProviderError, match="No adapter"):
        await collect(r.chat_stream(model="@oa/m", messages=[]))


async def test_unload_only_touches_local_models(router):
    await router.unload("qwen3:8b")
    await router.unload("@oa/gpt-4o")
    assert router.fake_ollama.calls == [("unload", "qwen3:8b")]


async def test_version_ps_and_list_delegate_to_ollama(router):
    assert await router.version() == "0.34.2"
    assert await router.ps() == []
    assert [m["name"] for m in await router.list_models()] == ["qwen3:8b"]
    assert (await router.show("qwen3:8b"))["capabilities"] == ["completion"]


async def test_aclose_closes_every_backend(router):
    await collect(router.chat_stream(model="@oa/gpt-4o", messages=[]))
    backend = next(iter(router._backends.values()))
    await router.aclose()
    assert backend.closed


# ---------------------------------------------------------------- preflight
def test_preflight_reports_every_problem_with_a_reason(router):
    problems = router.preflight(["qwen3:8b", "@oa/gpt-4o", "@oa/off", "@an/gpt-4o", "@ghost/x", "@oa/missing", "@bad"])
    by_ref = {p.ref: p.reason for p in problems}
    assert "@oa/gpt-4o" not in by_ref and "qwen3:8b" not in by_ref  # available; local names are not checked here
    assert by_ref["@oa/off"] == "model is disabled"
    assert "AN_KEY" in by_ref["@an/gpt-4o"] and "API key not set" in by_ref["@an/gpt-4o"]
    assert "not registered" in by_ref["@ghost/x"] and "provider 'ghost'" in by_ref["@ghost/x"]
    assert "not registered under 'oa'" in by_ref["@oa/missing"]
    assert "not a valid model reference" in by_ref["@bad"]


def test_preflight_ok_and_deduplicates(router):
    assert router.preflight(["@oa/gpt-4o", "@oa/gpt-4o", "qwen3:8b"]) == []
    assert len(router.preflight(["@an/gpt-4o", "@an/gpt-4o"])) == 1


def test_preflight_sees_a_key_added_later(session_factory):
    env = {}
    with session_factory() as s:
        p = repo.create_provider(s, kind="openai", name="oa", key_env="K", base_url=None, ack_at=None)
        repo.add_registered_model(s, p.id, "m")
        s.commit()
    r = ModelRouter(FakeOllama(), session_factory, KeyProvider(env), factories={})
    assert r.preflight(["@oa/m"])[0].reason.startswith("API key not set")
    env["K"] = "now-set"
    assert r.preflight(["@oa/m"]) == []


def test_registered_secrets_feed_the_redactor(router):
    assert router.redactor.redact("bad key k1 here") == "bad key [REDACTED] here"
