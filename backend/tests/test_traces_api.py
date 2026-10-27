"""add-otel-tracing 4.2/4.3: GET /api/traces/{trace_id} - found, not-found, unreachable, not
configured - and that none of this touches any other endpoint."""

from __future__ import annotations

import dataclasses

import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from tests.fakes import FakeOllama, make_tag
from tests.helpers import CLS, make_responder, start_run, wait_for


def transport_returning(status_code: int, json_body=None, *, text=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if text is not None:
            return httpx.Response(status_code, text=text)
        return httpx.Response(status_code, json=json_body)

    return httpx.MockTransport(handler)


def unreachable_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    return httpx.MockTransport(handler)


def client_with_tempo(settings, file_session_factory, tempo_transport):
    settings = dataclasses.replace(settings, tempo_base_url="http://tempo.example")
    return TestClient(create_app(settings, session_factory=file_session_factory, tempo_transport=tempo_transport))


def test_found_trace_returns_its_json(settings, file_session_factory):
    body = {"batches": [{"spans": [{"name": "eval.generate"}]}]}
    with client_with_tempo(settings, file_session_factory, transport_returning(200, body)) as c:
        r = c.get("/api/traces/abc123")
    assert r.status_code == 200 and r.json() == body


def test_not_found_trace_is_a_clear_404(settings, file_session_factory):
    with client_with_tempo(settings, file_session_factory, transport_returning(404, text="not found")) as c:
        r = c.get("/api/traces/missing")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "trace_not_found"


def test_unreachable_tempo_is_a_clear_503(settings, file_session_factory):
    with client_with_tempo(settings, file_session_factory, unreachable_transport()) as c:
        r = c.get("/api/traces/abc123")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "tempo_unreachable"


def test_unexpected_tempo_response_is_a_clear_502(settings, file_session_factory):
    with client_with_tempo(settings, file_session_factory, transport_returning(500, text="oops")) as c:
        r = c.get("/api/traces/abc123")
    assert r.status_code == 502 and r.json()["detail"]["code"] == "tempo_error"


def test_tempo_not_configured_is_a_clear_503(settings, file_session_factory):
    """Default settings: tempo_base_url is unset - a supported, graceful state, not a crash."""
    with TestClient(create_app(settings, session_factory=file_session_factory)) as c:
        r = c.get("/api/traces/abc123")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "tempo_not_configured"


def test_an_unreachable_tempo_never_affects_evaluation_endpoints(settings, file_session_factory):
    """4.3: a trace-proxy failure is isolated - run/results/summary endpoints behave identically."""
    fake = FakeOllama([make_tag("qwen3:8b")], make_responder())
    settings = dataclasses.replace(settings, tempo_base_url="http://tempo.example")
    with TestClient(
        create_app(settings, ollama=fake, session_factory=file_session_factory, tempo_transport=unreachable_transport())
    ) as c:
        run = start_run(c, ["qwen3:8b"], [CLS], config={"warmup": False})
        done = wait_for(c, run["id"])
        assert done["status"] == "completed"
        assert c.get(f"/api/runs/{run['id']}/results").status_code == 200
        assert c.get(f"/api/runs/{run['id']}/summary").status_code == 200
        trace_resp = c.get("/api/traces/abc123")
    assert trace_resp.status_code == 503 and trace_resp.json()["detail"]["code"] == "tempo_unreachable"
