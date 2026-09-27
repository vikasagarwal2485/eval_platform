"""1.2: error hierarchy and where it is caught."""

import pytest

from app.core.scoring.judge import JudgeCall, run_judge
from app.ollama.client import OllamaError, OllamaUnreachable
from app.providers.errors import (
    ModelBackendError,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimited,
    ProviderUnavailable,
)
from tests.fakes import FakeOllama, make_stream, make_tag
from tests.helpers import CLS, make_responder, new_client, start_run, wait_for


def test_hierarchy():
    assert issubclass(OllamaError, ModelBackendError) and issubclass(OllamaUnreachable, OllamaError)
    for cls in (ProviderAuthError, ProviderRateLimited, ProviderUnavailable):
        assert issubclass(cls, ProviderError) and issubclass(cls, ModelBackendError)
        # a provider problem must never be mistaken for the local server being down (which fails the run)
        assert not issubclass(cls, OllamaError)


def test_provider_error_carries_status_and_provider():
    e = ProviderAuthError("bad key", status=401, provider="openai-main")
    assert (str(e), e.status, e.provider) == ("bad key", 401, "openai-main")


def test_per_request_provider_error_is_recorded_and_the_run_continues(settings, file_session_factory):
    def responder(model, messages, options):
        if "I love it" in messages[-1]["content"]:
            raise ProviderUnavailable("provider overloaded", status=529, provider="p")
        return make_stream("positive")

    other = dict(CLS, prompt="Great phone", title="c2")
    fake = FakeOllama([make_tag("a:1")], responder)
    with new_client(settings, file_session_factory, fake) as c:
        run = start_run(c, ["a:1"], [CLS, other], config={"warmup": False})
        done = wait_for(c, run["id"])
        res = c.get(f"/api/runs/{run['id']}/results").json()["results"]
    assert done["status"] == "completed"
    assert [(r["status"], r["primary"]["outcome"]) for r in res] == [("error", "error"), ("ok", "correct")]
    assert "overloaded" in res[0]["error"]


def test_ollama_unreachable_still_fails_the_run(settings, file_session_factory):
    def responder(model, messages, options):
        raise OllamaUnreachable("connection refused")

    with new_client(settings, file_session_factory, FakeOllama([make_tag("a:1")], responder)) as c:
        run = start_run(c, ["a:1"], [CLS], config={"warmup": False})
        done = wait_for(c, run["id"])
    assert done["status"] == "failed" and "connection refused" in done["error"]


async def test_a_judge_provider_error_becomes_an_error_judgement():
    def responder(model, messages, options):
        raise ProviderAuthError("invalid key", status=401)

    res, _ = await run_judge(FakeOllama(responder=responder), "j", JudgeCall("t", "r", [{"name": "Q"}]))
    assert res.outcome == "error" and "invalid key" in res.detail["error"]


async def test_judge_connection_loss_still_propagates():
    with pytest.raises(OllamaUnreachable):
        await run_judge(FakeOllama(down=True), "j", JudgeCall("t", "r", [{"name": "Q"}]))


def test_default_responder_sanity():
    assert make_responder()  # helper import stays valid
