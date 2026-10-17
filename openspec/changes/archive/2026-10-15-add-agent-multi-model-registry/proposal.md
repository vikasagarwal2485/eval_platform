# Proposal

## Why

`Agent.declared_model` is a single string, but `AgentSpan.model` is already per-span and
`plan_turn_evaluators` already takes a plural `turn_models` list - the evaluation core was built
to handle a turn produced by more than one model from day one. `add-reasoning-agent-task-routing`
makes that real for the first time (plan/verify on one model, solve on another), but the registry
still only lets a user declare and safety-check one model per agent. This leaves the
self-evaluator check (`_check_no_self_evaluator`) blind to the second model a task-routed agent
actually uses: an operator could configure an evaluator that matches the agent's `generation`
model and the registry would accept it, because only `declared_model` (its `reasoning` model, say)
is checked. This change brings the registration-time check up to what the runtime check already
does.

## What Changes

- Replace `Agent.declared_model: str` with `Agent.declared_models: dict[str, str]`, keyed by task
  type (e.g. `{"reasoning": "@anthropic/claude-sonnet-5", "generation": "@openai/gpt-4o"}`); an
  agent with one task (like `chatbot.py`) declares one entry, conventionally keyed `"default"`.
- Alembic migration backfills every existing agent's `declared_model` into
  `{"default": declared_model}` so no currently-registered agent's data is lost or behaves
  differently post-migration.
- `AgentCreate`/`AgentSettingsUpdate` take `declared_models: dict[str, str]`; each value is
  validated with the existing `parse_ref()` (`backend/app/providers/refs.py`), applied per entry.
- `_check_no_self_evaluator` becomes a loop over `declared_models.values()`, rejecting an
  evaluator that matches **any** declared model - the same pattern `plan_turn_evaluators` already
  uses for `turn_models`.
- Registration/settings UI shows one model field per declared task type instead of one.
- **BREAKING**: `declared_model` (singular) is removed from the public API request/response shape;
  any existing client sending `declared_model` must switch to `declared_models`. The migration
  preserves existing data under the `"default"` key, but the field name itself changes.

## Capabilities

### Modified Capabilities
- `agent-registry`: "Register an agent" and "An evaluator cannot be configured as an agent's own
  model" both change to operate on a map of declared models instead of one.

## Impact

- **Affected code**: `backend/app/models.py` (`Agent.declared_models`), a new Alembic migration,
  `backend/app/schemas.py` (`AgentCreate`, `AgentSettingsUpdate`), `backend/app/repo.py`
  (`_check_no_self_evaluator`, `create_agent`/settings-update functions),
  `backend/app/api/agents.py` (`_agent_out`), frontend agent registration/settings forms.
- **Depends on**: none structurally - this change is independent of
  `add-litellm-gateway-infra`/`add-reasoning-agent-task-routing` and could land before, after, or
  in parallel with them (it only becomes *necessary* once an agent actually has more than one
  declared model, but is safe to ship first).
- **Not affected**: `AgentSpan.model`, `plan_turn_evaluators`, `resolve_evaluators`, the judge
  pipeline, `AgentTurnDrilldown` - all already operate per-span/per-turn with no singular "the"
  model assumption.
