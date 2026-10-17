# Design

## Context

See `proposal.md` - "Why". `backend/app/core/gateway_sync.py` already has
`agent_slug(name) -> slug` and `model_group_name(slug, task_type) -> f"{slug}__{task_type}"` -
pure, deterministic functions with no I/O, used today only by the sync step itself.
`backend/app/api/ingest.py`'s existing `POST /v1/events` route shows the established pattern for
ingest-token auth: `_bearer_token(authorization)` -> `repo.verify_agent_token(session, token)` ->
`401` on `None`, `403` on a paused agent for event-sending (note: "paused" blocks *sending events*,
not reading - see Decisions below for why `whoami` does not apply that same block).
`agents/eval_agent_sdk/__init__.py`'s `AgentClient` is built entirely around a background queue +
worker thread for fire-and-forget event delivery; it has no existing synchronous request/response
helper to extend.

The user's own framing of this approach named the exact trade-off to resolve: *"No manual
bookkeeping per run, but is new backend surface + a slug-computation duplicated in two places (or
shared via a tiny published helper)."*

## Goals / Non-Goals

**Goals:**
- Eliminate the manual "look up and pass the exact gateway group name" step for the common case.
- Guarantee the agent's derived group names can never drift from what the backend's own sync
  actually created, by construction, not by convention or a shared library kept in version-lockstep
  across two independently deployable codebases.
- Preserve the existing explicit-override flags and today's no-config default behavior as fallbacks,
  so this is a strict improvement with no new required step for the simplest case.

**Non-Goals:**
- A general-purpose "agent configuration API" beyond identity/group-name discovery. `whoami`
  returns exactly `name`, `kind`, `declared_models`, `gateway_model_groups` - nothing about
  evaluators, rubrics, or other settings an agent process has no business reading.
- Caching, polling, or live-updating an agent's discovered group names after startup. Discovery
  happens once, at process start; if an agent is renamed or re-declared while a long-running
  process is already up, that process keeps using what it discovered at startup (matching how the
  explicit CLI flags already behave today - they are also fixed for the process's lifetime).
- Changing how `declared_models` or the gateway sync step themselves work. This proposal only adds
  a read path on top of state `add-gateway-model-sync` already computes and (for the sync groups
  specifically) already pushed to the gateway.

## Decisions

**Resolve the stated trade-off by choosing neither of its two named options.** The user's framing
offered two choices: duplicate the slug computation in the agent's own code, or share it via "a
tiny published helper." Both still require the agent to *compute* a slug itself. This design
instead has the backend compute the slug and the full group name, and return the group name
directly in the `whoami` response (`gateway_model_groups: {"reasoning": "my-agent__reasoning"}`).
The agent never calls `agent_slug()` or needs to know the `<slug>__<task_type>` convention exists
at all - it just reads a string. This removes the duplication concern entirely rather than
mitigating it: there is exactly one place (`gateway_sync.py`) that knows how a slug or group name
is formed, and the `whoami` endpoint is the only other caller of it, in-process, in the same
codebase. Nothing about the naming convention needs to be re-published, versioned, or kept in sync
across the backend/agents language or deployment boundary.

**Alternative considered and rejected**: publish `agent_slug`/`model_group_name` as a tiny shared
package (or inline duplicate) importable by both `backend/` and `agents/`. Rejected because it adds
a new internal dependency (or copy-paste duplication the user's own framing flagged as a real
cost) to solve a problem the "backend computes the answer" design doesn't have in the first place.
If a *third* consumer ever needs to compute a group name independently of a network call to the
backend (e.g. an offline tool), this alternative could be revisited then - but no such consumer
exists today.

**Auth reuses `repo.verify_agent_token` exactly as `POST /v1/events` does, but `whoami` does not
reject a paused agent.** Pausing blocks an agent from *sending live traffic into evaluation* - it
is a data-flow control, not an identity lock. An operator debugging why a paused agent isn't
behaving as expected should still be able to ask it "what groups do you think you're using?"
without first unpausing it. This is a deliberate, narrow difference from the events endpoint's
behavior, not an oversight - called out explicitly here since it needs its own scenario (see specs
delta) rather than silently inheriting the stricter behavior.

**`whoami` is a synchronous call from a new SDK helper function, not a method on `AgentClient`.**
`AgentClient` is designed around background delivery; discovery is a one-shot, must-complete-or-
fall-back-visibly call made once before any turns start. Making it `AgentClient.whoami()` would
pull platform-URL/token plumbing the class already has, but would also imply it belongs to the same
fire-and-forget contract as event sending, which it explicitly does not (a `whoami` failure needs
to be observed and acted on - fall back to hardcoded defaults with a visible warning - rather than
silently retried in the background). A standalone function,
`eval_agent_sdk.whoami(platform_url: str, token: str, *, timeout: float = 10.0) -> dict`, keeps
this distinction visible in the SDK's own public surface.

**`reasoning_agent.py`'s discovery call happens once, in `main()`, before `run_once`/`run_suite`.**
Discovered (or overridden, or defaulted) group names are resolved to concrete strings before any
turn starts, then threaded through exactly the way explicit CLI flags already are today - no
per-call discovery, no new code path inside `solve_one`.

## Risks / Trade-offs

- **An extra network round-trip at agent startup** → Mitigation: once, not per-turn or per-call;
  a short timeout (10s default) with a clear fall-back-to-defaults-and-warn path bounds the worst
  case to "starts anyway, slightly slower, using the same defaults it would have used before this
  change existed."
- **`whoami` is a new authenticated read surface; a compromised ingest token now also discloses
  `declared_models`** → declared models are not secret (visible in the platform UI to anyone who
  can view the agent already) and no credential is ever returned, so this does not meaningfully
  change the ingest token's blast radius: a leaked ingest token already lets an attacker send
  arbitrary fabricated events as that agent, which is a strictly larger exposure than reading its
  own public-ish registration back.
- **Behavior now depends on backend reachability at startup, where before (with explicit flags) it
  did not** → Mitigation: the explicit-flags path still exists and still works with zero backend
  dependency beyond what event-sending already requires; the fallback-to-hardcoded-defaults path
  means a backend outage degrades to today's exact pre-this-change behavior, not a hard failure.

## Migration Plan

- Purely additive: new endpoint, new SDK helper, new (defaulted) agent startup behavior. No schema
  change, no Alembic migration.
- Existing invocations of `reasoning_agent.py` that already pass explicit
  `--reasoning-model-group`/`--generation-model-group` flags are completely unaffected - the
  override path is checked first and discovery is never attempted when it's set, so no network
  call or new failure mode is introduced for those operators.
- Existing invocations with no flags and no change in registered name keep behaving identically:
  discovery will find and return the same `reasoning-agent__*` group names the hardcoded constants
  already specify, for the `reasoning-agent`-named registration case.
- Rollback is deleting the new endpoint/route and the agent's discovery call; the explicit-flag and
  hardcoded-default paths this builds on are unaffected and remain exactly as they are today.
