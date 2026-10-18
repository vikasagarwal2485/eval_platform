# Design

## Context

See `proposal.md` - Why. This phase is validation work: confirm the `<agent-slug>__<task_type>`
convention from `add-litellm-gateway-infra`/`add-reasoning-agent-task-routing` - and the
self-discovery (`add-agent-self-discovery`) and fallback (`add-declared-model-fallback`)
mechanisms layered on top of it since - all hold for a third task type, using the registry shape
`add-agent-multi-model-registry` introduces. Written against the `reference-agents` main spec as
it currently stands (post self-discovery and fallback); `reasoning_agent.py`'s `call_llm()` already
accepts a `fallback_group` parameter and `_resolve_model_groups()` already discovers task groups
generically from `whoami`'s response - this phase extends both to a third task rather than
inventing new mechanisms.

## Goals / Non-Goals

**Goals:**
- Prove a third task-scoped model group works end to end: gateway config, agent call (via the
  existing `call_llm()` helper, not a new calling path), span recording, registry declaration,
  self-discovery, and (if configured) fallback - with no change to the first two groups' behavior.
- Confirm `whoami`'s `gateway_model_groups` response - already generic over whatever task types an
  agent declares - needs no backend changes to return a `classification` entry once one is
  declared; this phase's acceptance criteria includes verifying this rather than assuming it.

**Non-Goals:**
- Using the classification result to actually change plan/solve/verify behavior (prompt
  selection, strategy branching) is explicitly **not required** for this phase. Making the
  classification call and recording its span is sufficient to prove the conventions generalize;
  wiring its output into downstream behavior is a separate, future enhancement with its own
  product questions (what categories? how do they change the prompts?) that don't need answering
  just to validate routing.
- No new reference agent. No change to `chatbot.py`.
- No Auto Router / semantic classification by the gateway itself - the agent's own classification
  call is a plain LLM call like any other, routed by the same static convention as the other two;
  it does not use LiteLLM's Auto Router feature (noted but not adopted anywhere in this plan, per
  the companion proposal doc).

## Decisions

**Classification reuses `call_llm()` directly - no new, bespoke LLM-calling code path.** The only
new things are the prompt, the discovered-or-overridden group name, the optional fallback group,
and the span. This keeps `plan`/`solve`/`verify`'s existing behavior completely unchanged (matches
the "A third task type does not disturb the first two" scenario), keeps this phase's blast radius
to "one new call site using existing machinery, one new span, one new model group," and directly
satisfies the requirement that there be no direct agent call to a classification LLM that bypasses
the gateway the other three calls already go through.

**Classification group discovery is expected to need zero backend changes.** `whoami`'s
`gateway_model_groups` field is already built generically from whatever keys an agent's
`declared_models` has (`backend/app/api/ingest.py`), not hardcoded to `reasoning`/`generation` - so
declaring a third `classification` entry should make a discovered `classification` group appear
automatically. Verifying this (task 1.2) is itself part of what this phase proves; if it turns out
not to hold, that is a real finding this phase exists to surface - see tasks.md.

**`_resolve_model_groups()` becomes 3-way, following its existing per-task pattern exactly** - one
more explicit/discovered/fallback-default resolution, no new resolution logic. A
`--classification-model-group` override and `--classification-fallback-group` are added as CLI
flags mirroring `--reasoning-model-group`/`--reasoning-fallback-group`'s existing shape.

**The classification call's output is recorded but not required to be acted upon.** This keeps
the phase's scope to exactly what it needs to prove. If, once this lands, the classification
result turns out useful for selecting a prompt variant, that's a natural, separate follow-up change
with its own proposal - not bundled in here, where it would mix "does the routing convention
generalize" with "is this particular product behavior useful," two different questions.

## Risks / Trade-offs

[An extra LLM call per turn adds latency and cost for a result that, in this phase, isn't even
used] → accepted deliberately, scoped as validation work; if the phases this depends on haven't
proven valuable enough to justify this phase at all, per the recommendation in proposal.md, the
right move is not to start it, not to start it without the extra call.

[A third model group is one more piece of registry-driven configuration] → no new risk beyond
what the phases this depends on already accepted; this phase changes only the count, not the
kind, of configuration surface.

## Open Questions

- If the classification result does turn out useful for prompt selection later, should that reuse
  this phase's span/model-group plumbing as-is, or does prompt-variant selection want its own
  design conversation? Deferred: this does not change this phase's spec, approach or tasks - it
  only affects a possible future change.
