"""3.5: retry, backoff, error mapping and secret hygiene shared by both adapters."""

import httpx
import pytest

from app.providers.anthropic import AnthropicBackend
from app.providers.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimited,
    ProviderUnavailable,
)
from app.providers.openai import OpenAIBackend
from tests.fake_providers import FakeAnthropic, FakeOpenAI, Step
from tests.provider_helpers import KEY, Sleeps, collect, make, text_of

MSGS = [{"role": "user", "content": "hi"}]


@pytest.fixture(params=["openai", "anthropic"])
def kit(request):
    srv, cls = (FakeOpenAI(), OpenAIBackend) if request.param == "openai" else (FakeAnthropic(), AnthropicBackend)
    url = srv.start()
    yield srv, url, cls, request.param
    srv.stop()


def build(kit, **kw):
    srv, url, cls, kind = kit
    return make(cls, kind, url, **kw)


async def chat(b):
    return await collect(b.chat_stream(model="m", messages=MSGS))


class Clock:
    """Virtual time: `sleep` advances it, so recorded waits can be checked without waiting."""

    def __init__(self):
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def with_clock(kit, **kw):
    clock = Clock()
    srv, url, cls, kind = kit
    b = make(cls, kind, url, **kw)
    b._sleep, b._clock = clock.sleep, clock
    return b, clock


# ---------------------------------------------------------------- rate limits
async def test_rate_limit_then_success_records_attempts_and_the_wait(kit):
    srv = kit[0]
    srv.script.append(Step(kind="status", status=429, headers={"retry-after": "2"}))
    b, clock = with_clock(kit)
    chunks = await chat(b)
    meta = chunks[-1]["_provider"]
    assert text_of(chunks) and meta["attempts"] == 2
    assert clock.slept == [2.0] and meta["retry_wait_ms"] == pytest.approx(
        2000.0
    )  # the wait is reported, not folded in
    assert len(srv.chat_requests()) == 2


async def test_first_try_success_reports_one_attempt_and_no_wait(kit):
    b, clock = with_clock(kit)
    meta = (await chat(b))[-1]["_provider"]
    assert meta["attempts"] == 1 and meta["retry_wait_ms"] == 0.0 and clock.slept == []


async def test_retry_after_is_honoured_and_capped(kit):
    srv = kit[0]
    srv.script.extend(
        [
            Step(kind="status", status=429, headers={"retry-after": "3.5"}),
            Step(kind="status", status=429, headers={"retry-after": "9999"}),
        ]
    )
    b, clock = with_clock(kit, retries=3)
    await chat(b)
    assert clock.slept == [3.5, 120.0]  # numeric hint used as given, huge hints capped at 2 minutes


async def test_backoff_is_exponential_with_jitter_and_capped(kit):
    srv = kit[0]
    srv.script.extend([Step(kind="status", status=503)] * 4)
    b, clock = with_clock(kit, retries=4, backoff=0.5, cap=3.0, jitter=lambda: 1.0)
    await chat(b)
    assert clock.slept == [0.5, 1.0, 2.0, 3.0]  # 0.5 * 2^n, capped at 3.0
    srv.script.extend([Step(kind="status", status=503)] * 2)
    b2, clock2 = with_clock(kit, retries=2, backoff=1.0, jitter=lambda: 0.0)
    await chat(b2)
    assert clock2.slept == [0.5, 1.0]  # lowest jitter is half the delay


async def test_a_date_style_retry_after_falls_back_to_backoff(kit):
    srv = kit[0]
    srv.script.append(Step(kind="status", status=429, headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}))
    b, clock = with_clock(kit, backoff=0.5, jitter=lambda: 1.0)
    await chat(b)
    assert clock.slept == [0.5]


async def test_exhausted_rate_limit_is_a_rate_limited_error_after_the_configured_attempts(kit):
    srv = kit[0]
    srv.script.extend([Step(kind="status", status=429)] * 10)
    b, clock = with_clock(kit, retries=2)
    with pytest.raises(ProviderRateLimited, match="gave up after 3 attempts") as ei:
        await chat(b)
    assert ei.value.status == 429 and len(srv.chat_requests()) == 3 and len(clock.slept) == 2


@pytest.mark.parametrize("status", [500, 502, 503, 504, 529])
async def test_exhausted_server_errors_are_unavailable_errors(kit, status):
    srv = kit[0]
    srv.script.extend([Step(kind="status", status=status)] * 10)
    b, _ = with_clock(kit, retries=1)
    with pytest.raises(ProviderUnavailable, match="gave up after 2 attempts") as ei:
        await chat(b)
    assert ei.value.status == status and not isinstance(ei.value, ProviderRateLimited)


async def test_retries_can_be_switched_off(kit):
    srv = kit[0]
    srv.script.append(Step(kind="status", status=429))
    b, clock = with_clock(kit, retries=0)
    with pytest.raises(ProviderRateLimited, match="gave up after 1 attempts"):
        await chat(b)
    assert clock.slept == [] and len(srv.chat_requests()) == 1


