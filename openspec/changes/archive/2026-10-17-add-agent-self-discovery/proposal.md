# Proposal

## Why

`add-reasoning-agent-task-routing` hardcoded the reasoning agent's gateway model group names to
`reasoning-agent__reasoning`/`reasoning-agent__generation`. `add-gateway-model-sync`'s "Approach
A" (already implemented) made these overridable via `--reasoning-model-group`/
`--generation-model-group` CLI flags, but that is an explicit, documented **temporary stopgap**:
every time an agent process is run under a different registered name (as the user did, registering
`reasoning-agent-verify`), the operator must separately look up and pass the exact synced group
name by hand, on every invocation, or the agent silently calls the wrong (default) group. This
does not scale past one or two hand-run agents and has no way to stay correct automatically if an
agent is ever renamed.

This proposal implements the deferred "Approach B" from that discussion: the agent discovers its
own registered identity and gateway group names itself, at startup, using the same ingest token it
already holds - removing the manual bookkeeping entirely while keeping the override flags
available for cases that still need them (e.g. pointing a test run at a different agent's groups).

## What Changes

- A new endpoint, `GET /api/ingest/v1/whoami`, authenticated exactly like
  `POST /api/ingest/v1/events` (the same `Authorization: Bearer <ingest-token>` check, the same
  paused-agent rejection), returns the calling agent's own `name`, `kind`, `declared_models`, and -
  critically - its already-computed gateway model group name for each declared task type
  (`gateway_model_groups: {"reasoning": "reasoning-agent-verify__reasoning", ...}`). The endpoint
  computes these with the exact same `agent_slug()`/`model_group_name()` functions
  `gateway_sync.py` already uses for the real sync calls, so the two can never drift apart - there
  is no second slugging algorithm to keep in sync by convention, because the agent never computes
  a slug at all; it only reads the string the backend already computed.
- The response never includes the ingest token, any gateway credential, or any provider secret -
  only the `name`/`kind`/`declared_models`/`gateway_model_groups` the user explicitly asked for.
- `agents/eval_agent_sdk` gains a small synchronous helper (not part of the background event-queue
  machinery, since this is a one-time, must-succeed-or-fail-clearly call made before an agent
  starts its work, unlike the fire-and-forget event stream) that calls this endpoint and returns
  its JSON.
- `reasoning_agent.py` calls this helper once at startup when `--reasoning-model-group`/
  `--generation-model-group` are not explicitly passed (and `--model` is not set), using the
  discovered `gateway_model_groups` instead of the hardcoded `REASONING_MODEL_GROUP`/
  `GENERATION_MODEL_GROUP` constants. The explicit flags remain available and, when passed, always
  win over discovery (an explicit override is never silently second-guessed). If discovery itself
  fails (platform unreachable, token rejected) and no explicit flag was given, the agent falls back
  to the existing hardcoded constants and logs a visible warning, rather than failing to start -
  preserving today's zero-config "just works against the dev-default gateway groups" behavior for
  the common case where the agent genuinely is registered as `reasoning-agent`.

## Capabilities

### Modified Capabilities
- `agent-registry`: adds the agent-facing "discover my own registration" requirement - a new
  ingest-token-authenticated read endpoint, distinct from the existing ingest-events endpoint
  (`trace-ingestion`), but governed by `agent-registry` since what it returns (name, kind, declared
  models) and the credential it authenticates with are both `agent-registry` concepts.
- `reference-agents`: the reasoning agent's default mode for learning its own gateway group names
  changes from "hardcoded `reasoning-agent__*` constants, overridable by CLI flag" to "discovered
  from the platform at startup via `whoami`, overridable by CLI flag, falling back to the hardcoded
  constants only if discovery itself fails."

## Impact

- `backend/app/api/ingest.py` (new `GET /v1/whoami` route, reusing `_bearer_token`/
  `repo.verify_agent_token`).
- `backend/app/core/gateway_sync.py` (`agent_slug`, `model_group_name` - reused, not duplicated, by
  the new endpoint).
- `backend/app/repo.py` or a small new serializer for the `whoami` response shape.
- `agents/eval_agent_sdk/__init__.py` (new `whoami(platform_url, token)` helper).
- `agents/reasoning_agent.py` (`main`, CLI flag handling, module docstring).
- `agents/README.md` (documents the new default discovery behavior, marks the explicit
  `--reasoning-model-group`/`--generation-model-group` flags as an override rather than the primary
  mechanism).
