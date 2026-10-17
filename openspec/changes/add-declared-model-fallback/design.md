# Design

## Context

See `proposal.md` - "Why" for the motivation and the two mechanisms tested live against the
running gateway. In short: a `fallbacks: ["<group-name>"]` field on the request is the only
mechanism confirmed to work; `POST /config/update` with `litellm_settings.fallbacks` reports
success but does not change behavior for a request that omits the per-request field.

**A correction discovered during this change's own task 3.4 live verification**: "the request" above
is not one single thing. A direct REST call to the gateway's own `/chat/completions` endpoint with
`fallbacks` in the JSON body is handled server-side by the proxy's router, which resolves the
fallback group name against its own `model_list` the same way it resolves the primary. But this
agent calls the gateway through the `litellm` **Python SDK's client-side** `completion()` (with
`api_base` pointed at the gateway and `model` prefixed `openai/<group>` - see `call_llm`'s
existing comment on that prefix), and passing `fallbacks` there invokes a *different*,
client-side fallback mechanism (`litellm_core_utils/fallback_utils.py`) that just calls
`completion()` again with whatever string is in `fallbacks`, verbatim - it does not know to apply
the same `openai/` prefix workaround to it. Verified live: an unprefixed fallback entry failed with
the identical `LLM Provider NOT provided` error a bare, unprefixed primary `model` already produces
elsewhere in this codebase. The fix is to prefix the fallback entry the same way:
`fallbacks=[f"openai/{fallback_group}"]`.

Today's sync (`add-gateway-model-sync`, `backend/app/core/gateway_sync.py`) creates exactly one
gateway group per `(agent, task type)`: `model_group_name(slug, task_type)` ->
`<agent-slug>__<task_type>`. `to_litellm_params` turns one `declared_models` entry's model
reference + `params` into the `litellm_params` body `/model/new`/`/model/update` expects.
`reasoning_agent.py`'s `call_llm` is the one place that actually issues a gateway-routed
completion call; it already resolves the concrete model that answered via `_concrete_model`
(response header, falling back to `resp.model`) regardless of which group answered, so a span
already records the right thing with no change needed there.

## Goals / Non-Goals

**Goals:**
- Let a declared model name a fallback model reference per task type, synced to its own gateway
  group.
- Have `reasoning_agent.py` pass that fallback group on its underlying request when one is
  configured, using the verified-working per-request mechanism only.
- Make this consistent with the existing "Approach A" (`add-gateway-model-sync`'s temporary
  explicit CLI-flag pattern) for how an agent process learns its own group names, rather than
  inventing a second, different discovery convention for fallback groups alone.

**Non-Goals:**
- Gateway-wide fallback configuration (`/config/update`). Confirmed unreliable live; not relied on
  anywhere in this design.
- Multiple fallbacks per task, or a fallback chain (fallback-of-a-fallback). One fallback per task
  type is the full scope; nothing here blocks adding a list later, but a single field is simpler
  and covers the motivating case (one cloud provider, one local backstop).
- Automatic failover detection or health-based routing logic in the backend. The gateway (via
  LiteLLM) decides when to use the fallback; the platform's only job is to make sure a group
  exists for it to fall back to, and to tell the agent which group name to put in the request.
- Self-discovery of group names (including fallback group names) by the agent at runtime. That is
  the separate `add-agent-self-discovery` proposal; this change extends Approach A's existing
  explicit-flag pattern with two more flags, and self-discovery (once it lands) will cover fallback
  groups the same way it covers primary groups, with no further change needed here.

## Decisions

**`fallback` lives next to `model` in `DeclaredModelSpec`, not as a separate map.**
`DeclaredModelSpec` becomes `{model: str, params: dict | None, fallback: str | None}`. A plain
string declared-model entry (the common case, no fallback) is unaffected - this only changes the
object form. Keeping `fallback` as a bare reference string (reusing `parse_ref`/`declared_model_ref`
validation, not a nested `DeclaredModelSpec`) avoids a confusing fallback-with-its-own-fallback
shape; a fallback's generation params, if ever needed, can reuse the primary's `params` rather than
needing its own - not supporting per-fallback params is a deliberate simplification for this first
version.

**Alternative considered**: a `fallbacks: dict[str, str]` map alongside `declared_models`, keyed
by task type. Rejected: it duplicates `declared_models`' own keys and separates two facts about the
same task type into two maps that must be kept in sync by callers; putting `fallback` directly on
the entry it belongs to is simpler and mirrors how `params` already works.

**Sync creates `<agent-slug>__<task_type>__fallback`, a full second group, not a second deployment
under the primary group's name.** LiteLLM also supports multiple deployments sharing one
`model_name` with a `routing_strategy` (the mechanism the original, unimplemented
`agent-llm-gateway` scenario text could be read as describing) - but that is a *load-balancing*
construct (the router picks among same-named deployments by its configured strategy on every
call, not only on failure) and was not the mechanism verified working for an explicit,
caller-controlled fallback. A separate, explicitly-named group matches exactly what the verified
`fallbacks: [...]` request parameter expects (a list of other group names) and keeps the primary
group's `/model/info` entry showing only its own one deployment, which is clearer for the sync
status UI and gateway admin operations already built around one-group-one-deployment.

