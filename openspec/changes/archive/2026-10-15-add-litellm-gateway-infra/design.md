# Design

## Context

See `proposal.md` - Why. Today every agent process reaches providers directly (`agents/chatbot.py`,
`agents/reasoning_agent.py` call Ollama's native API over `httpx`); there is no shared place to
route a request by task. The `backend/app/providers/ModelRouter` is a separate, deliberately
unrelated system that serves the platform's own contestant/judge calls and is out of scope here
(see the companion proposal doc, "What LiteLLM is" tab, Option B).

## Goals / Non-Goals

**Goals:**
- Stand up one shared, supervised LiteLLM Proxy process that any future task-routed agent can
  reach by a model-group name instead of a provider endpoint.
- Keep provider credentials out of agent processes entirely; agents hold only a gateway-issued
  credential.

**Non-Goals:**
- No agent code changes (`add-reasoning-agent-task-routing`).
- No `Agent` registry schema changes (`add-agent-multi-model-registry`).
- No change to `backend/app/providers/` - the platform's own `ModelRouter` is untouched.
- No production-grade HA/scaling design for the gateway process - this stands up a single
  supervised instance suitable for local/dev and small deployments; multi-instance gateway
  topology is out of scope until usage demands it.

## Decisions

**Router model groups, not tags or the Auto Router, as the routing key.** A model group per
`(agent, task type)`, named `<agent-slug>__<task_type>` (e.g. `reasoning-agent__reasoning`), is
addressed directly by the caller's `model=` parameter. Tag-based routing and the Auto Router
(LiteLLM's complexity classifier) both solve a different problem - picking a deployment when the
caller does *not* already know what it needs - and are not adopted here. Full comparison: the
companion proposal doc, "LiteLLM's routing mechanisms" section.

**`config.yaml` is hand-authored in this phase; the `Agent` registry becomes authoritative in
`add-agent-multi-model-registry`.** This resolves the open question the companion proposal left
for implementation: rather than build registry-driven config generation before any agent exists
to generate it for, phase 1 ships a small, hand-written `config.yaml` naming only the one adopter
(`reasoning-agent`). Once `add-agent-multi-model-registry` lands, the registry's `declared_models`
map becomes the source of truth and the gateway config should be generated or validated against
it (tracked as a task there, not here) - not maintained by hand indefinitely.

**No fallback between providers configured in phase 1.** Each model group has exactly one
deployment for now. `litellm_settings.fallbacks` is left available but unconfigured; a later phase
can add it per group once there is a second real deployment to fall back to.

**Virtual key, not the shared master key, for the agent process.** The reasoning agent process
is issued a virtual key scoped to `reasoning-agent__*` groups only. The proxy's `master_key` stays
operator-only (admin API/UI), matching the platform's existing principle of least-privilege
credential scoping (`KeyProvider` in `backend/app/providers/secrets.py` holds provider keys at a
single point; the gateway now plays the analogous role for agent processes).

## Risks / Trade-offs

[The gateway becomes a single point of failure for any agent that depends on it] → run it as a
supervised process (not an ad hoc background job) with a documented restart procedure; this phase
ships no agent that depends on it yet, so the blast radius of an outage during this phase is zero
by construction - risk becomes real only once `add-reasoning-agent-task-routing` lands.

[Hand-written `config.yaml` drifts from whatever the registry says once the registry exists] →
explicitly flagged as temporary above; `add-agent-multi-model-registry`'s tasks include bringing
the two back in sync, not treating the hand-written file as permanent.

[Provider credentials now live in one more process's environment (the gateway's), widening the
set of places a leak could occur] → same env-var-only, never-logged discipline as the platform's
existing `KeyProvider`/`Redactor`; the gateway's own logs/export paths must be checked for key
leakage before any provider deployment is added to its config (tracked in tasks.md).

## Migration Plan

Pure addition: no existing process is modified or has traffic shifted to it in this phase. Stand
up the gateway, configure the one model group pair, verify it reachable and routing correctly
(`curl` against its completion endpoint with the virtual key), and stop - no rollback plan is
needed because nothing yet depends on it.
