"""5.5: no API key value may reach the database, any API response, an export, the event stream, logs or stored errors."""

import logging
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import repo
from app.main import create_app
from app.providers.secrets import Redactor
from tests.fake_providers import FakeAnthropic, FakeOpenAI, Step
from tests.fakes import FakeOllama, make_tag
from tests.helpers import GEN, make_responder, wait_for

SENTINEL = "sk-proj-LEAKCHECK0123456789abcdefghijKLMN"
PARTIAL = SENTINEL[10:30]  # a long stretch of the key: partial echoes count as leaks too
GPT, O3, CLAUDE = "@oa/gpt-4o", "@oa/o3", "@an/claude"


def find_leaks(text: str) -> list[str]:
    return [what for what, needle in (("full key", SENTINEL), ("partial key", PARTIAL)) if needle in text]


@pytest.fixture
def stack(settings, file_session_factory, monkeypatch):
    monkeypatch.setenv("OA_KEY", SENTINEL)
    monkeypatch.setenv("AN_KEY", SENTINEL)
    oa, an = FakeOpenAI(), FakeAnthropic()
    oa.expected_key = an.expected_key = SENTINEL
    oa.answer = an.answer = "Rain taps the glass"
    urls = (oa.start(), an.start())
    with file_session_factory() as s:
        for kind, name, env, url, ids in (
            ("openai", "oa", "OA_KEY", urls[0], ["gpt-4o", "o3"]),
            ("anthropic", "an", "AN_KEY", urls[1], ["claude"]),
        ):
            p = repo.create_provider(s, kind=kind, name=name, key_env=env, base_url=url, ack_at=datetime.now(UTC))
            for mid in ids:
                repo.add_registered_model(s, p.id, mid)
        s.commit()
    fake = FakeOllama([make_tag("qwen3:8b")], make_responder())
    with TestClient(create_app(settings, ollama=fake, session_factory=file_session_factory)) as client:
        yield client, oa, an, file_session_factory
    oa.stop()
    an.stop()


def db_bytes(sf) -> bytes:
    path = sf.kw["bind"].url.database
    data = b""
    for suffix in ("", "-wal", "-shm"):
        try:
            data += open(path + suffix, "rb").read()
        except FileNotFoundError:
            pass
    return data


def run_scenarios(client, oa, an, echo_key: bool):
    """Successful and failing runs whose provider errors echo the key back, then everything is fetched."""
    bad = f"Incorrect API key provided: {SENTINEL}. You can find your key at ..." if echo_key else "invalid"
    oa.script.extend([Step(kind="status", status=401, body={"error": {"message": bad}})])  # gpt-4o: auth failure
    an.script.extend(
        [
            Step(
                kind="status",
                status=503,
                body={"type": "error", "error": {"type": "overloaded_error", "message": f"upstream said {SENTINEL}"}},
            )
        ]
        * 4
    )
    ids = []
    for judge in ({"judge_mode": "cross_model"}, {"judge_model": CLAUDE}):
        r = client.post(
            "/api/runs",
            json={
                "models": ["qwen3:8b", GPT, O3, CLAUDE],
                "adhoc_cases": [GEN],
                "config": {"warmup": False, "judge_reasoning": True},
                **judge,
            },
        )
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
        wait_for(client, r.json()["id"], timeout=60)
    client.post(f"/api/runs/{ids[0]}/rescore", json={"judge_mode": "cross_model"})
    wait_for(client, ids[0], timeout=60)
    client.post(f"/api/runs/{ids[0]}/rerun")
    return ids


