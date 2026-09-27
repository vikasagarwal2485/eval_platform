"""7.2: opt-in live smoke test against the real OpenAI and Anthropic APIs.

Skipped unless the provider's real key environment variable is set to a non-empty value; this
repository, its CI and every other test never need or hold a real key (design D13). To run it:

    OPENAI_API_KEY=sk-... .venv/bin/pytest tests/test_live_smoke_enterprise.py -k openai -s
    ANTHROPIC_API_KEY=sk-ant-... .venv/bin/pytest tests/test_live_smoke_enterprise.py -k anthropic -s

The model used for each provider can be overridden (e.g. if the default is retired) with
`EVAL_LIVE_OPENAI_MODEL` / `EVAL_LIVE_ANTHROPIC_MODEL`. Requests are kept small (short prompts, a
low output-token cap) since this hits the real, billable API.
"""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app
from tests.helpers import wait_for

CLS_CASE = {
    "category": "classification",
    "title": "sentiment",
    "prompt": "Classify the sentiment of this sentence: 'I absolutely love this, it's wonderful!'",
    "labels": ["positive", "negative"],
    "expected": "positive",
}
GEN_CASE = {
    "category": "generation",
    "title": "haiku",
    "prompt": "Write a one-line haiku about the ocean.",
    "rubric": [{"name": "Relevance", "description": "about the ocean"}],
}

PROVIDER_CASES = [
    ("openai", "OPENAI_API_KEY", "EVAL_LIVE_OPENAI_MODEL", "gpt-4o-mini"),
    ("anthropic", "ANTHROPIC_API_KEY", "EVAL_LIVE_ANTHROPIC_MODEL", "claude-3-5-haiku-20241022"),
]


@pytest.mark.parametrize(
    "kind,key_env,model_env,default_model",
    [pytest.param(*c, id=c[0]) for c in PROVIDER_CASES],
)
def test_live_smoke(kind, key_env, model_env, default_model, file_session_factory):
    key = os.environ.get(key_env, "").strip()
    if not key:
        pytest.skip(f"{key_env} is not set; opt in by exporting a real key to run this live test")
    model_id = os.environ.get(model_env, default_model)

    with TestClient(create_app(load_settings(), session_factory=file_session_factory)) as client:
        prov = client.post(
            "/api/providers",
            json={
                "kind": kind,
                "name": f"live-{kind}",
                "key_env": key_env,
                "acknowledge_data_sharing": True,
            },
        )
        assert prov.status_code == 201, prov.text
        provider_id = prov.json()["id"]
        assert prov.json()["key_available"] is True

        added = client.post(f"/api/providers/{provider_id}/models", json={"model_id": model_id})
        assert added.status_code == 201, added.text
        ref = added.json()["ref"]

        test_conn = client.post(f"/api/providers/{provider_id}/test").json()
        assert test_conn["status"] == "working", test_conn

        run = client.post(
            "/api/runs",
            json={
                "name": f"live smoke ({kind})",
                "models": [ref],
                "adhoc_cases": [CLS_CASE, GEN_CASE],
                "judge_mode": "single",
                "judge_model": ref,  # self-judged, but this test only checks the pipeline works end to end
                "config": {"warmup": False, "max_output_tokens": 200, "temperature": 0},
            },
        )
        assert run.status_code == 201, run.text
        run_id = run.json()["id"]
        done = wait_for(client, run_id, timeout=120)
        assert done["status"] == "completed", done.get("error")

        results = client.get(f"/api/runs/{run_id}/results").json()["results"]
        assert len(results) == 2
        for r in results:
            assert r["status"] == "ok", r["error"]
            assert r["output"].strip()
            assert r["latency_ms"] is not None and r["latency_ms"] > 0
            assert r["source"] == "cloud" and r["provider"] == f"live-{kind}"
            assert r["model_version"]  # the provider reported which build actually answered
            assert r["primary"]["outcome"] != "unscored"

        summary = client.get(f"/api/runs/{run_id}/summary").json()
        row = summary["leaderboard"][0]
        assert row["categories"]["classification"]["scored"] == 1
        assert row["categories"]["generation"]["scored"] == 1

        # the real key must never appear in anything the run produced or stored
        exported = json.loads(client.get(f"/api/runs/{run_id}/export?format=json").text)
        haystack = json.dumps(
            {
                "results": results,
                "summary": summary,
                "exported": exported,
                "providers": client.get("/api/providers").json(),
            }
        )
        assert key not in haystack

        db_path = file_session_factory.kw["bind"].url.database
        db_bytes = b""
        for suffix in ("", "-wal", "-shm"):
            try:
                db_bytes += open(db_path + suffix, "rb").read()
            except FileNotFoundError:
                pass
        assert key.encode() not in db_bytes


def test_skipped_by_default_without_real_keys():
    """Documents the opt-in gate itself: with no key env vars set, both parametrized cases skip."""
    for _, key_env, _, _ in PROVIDER_CASES:
        assert not os.environ.get(key_env, "").strip(), (
            f"{key_env} is set in this environment; the parametrized live tests above will run "
            "against the real provider instead of skipping"
        )
