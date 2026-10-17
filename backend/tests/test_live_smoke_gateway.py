"""`add-reasoning-agent-task-routing` tasks.md 4.2/4.3: opt-in live smoke test against a real, running LLM
gateway (`gateway/`, `add-litellm-gateway-infra`).

Skipped unless `EVAL_LIVE_GATEWAY_URL` is set to a reachable gateway, mirroring
`test_live_smoke_enterprise.py`'s pattern - this repo's default test run never needs a live gateway process. To
run it (gateway already up per `gateway/README.md`, with a virtual key scoped to
`reasoning-agent__reasoning`/`reasoning-agent__generation`):

    EVAL_LIVE_GATEWAY_URL=http://localhost:4000 EVAL_LIVE_GATEWAY_KEY=sk-... \
      backend/.venv/bin/pytest backend/tests/test_live_smoke_gateway.py -s
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agents"))

import httpx
import reasoning_agent  # noqa: E402
from eval_agent_sdk import AgentClient  # noqa: E402


def _live_gateway():
    url = os.environ.get("EVAL_LIVE_GATEWAY_URL", "").strip()
    if not url:
        pytest.skip("EVAL_LIVE_GATEWAY_URL is not set; opt in by pointing it at a running gateway to run this")
    return url, os.environ.get("EVAL_LIVE_GATEWAY_KEY", "").strip() or None


def test_plan_and_verify_use_the_reasoning_group_and_solve_uses_the_generation_group():
    """Spec `reference-agents`, scenarios 'Plan and verify calls use the reasoning-scoped model group' / 'The
    solve call uses the generation-scoped model group' - against the real gateway, not a mock, using whatever
    distinguishable deployments each group is actually configured with (the dev default: two different local
    Ollama models - see gateway/config.yaml)."""
    gateway_url, gateway_key = _live_gateway()

    concrete_models: list[str] = []

    def fake_platform(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json={"accepted": 1, "duplicates": 0, "rejected": []})

    client = AgentClient("http://platform.local", "tok", transport=httpx.MockTransport(fake_platform))
    try:
        for model_group, prompt in [
            (reasoning_agent.REASONING_MODEL_GROUP, "Say the single word: reasoning"),
            (reasoning_agent.GENERATION_MODEL_GROUP, "Say the single word: generation"),
        ]:
            content, usage = reasoning_agent.call_llm(gateway_url, gateway_key, model_group, prompt)
            assert content  # the real gateway answered
            concrete_models.append(usage["model"])
    finally:
        client.close()

    # The dev-default config.yaml points the two groups at two different local Ollama models - if whoever is
    # running this swapped in real cloud deployments instead, the two concrete models are still expected to
    # differ (that's the entire point of having two separate groups), so this assertion holds either way.
    assert concrete_models[0] != concrete_models[1]
    assert reasoning_agent.REASONING_MODEL_GROUP not in concrete_models
    assert reasoning_agent.GENERATION_MODEL_GROUP not in concrete_models


def test_an_unreachable_gateway_fails_the_call_visibly():
    """Spec `agent-llm-gateway`, 'No silent deployment substitution' (and this change's own gateway-failure
    decision) - pointing at a gateway URL nothing is listening on must raise, not silently succeed."""
    import litellm

    with pytest.raises(Exception):  # noqa: B017 - litellm's own connection-error type, deliberately broad here
        litellm.completion(
            model="openai/reasoning-agent__reasoning",
            api_base="http://localhost:1",
            api_key="irrelevant",
            messages=[{"role": "user", "content": "hi"}],
            timeout=5,
            num_retries=0,
        )
