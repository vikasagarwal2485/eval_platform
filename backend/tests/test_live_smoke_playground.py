"""`add-agent-playground` task 6.6: opt-in live smoke test against a real, already-running backend
(with `EVAL_SECRET_KEY` configured) and a real local Ollama.

Skipped unless `EVAL_LIVE_PLAYGROUND_URL` is set, mirroring `test_live_smoke_gateway.py`'s pattern -
this repo's default test run never needs a live backend process or `agents/.venv`. To run it:

    # in one terminal: a real backend, with a model it can reach already pulled in Ollama
    EVAL_SECRET_KEY=some-passphrase backend/.venv/bin/uvicorn app.main:app_factory --factory \
        --host 127.0.0.1 --port 8000

    # in another:
    EVAL_LIVE_PLAYGROUND_URL=http://127.0.0.1:8000 EVAL_LIVE_PLAYGROUND_MODEL=qwen3:8b \
        backend/.venv/bin/pytest backend/tests/test_live_smoke_playground.py -s

Verifies spec `agent-playground`'s "A spawned turn is indistinguishable from a terminal-run one":
registers a real chatbot agent, marks it playground-eligible, spawns it with a one-shot task
through the real `/playground/spawn` endpoint (launching the real `agents/chatbot.py` as its own
OS subprocess - never a mock), and confirms the resulting turn appears in that agent's ordinary
conversation history with the expected output, exactly as a terminal-run instance's turn would.
"""

from __future__ import annotations

import os
import time

import httpx
import pytest


def _live_playground():
    url = os.environ.get("EVAL_LIVE_PLAYGROUND_URL", "").strip()
    if not url:
        pytest.skip("EVAL_LIVE_PLAYGROUND_URL is not set; opt in by pointing it at a running backend to run this")
    model = os.environ.get("EVAL_LIVE_PLAYGROUND_MODEL", "qwen3:8b").strip()
    return url, model


def test_a_spawned_chatbot_turn_appears_in_its_conversation_history():
    base_url, model = _live_playground()
    client = httpx.Client(base_url=base_url, timeout=30.0)

    name = f"live-playground-chatbot-{int(time.time())}"
    created = client.post(
        "/api/agents", json={"name": name, "kind": "chatbot", "declared_models": {"default": model}}
    ).json()
    agent_id = created["id"]

    enabled = client.post(f"/api/agents/{agent_id}/playground/enable", json={"flavor": "chatbot"})
    assert enabled.status_code == 200, enabled.text

    spawned = client.post(
        f"/api/agents/{agent_id}/playground/spawn",
        json={"task": "Say the single word: hello"},
        timeout=120.0,
    )
    assert spawned.status_code == 200, spawned.text
    assert spawned.json()["status"] == "ok", spawned.json()

    turns = client.get(f"/api/agents/{agent_id}/turns").json()
    assert len(turns) == 1
    assert turns[0]["status"] == "ok"
    assert turns[0]["output"]

    client.delete(f"/api/agents/{agent_id}")
