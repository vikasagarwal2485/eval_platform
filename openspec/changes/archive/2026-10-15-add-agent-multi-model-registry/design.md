# Design

## Context

See `proposal.md` - Why. `Agent.declared_model: str` (`backend/app/models.py`) is used in exactly
one place at runtime: `_check_no_self_evaluator(declared_model, evaluators)` in `repo.py`, called
from both agent creation and settings updates. Everything that matters at evaluation time already
operates on the plural `turn_models` derived from `AgentSpan.model` per span
(`plan_turn_evaluators` in `eligibility.py`) - this change brings the one remaining singular-model
code path in line with that.

## Goals / Non-Goals

**Goals:**
- Let an agent declare more than one model, keyed by task type.
- Generalize the self-evaluator check to reject an evaluator matching *any* declared model.
- Preserve every existing single-model agent's data and behavior through migration.

**Non-Goals:**
- No change to how a *turn's* actual models are determined or checked (`AgentSpan.model`,
  `plan_turn_evaluators`) - those already work correctly today and are the reason this change is
  narrow.
- No gateway config generation/validation from the registry in this change, even though the
  companion proposal doc's open question raised it - see Decisions below for why it's deferred.
- No change to `kind` (`chatbot`/`reasoning`) - it remains the agent's overall behavior pattern,
  orthogonal to how many models it declares.

## Decisions

**A `dict[str, str]` keyed by task type, not a list.** A list would require a separate convention
for "which entry is the reasoning one," duplicating what the key already expresses. The key
namespace is intentionally open (not an enum) so a new task type needs no schema change - only
`"default"` is a reserved convention, for an agent with exactly one undifferentiated model
(matches today's single-chatbot-model shape after migration).

**Migration backfills to `{"default": declared_model}`, not a guessed task-type key.** The
platform cannot know whether an existing agent's one declared model should be called `"reasoning"`,
`"generation"`, or anything else - `"default"` is the only safe, meaning-free choice that
preserves exactly what the data already said.

**`declared_models` values are not currently cross-checked against the gateway's actual model
groups.** The open question this proposal doc left open - "should `config.yaml` be generated from
the registry, or does the registry read it?" - is deliberately **not resolved by building that
integration in this change**. Recommended direction, to action in a future change once both sides
exist and have run for a while: the registry (`declared_models`) is authoritative, since it is
this platform's own durable record and already goes through this change's validation; a later
change should generate or validate the gateway's `config.yaml` against it, not the reverse. This
change only makes the registry capable of holding the right shape of data - wiring it to the
gateway is separate, deliberately deferred work, not a gap in this change's scope.

**BREAKING change accepted, not shimmed.** A compatibility shim accepting both `declared_model`
and `declared_models` was considered and rejected: this is pre-1.0 internal tooling (reference
agents, not third-party integrations), so carrying two parallel fields indefinitely costs more
than updating the one caller (`agents/eval_agent_sdk` registration helper, if any exists;
otherwise just documentation and any manual registration scripts).

## Risks / Trade-offs

[Breaking API change] → scoped tightly: only the registration/settings request and response shape
changes; no data is lost (migration preserves it under `"default"`); document the change
prominently in this change's own `agents/README.md` update task.

[An agent could now declare a model for a task it doesn't actually have, or omit one it does,
with nothing catching the mismatch until a turn arrives with an unrecognized model] → out of
scope for this change (no gateway cross-check, per the Decision above); flagged as a known gap,
not silently accepted - `plan_turn_evaluators`'s existing `agent_model_unknown` skip reason already
handles the runtime case of a turn whose models can't be determined, so an undeclared-but-used
model fails safe (skipped, not wrongly evaluated) even without this change's registry catching it
earlier.

## Migration Plan

1. Add `declared_models` JSON column (default `{}`), keep `declared_model` column temporarily.
2. Data migration: for every existing row, set `declared_models = {"default": declared_model}`.
3. Switch all code paths (`repo.py`, `schemas.py`, `api/agents.py`) to read/write
   `declared_models` only.
4. Drop the `declared_model` column in a follow-up migration once the switch is verified in
   place (kept as a separate step so a rollback before that point only needs to revert code, not
   restore a dropped column).

Rollback: revert code to read `declared_model`; since step 4 is a separate migration, an early
rollback (before the column is dropped) needs no data recovery.
