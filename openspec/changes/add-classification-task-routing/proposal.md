# Proposal

## Why

Phases 1-3 (`add-litellm-gateway-infra`, `add-reasoning-agent-task-routing`,
`add-agent-multi-model-registry`) prove the task-routing convention with exactly two task types,
`reasoning` and `generation`. Since this phase was first drafted, two more phases have landed and
been archived: `add-agent-self-discovery` (the agent discovers its own gateway group names via
`GET /api/ingest/v1/whoami` instead of requiring hardcoded or hand-passed group names) and
`add-declared-model-fallback` (a task's call can name a fallback group to retry against). This
phase now validates that **all three** of those - task-scoped routing, self-discovery, and
fallback - generalize past two task types, not just the original routing convention, before
anyone builds tooling that assumes there are always exactly two. **Recommendation: defer starting
this phase until phases 1-3 (and the two that followed) have been running for a while and have
proven useful** - these artifacts are prepared now so the plan is ready to pick up, not as a
signal to start immediately.

## What Changes

- Add a `classify` step to `reasoning_agent.py`'s `solve_one()`, before planning: a short call
  that categorizes the incoming problem (for example, by domain or difficulty), routed through a
  third task-scoped model group (`classification`) using the **existing, already-implemented**
  `call_llm()` gateway-routing helper - the same one plan/solve/verify already call. There is no
  new, bespoke calling path: `classify()` is a `call_llm()` call like the other three, just with
  its own prompt, its own discovered (or explicitly overridden, via a new
  `--classification-model-group` flag) group name, and its own optional
  `--classification-fallback-group`.
- The agent's own classification group name is **discovered automatically** the same way the
  reasoning/generation groups already are (`add-agent-self-discovery`): `whoami`'s
  `gateway_model_groups` response is already keyed generically off whatever task types the agent
  declares, so adding a `classification` entry to `declared_models` is expected to make a
  discovered classification group appear with **zero backend changes** - this phase's job is to
  confirm that expectation holds, not to add discovery logic for a third task type.
- The classification result is recorded as its own span (consistent with the existing
  plan/solve/verify span pattern) and, at minimum, surfaced for display; using it to choose a
  prompt variant for the subsequent plan/solve/verify calls is a worthwhile follow-on but is
  **not** required for this phase to satisfy its purpose (proving the routing/discovery/fallback
  conventions generalize) - see design.md Non-Goals.
- No new reference agent is introduced; `chatbot.py` remains untouched (still out of scope, as
  decided in `add-reasoning-agent-task-routing`'s design.md).

## Capabilities

### Modified Capabilities
- `reference-agents`: the reasoning agent's requirement gains a classification step as part of
  its multi-call turn, routed through a third, self-discovered (or explicitly overridden)
  task-scoped model group, with the same fallback support the other two tasks already have.
- `agent-llm-gateway`: no requirement text changes (the existing "Task-scoped model groups" and
  "Model groups are scoped per agent" requirements already generalize to any number of task
  types by construction) - this phase is validation that the existing spec holds for a third
  group, not a change to it. No delta file is needed for this capability.

## Impact

- **Affected code**: `agents/reasoning_agent.py` (`classify()`, `_resolve_model_groups()` becoming
  3-way, a `--classification-model-group`/`--classification-fallback-group` CLI flag pair),
  `gateway/config.yaml` (adds the dev-default `reasoning-agent__classification` group),
  `agents/README.md`.
- **Depends on**: `add-litellm-gateway-infra`, `add-reasoning-agent-task-routing`,
  `add-agent-multi-model-registry`, `add-agent-self-discovery`, `add-declared-model-fallback`
  (uses the registry's `declared_models` map to add the third entry, discovers its group via
  `whoami`, and may configure a fallback for it the same way the other two tasks can).
- **Priority**: explicitly lower than the phases it depends on; start only once those have landed
  and run in practice, per the Why section above.
