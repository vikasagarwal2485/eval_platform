# Proposal

## Why

Phases 1-3 (`add-litellm-gateway-infra`, `add-reasoning-agent-task-routing`,
`add-agent-multi-model-registry`) prove the task-routing convention with exactly two task types,
`reasoning` and `generation`. This phase is explicitly optional (see the companion proposal doc's
phased plan, Phase 4): it exists only to confirm the `<agent-slug>__<task_type>` convention
generalizes past two task types before anyone builds a registry UI or gateway tooling assuming
there are always exactly two. **Recommendation: defer starting this phase until phases 1-3 have
been running for a while and have proven useful** - these artifacts are prepared now so the plan
is ready to pick up, not as a signal to start immediately.

## What Changes

- Add a `classify` step to `reasoning_agent.py`'s `solve_one()`, before planning: a short call
  that categorizes the incoming problem (for example, by domain or difficulty), routed through a
  third model group, `reasoning-agent__classification`.
- The classification result is recorded as its own span (consistent with the existing
  plan/solve/verify span pattern) and, at minimum, surfaced for display; using it to choose a
  prompt variant for the subsequent plan/solve/verify calls is a worthwhile follow-on but is
  **not** required for this phase to satisfy its purpose (proving the routing convention
  generalizes) - see design.md Non-Goals.
- No new reference agent is introduced; `chatbot.py` remains untouched (still out of scope, as
  decided in `add-reasoning-agent-task-routing`'s design.md).

## Capabilities

### Modified Capabilities
- `reference-agents`: the reasoning agent's requirement gains a classification step as part of
  its multi-call turn, routed through a third task-scoped model group.
- `agent-llm-gateway`: no requirement text changes (the existing "Task-scoped model groups" and
  "Model groups are scoped per agent" requirements already generalize to any number of task
  types by construction) - this phase is validation that the existing spec holds for a third
  group, not a change to it. No delta file is needed for this capability.

## Impact

- **Affected code**: `agents/reasoning_agent.py`, `gateway/config.yaml` (adds the
  `reasoning-agent__classification` group), `agents/README.md`.
- **Depends on**: `add-litellm-gateway-infra`, `add-reasoning-agent-task-routing`,
  `add-agent-multi-model-registry` (uses the registry's `declared_models` map to add the third
  entry).
- **Priority**: explicitly lower than phases 1-3; start only once those have landed and run in
  practice, per the Why section above.
