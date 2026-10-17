# Proposal

## Why

`agents/reasoning_agent.py` already makes three distinct, named LLM calls per turn - plan, solve,
verify - but all three hit the same hardcoded Ollama model today, because the agent has no way to
address a different model per call. With the gateway from `add-litellm-gateway-infra` in place,
the reasoning agent can route its plan/verify calls to a reasoning-suited model and its solve call
to a generation-suited model, without the agent code ever hardcoding a provider endpoint. This is
the first real, user-visible payoff of task-routing: the same agent, each step on the model best
suited to it.

## What Changes

- Replace `reasoning_agent.py`'s direct `httpx` calls to Ollama with LiteLLM SDK calls through the
  gateway (`add-litellm-gateway-infra`), addressed by the model group names
  `reasoning-agent__reasoning` and `reasoning-agent__generation`.
- Plan and verify calls use the `reasoning` group; the solve call uses the `generation` group.
- Each span reported to the platform continues to carry the concrete model that actually produced
  it - read from the gateway response's `x-litellm-model-name` header (exposed via the SDK's
  `resp._hidden_params`), not `resp.model` (which is the group alias, verified while implementing
  `add-litellm-gateway-infra` - see design.md) - no change to what the platform receives or how it
  evaluates a turn.
- `httpx.HTTPError` handling in `run_once()`/`run_suite()` (added for robustness in the live-agent-
  evaluation work) becomes LiteLLM's exception hierarchy; the "print and keep going" behavior is
  unchanged.
- `agents/chatbot.py` is explicitly **not** changed by this proposal - it makes one call per turn
  and has no task to route between (see design.md - Non-Goals).

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `reference-agents`: the reasoning agent's requirement ("answers a problem through more than one
  LLM call... planning, solving and verifying, sending each call as its own span") gains that each
  call's span MAY report a different model, and that the agent routes calls through the shared
  gateway rather than a single hardcoded endpoint.

## Impact

- **Affected code**: `agents/reasoning_agent.py`, `agents/requirements.txt` (adds `litellm`),
  `agents/README.md` (documents the new `--model` / gateway-URL flags).
- **Depends on**: `add-litellm-gateway-infra` (the `reasoning-agent__reasoning` /
  `reasoning-agent__generation` model groups and a virtual key for this process must exist first).
- **Not affected**: `backend/`, `agents/chatbot.py`, the eval platform's own `ModelRouter` or
  judge pipeline (per the companion proposal doc's "Reference agent integration" section:
  `AgentSpan.model` is already per-span and `plan_turn_evaluators` already takes a plural
  `turn_models` list, so nothing there needs to change for this agent to report two different
  models in one turn).