**`reasoning_agent.py` gets `--reasoning-fallback-group`/`--generation-fallback-group`, optional,
defaulting to unset (no fallback passed).** This mirrors the existing
`--reasoning-model-group`/`--generation-model-group` flags exactly (same "temporary, explicit"
status, same eventual replacement by self-discovery). `call_llm` gains an optional
`fallback_group: str | None` parameter; when set, it adds `"fallbacks": [fallback_group]` to the
kwargs passed to the completion call. `solve_one`/`run_once`/`run_suite` thread it through the same
way they already thread `reasoning_group`/`generation_group`.

**Validation**: the agent-registry acknowledgment check (`_check_provider_acks` in `repo.py`,
already generalized this session to take a flat list of refs) is reused unchanged - the fallback
reference is simply added to the same `refs` list already built from `declared_models.values()`,
alongside the primary reference and the evaluator list. No new acknowledgment code path.

## Risks / Trade-offs

- **A fallback configured for a local-to-local pair is allowed but not very meaningful** (a local
  Ollama deployment failing is rarely the transient kind of failure a fallback helps with) →
  Mitigation: not rejected outright (no strong reason to forbid it, and forbidding it would need an
  arbitrary rule to enforce), but the UI's fallback field copy explains the typical use case
  (hosted primary, local backstop) so operators aren't surprised it does nothing useful for a
  flaky local model.
- **The fallback group doubles the number of gateway groups an agent with N task types and every
  task fallback-enabled needs (`2N` instead of `N`)** → Mitigation: fallback is opt-in per task
  type (most won't set one), and the gateway virtual key documentation (`gateway/README.md`,
  "Virtual keys") already explains scoping a key to exactly the groups it needs - the agent's
  virtual key would need the fallback group added to its `"models"` allow-list the same way it
  needs the primary group, which this change documents as an operator step (not automated - virtual
  key minting is already a manual, operator-performed step today, unrelated to sync).
- **A caller that forgets to pass `fallbacks` on the request gets no fallback even though one is
  configured, with no error indicating that** → this is the direct consequence of the verified
  "gateway-wide config is unreliable" finding, not a bug in this design, but it is non-obvious at
  the call site → Mitigation: `call_llm`'s docstring and `gateway/README.md` both state plainly
  that a configured fallback group does nothing unless the caller's own code names it on the
  request; this is also why self-discovery (separate proposal) matters - it is the mechanism that
  will let an agent reliably learn whether a fallback is configured for a task without an operator
  having to tell it via a CLI flag.
- **A *successful* fallback still looked like a crash in the terminal** - found live, from the
  user's own real run against `reasoning-agent-verify`: LiteLLM's client-side fallback mechanism
  logs every failed attempt (including the primary's, even when a later fallback succeeds) via
  `verbose_logger.exception(...)` - ERROR level, always with a full traceback - plus a "Give
  Feedback / Get Help" banner per failure, plus an unrelated `asyncio`/`RuntimeWarning` pair from
  its sync wrapper spinning a new event loop per call. None of it indicates an unhandled failure -
  `run_once`/`run_suite` already print a clean one-line message for a call that fails outright -
  so it was pure noise on exactly the path this feature is supposed to make quiet (a recovered
  failure). Mitigation: `reasoning_agent.py` now sets `litellm.suppress_debug_info = True` and
  raises the `"LiteLLM"` and `"asyncio"` loggers to `CRITICAL`, plus a narrow `warnings.filterwarnings`
  for the specific "never awaited" message, all at module import time - verified live to produce
  clean stdout (just the agent's own final answer) across a real multi-call fallback run.
- **The *gateway's own* server process logs the same kind of traceback for a recovered failure, and
  this one is deliberately NOT suppressed.** Found live, same user run: the proxy's
  `verbose_proxy_logger` (a separate logger, in a separate process, from the agent-side fix above)
  always uses `.exception()` - full traceback - for any provider-originated failure
  (`is_expected_client_error` returns `False` for it), by design, regardless of whether a caller's
  `fallbacks` subsequently recovers the request. The only lever is the gateway-wide `LITELLM_LOG`
  env var, which would also quiet a deployment that fails outright with *no* fallback configured -
  a real loss of operator-facing diagnostic signal, not a pure noise fix like the agent-side case.
  Decision (confirmed with the user): leave the gateway's own logging as-is: a provider failure
  remains loudly visible in the gateway's log even when a fallback masks it from the caller, so an
  operator still notices a backend is broken. Not implemented.

## Migration Plan

- Additive schema change (`fallback` is optional); no migration needed for existing agents or
  stored `declared_models` JSON - absent means "no fallback," matching today's implicit behavior
  exactly.
- No new Alembic migration: `declared_models` is already a JSON column (not a normalized table),
  so a new optional key inside its value needs no schema change.
- Existing gateway groups are untouched; fallback groups are created only when an operator sets a
  `fallback` on a declared model.
- `reasoning_agent.py`'s new flags default to "no fallback" - existing invocations (including the
  user's own already-running `reasoning-agent-verify` setup) are unaffected until the operator
  opts in.

## Open Questions

- Whether `fallback` should eventually become a list (fallback chain) once more than one provider
  needs backstopping in practice - deferred; today's single-field shape doesn't block adding a list
  later, since it's an additive schema change either way.