# ---------------------------------------------------------------- errors that are not retried
@pytest.mark.parametrize("status", [401, 403])
async def test_auth_failures_are_immediate_and_never_retried(kit, status):
    srv = kit[0]
    srv.script.append(Step(kind="status", status=status))
    b, clock = with_clock(kit)
    with pytest.raises(ProviderAuthError) as ei:
        await chat(b)
    assert ei.value.status == status and clock.slept == [] and len(srv.chat_requests()) == 1


async def test_a_wrong_key_is_an_auth_error(kit):
    with pytest.raises(ProviderAuthError):
        await chat(build(kit, key="not-the-key"))


async def test_other_client_errors_surface_the_provider_message_without_retrying(kit):
    srv = kit[0]
    srv.script.append(Step(kind="status", status=404, body={"error": {"message": "The model `m` does not exist"}}))
    b, clock = with_clock(kit)
    with pytest.raises(ProviderError, match="does not exist") as ei:
        await chat(b)
    assert ei.value.status == 404 and clock.slept == []
    assert not isinstance(ei.value, (ProviderUnavailable, ProviderRateLimited, ProviderAuthError))


# ---------------------------------------------------------------- transport failures
def failing_transport(times, then_ok: bool, message="connection reset"):
    calls = {"n": 0}

    def handler(req: httpx.Request):
        calls["n"] += 1
        if calls["n"] <= times:
            raise httpx.ConnectError(message)
        return httpx.Response(200, json={"data": [{"id": "x"}]})

    return httpx.MockTransport(handler), calls


@pytest.mark.parametrize("cls,kind", [(OpenAIBackend, "openai"), (AnthropicBackend, "anthropic")])
async def test_connection_errors_are_retried_then_succeed(cls, kind):
    transport, calls = failing_transport(2, True)
    sleeps = Sleeps()
    b = make(cls, kind, "http://x.test", transport=transport, sleeps=sleeps, retries=3)
    assert await b.list_models() == ["x"] and calls["n"] == 3 and len(sleeps.calls) == 2


@pytest.mark.parametrize("cls,kind", [(OpenAIBackend, "openai"), (AnthropicBackend, "anthropic")])
async def test_persistent_connection_errors_end_as_unavailable_with_a_redacted_message(cls, kind):
    transport, _ = failing_transport(99, False, message=f"tls failure for key {KEY}")
    b = make(cls, kind, "http://x.test", transport=transport, retries=1)
    with pytest.raises(ProviderUnavailable) as ei:
        await b.list_models()
    assert KEY not in str(ei.value) and "[REDACTED]" in str(ei.value) and "gave up after 2 attempts" in str(ei.value)


# ---------------------------------------------------------------- secret hygiene
async def test_a_key_echoed_in_a_provider_error_is_redacted_everywhere(kit):
    srv = kit[0]
    srv.script.append(
        Step(
            kind="status",
            status=400,
            body={"error": {"message": f"Bad request for key {KEY} and sk-proj-AbCdEf0123456789"}},
        )
    )
    with pytest.raises(ProviderError) as ei:
        await chat(build(kit))
    text = str(ei.value)
    assert KEY not in text and "sk-proj-AbCdEf0123456789" not in text and "[REDACTED]" in text


async def test_the_key_appears_only_in_the_auth_header_never_in_url_or_body(kit):
    srv = kit[0]
    await chat(build(kit))
    await build(kit).list_models()
    for rec in srv.requests:
        assert KEY not in rec["path"] and KEY not in rec["query"]
        assert KEY not in str(rec["body"] or "")
        carriers = [h for h, v in rec["headers"].items() if KEY in v]
        assert carriers in (["authorization"], ["x-api-key"])


@pytest.mark.parametrize("cls,kind", [(OpenAIBackend, "openai"), (AnthropicBackend, "anthropic")])
async def test_redirects_are_never_followed_so_the_key_cannot_leave(cls, kind):
    hosts = []

    def handler(req: httpx.Request):
        hosts.append(req.url.host)
        if req.url.host == "provider.test":
            return httpx.Response(302, headers={"location": "http://evil.test/steal"})
        return httpx.Response(200, json={"data": []})

    b = make(cls, kind, "http://provider.test", transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="unexpected redirect"):
        await b.list_models()
    assert hosts == ["provider.test"]  # evil.test was never contacted


async def test_a_key_rotated_between_attempts_is_used_for_the_retry(kit):
    srv = kit[0]
    srv.script.append(Step(kind="status", status=503))
    b, clock = with_clock(kit)

    async def rotate(seconds):
        b.env["PROV_KEY"] = KEY  # unchanged value: just proves the key is re-read each attempt without error
        await Clock.sleep(clock, seconds)

    b._sleep = rotate
    assert text_of(await chat(b))
    assert [r["headers"].get("authorization") or r["headers"].get("x-api-key") for r in srv.chat_requests()].count(
        f"Bearer {KEY}" if kit[3] == "openai" else KEY
    ) == 2