def collect_everything(client, ids) -> dict[str, str]:
    out: dict[str, str] = {}
    pid = client.get("/api/providers").json()[0]["id"]
    urls = ["/api/providers", f"/api/providers/{pid}", "/api/models", "/api/health", "/api/runs", "/api/suites"]
    for rid in ids:
        urls += [
            f"/api/runs/{rid}",
            f"/api/runs/{rid}/results",
            f"/api/runs/{rid}/summary",
            f"/api/runs/{rid}/export?format=csv",
            f"/api/runs/{rid}/export?format=json",
        ]
    urls += [f"/api/runs/compare?a={ids[0]}&b={ids[1]}"]
    for u in urls:
        out[u] = client.get(u).text
    with client.stream("GET", f"/api/runs/{ids[0]}/events") as resp:
        out["events"] = "".join(resp.iter_text())
    out["test-connection"] = client.post(f"/api/providers/{pid}/test").text
    out["available-models"] = client.get(f"/api/providers/{pid}/available-models").text
    return out


def stored_errors(sf) -> list[str]:
    from sqlalchemy import select

    from app.models import Judgement, Result, Run, Score

    with sf() as s:
        texts = [str(r.error) for r in s.scalars(select(Result))]
        texts += [str(r.error) for r in s.scalars(select(Run))]
        texts += [str(j.detail) for j in s.scalars(select(Judgement))]
        texts += [str(x.detail) for x in s.scalars(select(Score))]
        texts += [str(r.metrics) for r in s.scalars(select(Result))]
    return texts


def test_no_key_reaches_the_database_api_exports_events_logs_or_stored_errors(stack, caplog):
    client, oa, an, sf = stack
    caplog.set_level(logging.DEBUG)
    ids = run_scenarios(client, oa, an, echo_key=True)

    # the scenario really exercised failures whose provider text contained the key (else this test proves nothing)
    results = client.get(f"/api/runs/{ids[0]}/results").json()["results"]
    errors = [r["error"] for r in results if r["error"]]
    assert errors and any("[REDACTED]" in e for e in errors), errors
    assert any(r["status"] == "error" and r["model"] == GPT for r in results)
    assert oa.requests and an.requests

    leaks = {name: find_leaks(text) for name, text in collect_everything(client, ids).items() if find_leaks(text)}
    assert leaks == {}, f"key leaked in API responses: {leaks}"
    assert find_leaks(db_bytes(sf).decode("latin-1")) == [], "key leaked into the SQLite file"
    assert [t for t in stored_errors(sf) if find_leaks(t)] == [], "key leaked into stored errors or metrics"
    assert [rec.getMessage() for rec in caplog.records if find_leaks(rec.getMessage())] == [], "key leaked into logs"
    assert [rec.exc_text for rec in caplog.records if rec.exc_text and find_leaks(rec.exc_text)] == []
    # ...but the key *was* used: it travelled only in the authentication headers
    assert {r["headers"].get("authorization") for r in oa.requests} == {f"Bearer {SENTINEL}"}
    assert {r["headers"].get("x-api-key") for r in an.requests} == {SENTINEL}


def test_the_scan_really_detects_a_leak_when_redaction_is_removed(stack, monkeypatch):
    """Guards the guard: with redaction disabled the same scenario must be caught by the scan."""
    client, oa, an, sf = stack
    monkeypatch.setattr(Redactor, "redact", lambda self, text: text or "")
    ids = run_scenarios(client, oa, an, echo_key=True)
    leaked_in = [name for name, text in collect_everything(client, ids).items() if find_leaks(text)]
    stored = [t for t in stored_errors(sf) if find_leaks(t)]
    assert leaked_in or stored, "the leak detector is blind: it found nothing with redaction switched off"
    assert stored or find_leaks(db_bytes(sf).decode("latin-1"))


def test_a_run_whose_errors_do_not_echo_the_key_is_also_clean(stack):
    client, oa, an, sf = stack
    ids = run_scenarios(client, oa, an, echo_key=False)
    assert {n: find_leaks(t) for n, t in collect_everything(client, ids).items() if find_leaks(t)} == {}
    assert find_leaks(db_bytes(sf).decode("latin-1")) == []


def test_find_leaks_helper_flags_full_and_partial_keys():
    assert find_leaks("x") == [] and find_leaks(f"a {SENTINEL} b") == ["full key", "partial key"]
    assert find_leaks(f"key ends {PARTIAL} ...") == ["partial key"]
