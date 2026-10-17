# Design

## Context

See `proposal.md` - Why. This phase is validation work: confirm the `<agent-slug>__<task_type>`
convention from `add-litellm-gateway-infra`/`add-reasoning-agent-task-routing` holds for a third
task type, using the registry shape `add-agent-multi-model-registry` introduces. Written against
the `reference-agents` main spec as it stands before phase 2's delta has been archived; if phase 2
archives first, reconciling this delta's base text against the then-current main spec is routine
`openspec` sync work, not a design change.

## Goals / Non-Goals

**Goals:**
- Prove a third task-scoped model group works end to end: gateway config, agent call, span
  recording, registry declaration - with no change to the first two groups' behavior.

**Non-Goals:**
- Using the classification result to actually change plan/solve/verify behavior (prompt
  selection, strategy branching) is explicitly **not required** for this phase. Making the
  classification call and recording its span is sufficient to prove the convention generalizes;
  wiring its output into downstream behavior is a separate, future enhancement with its own
  product questions (what categories? how do they change the prompts?) that don't need answering
  just to validate routing.
- No new reference agent. No change to `chatbot.py`.
- No Auto Router / semantic classification by the gateway itself - the agent's own classification
  call is a plain LLM call like any other, routed by the same static convention as the other two;
  it does not use LiteLLM's Auto Router feature (noted but not adopted anywhere in this plan, per
  the companion proposal doc).

## Decisions

**Classification is a genuinely new call, not a repurposed existing one.** Keeps `plan`/`solve`/
`verify`'s existing behavior completely unchanged (matches the "A third task type does not disturb
the first two" scenario) and keeps this phase's blast radius to "one new span, one new model
group."

**The classification call's output is recorded but not required to be acted upon.** This keeps
the phase's scope to exactly what it needs to prove. If, once this lands, the classification
result turns out useful for selecting a prompt variant, that's a natural, separate follow-up change
with its own proposal - not bundled in here, where it would mix "does the routing convention
generalize" with "is this particular product behavior useful," two different questions.

## Risks / Trade-offs

[An extra LLM call per turn adds latency and cost for a result that, in this phase, isn't even
used] → accepted deliberately, scoped as validation work; if phases 1-3 haven't proven valuable
enough to justify this phase at all, per the recommendation in proposal.md, the right move is not
to start it, not to start it without the extra call.

[A third model group is one more piece of hand-kept (or, post phase 3, registry-driven)
configuration] → no new risk beyond what phases 1-3 already accepted; this phase changes only the
count, not the kind, of configuration surface.

## Open Questions

- If the classification result does turn out useful for prompt selection later, should that reuse
  this phase's span/model-group plumbing as-is, or does prompt-variant selection want its own
  design conversation? Deferred: this does not change this phase's spec, approach or tasks - it
  only affects a possible future change.
