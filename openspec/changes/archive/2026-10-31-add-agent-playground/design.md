# Design

## Context

See `proposal.md` - Why/What Changes for motivation. Relevant current state:

- `Agent.token_hash`/`token_prefix` store only a salted hash of the ingest token (`Provider`/D4
  convention, mirrored everywhere else in this codebase - no credential is ever stored reversibly
  today).
- `Agent.kind` is a two-value enum (`chatbot`/`reasoning`); `classifier_router_agent.py` registers
  itself under `reasoning`, reusing its built-in rubric.
- `agents/chatbot.py`, `agents/reasoning_agent.py`, `agents/classifier_router_agent.py` are each a
  standalone script with CLI flags for model/gateway/discovery config; none accepts a system-prompt
  override, a skill, or a one-shot task input - each has its own hardcoded prompt and
  stdin/interactive entry point.
- Gateway virtual keys are minted by an operator running `curl .../key/generate` by hand
  (`gateway/README.md`); the backend has no code path that calls this endpoint today.
- `backend/app/core/eval_worker.py`'s `EvaluationWorker` already calls a model directly via
  `ModelRouter`, outside any benchmark Run, for judge calls - precedent for "the backend originates
  a model call" existing already, though this change does not reuse that path: it spawns the
  agent's own script as a subprocess instead, per the user's explicit choice of running the real
  implementation, not a backend-native reimplementation.
- `frontend/src/api/useAgentEvents.ts` already provides a per-agent SSE live-event feed
  (`state`/`turn_started`/`turn_finished`/...) that any agent's turns flow through today,
  regardless of how that agent's process was started.
- No encryption dependency exists anywhere in this codebase today (checked `backend/pyproject.toml`
  and `app/`) - every secret today is either hash-only or an externally-held env-var name
  (`Provider.key_env`).

## Goals / Non-Goals

**Goals:**
- Let a user spawn any of the three reference agent *scripts*, unmodified in their core logic,
  from the UI with a custom system prompt, attached skills, and a one-shot task.
- Make a UI-spawned turn and a terminal-run turn indistinguishable once ingested.
- Automate what is today a manual `curl` (gateway virtual-key minting) for agents that opt in.

**Non-Goals:**
- Multi-turn chat sessions with a persistent process (explicitly deferred to a future change; see
  proposal's confirmed scope - one spawn is one task, one turn, process exit).
- Spawning a third-party, non-catalog agent's arbitrary script. The catalog is seeded with the
  three reference flavors; adding a fourth is a catalog-file change, not a UI feature, in this
  phase.
- A general-purpose secrets manager. The encryption mechanism below is scoped to exactly the two
  new credential fields this change introduces.
- Changing how a *non*-playground-eligible agent is registered, credentialed, or run. That path is
  untouched.

## Decisions

### D1: Spawn the real script as a subprocess, supervised by the backend
Rejected alternative: a backend-native "playground" that calls a model directly via `ModelRouter`
(the `EvaluationWorker` precedent). The user explicitly wants the agent's *actual* bespoke logic
(reasoning_agent's classify/plan/solve/verify pipeline, classifier_router_agent's real graph + MCP
+ hand-off) exercised, not a generic chat call standing in for it. A subprocess is therefore the
only option that is faithful to what "select reasoning-agent" means. The backend becomes a process
supervisor for exactly this one case: `asyncio.create_subprocess_exec(*catalog_entry.command, env=...)`,
with stdout/stderr captured for diagnostics (not parsed - the agent's own ingest calls are the
source of truth for turn data, matching how a terminal-run instance already works). One in-flight
spawn per agent, tracked in memory, rejecting a second concurrent request (`agent-playground`'s
"second spawn is rejected" scenario) - this avoids two processes racing to use the same ingest
token/session and keeps v1's lifecycle trivial (no process pool, no queueing).

### D2: A new, explicit "encrypted secret" column type, used only for these two fields
Two new nullable columns on `Agent`: `playground_ingest_token_enc` and `playground_gateway_key_enc`,
both `bytes`, populated only when `playground_eligible` is true. Encrypted with Fernet
(`cryptography` package - a new dependency) keyed by a new `EVAL_SECRET_KEY` environment variable
the operator sets once (read at startup, same "unset = feature off" convention `Settings.otel_endpoint`
already uses: with no key configured, marking an agent playground-eligible is rejected with a clear
error naming the missing env var, rather than silently storing something unrecoverable or failing
in an obscure way at first spawn). Decryption happens only inside the spawn code path, in-process,
immediately before launching the subprocess - never exposed through any read API (`agent-playground`'s
"never returned in plaintext" scenario).

Alternative considered: ask the operator to re-paste the plaintext token/key into every spawn
request instead of storing it. Rejected - it reduces to the terminal workflow this change exists to
remove, and contradicts the user's explicit "configure once in agent settings... then ready for
use."

Alternative considered: store these in the OS keychain / an external secrets manager instead of the
database. Rejected for this phase as disproportionate - this project has no existing secrets-manager
dependency, and a single symmetric key read from one env var matches the project's existing
"operator sets an env var, backend reads it once at startup" pattern elsewhere (`EVAL_OTEL_ENDPOINT`,
provider `key_env`'s *mechanism*, if not its hash-only *policy*).

### D3: A static, repo-shipped catalog file, not a database table
`agents/catalog.yaml` lists the three flavors with their entrypoint command template, declared-model
task slots, and the fact that they accept `--system-prompt`/`--skill`/`--task`. Loaded read-only by
the backend at startup (mirrors `model_pricing.yaml`'s existing loading pattern). Not a DB table
because it changes only when a new agent flavor ships with the codebase - an engineering event, not
an operator action - exactly like the reference agents themselves today.

### D4: New CLI flags on the three scripts, not a JSON spawn-config file
`--system-prompt TEXT`, `--skill NAME` (repeatable), `--task TEXT` added to each script's existing
argparse setup, consistent with their current flag-based configuration style (`--model`,
`--otel-endpoint`, `--reasoning-model-group`, etc.) - confirmed with the user over a JSON-config-file
alternative. Each script resolves `--skill` names to content by calling the platform (a thin
GET per name, using its own ingest token for auth - the same discovery-call pattern
`_discover_agent_name()` already established) and prepends the fetched instructions, in flag order,
to whichever system prompt is in effect. `--task` replaces each script's interactive/stdin loop for
that one invocation: it answers the one task and exits, leaving the existing loop entry point
intact and default when `--task` is not given (so a terminal operator's existing muscle memory for
running these scripts interactively is unaffected).

### D5: The spawn endpoint passes the agent's catalog entrypoint command plus flags, built server-side
The backend resolves `(agent.declared_models, agent's fallback groups, decrypted ingest token,
decrypted gateway key, discovered otel endpoint, request's prompt/skills/task)` into the exact
argv the terminal operator would have typed, then launches it. This keeps the three scripts'
own code the single source of truth for how a flag is consumed - the backend only ever assembles a
command line, never reimplements flag-handling logic.

### D6: Reuse the existing SSE feed verbatim for the live-conversation panel
No new live-event machinery. The playground page opens `useAgentEvents.ts`'s existing per-agent feed
for the spawned agent's id the moment spawn is requested; `turn_started`/`turn_finished` already
fire from the same ingest path a terminal-run instance uses. The only new frontend piece is the page
itself (agent/flavor picker, prompt/skill/task form, spawn button, embedded live panel) - not a new
streaming mechanism.

### D7: A router's hand-off target is named explicitly, by name, on the router's own registration
**Discovered during implementation, not anticipated in the original proposal.** `classifier_router_agent.py`
requires its hand-off target's own ingest token and gateway virtual key as required CLI flags
(`--reasoning-agent-token`/`--reasoning-agent-gateway-key`) - unconditionally, regardless of
whether a given turn's routing decision actually hands off. Nothing in the registry recorded which
agent a router hands off to, so the spawn module had no way to resolve whose credentials to
decrypt and pass.

Added `Agent.handoff_agent_names` (a `list[str]`, default `[]`) - each target is named by its own
unique, user-facing registration name, not an internal id the user never sees or types (the user's
own explicit preference when this gap was raised). Validated at registration/update time: only
meaningful for a `router`-kind agent, which must declare at least one entry (mandatory, not
optional - a router with none could never hand anything off); every entry must name an
already-registered agent (of *any* kind - see the "any kind" revision below), be distinct from
every other entry, and never name the router itself. At spawn time, the spawn module resolves the
*first* name to that agent's own row and requires it to be playground-eligible too (its stored,
encrypted credentials are what gets decrypted and passed) - a router whose hand-off target was
never made playground-eligible is a visible spawn-time error, not a missing flag the subprocess
would reject less clearly on its own.

**Revised during implementation (list, not scalar) - also found via the user's own review, not
just live testing.** A single `handoff_agent_name: str | None` was built first, then corrected:
baking `classifier_router_agent.py`'s own one-target limitation into the *registry's* data model
was wrong - the registry itself should place no limit on how many hand-off agents a router
declares, even though today's one reference router script only ever consumes the first. The cap
belongs to the catalog *flavor*, not the registry: `agents/catalog.yaml`'s `router` entry gained
`max_handoff_agents: 1`, and the spawn module raises a clear `SpawnError` (not an obscure
subprocess-argv failure) when a router is configured with more hand-off agents than its chosen
flavor's script can actually consume. A future flavor whose script genuinely supports more would
simply declare a higher cap (or none, for "no limit"). Migrated via the same two-step
add-then-drop pattern `add-agent-multi-model-registry` used for `declared_model` ->
`declared_models` (migrations 0018/0019) - an early rollback needs no data recovery.

**Revised again during implementation (any kind, not just `reasoning`) - also found via the user's
own review.** The original validation also required every hand-off target to be `kind ==
"reasoning"`. Removed for the same reason as the count cap above: nothing in the actual spawn
mechanism depends on a target's registered kind - `app.core.playground_spawn`'s router branch only
ever checks that the target is playground-eligible with valid credentials, never its kind, and
`classifier_router_agent.py` always spawns `reasoning_agent.py` literally for any target, under
that target's own identity, regardless of what kind it is registered as. A target's own `kind` is
therefore purely descriptive of its own registration (used for e.g. its own default rubric, its
own playground-flavor matching) and was never something the handoff mechanism actually validated
against. Removing the constraint also removed `_check_kind_change`'s matching check (a target's
kind could previously not be changed away from `reasoning` while a router depended on it - no
longer a real dependency) and the now-unused `get_agents_with_handoff_target` helper that backed it.

**Revised a third time during implementation (`add-chatbot-handoff`) - `classifier_router_agent.py`
genuinely spawns one of two different scripts, not always `reasoning_agent.py`.** Until now, every
hand-off target's own `kind` was purely descriptive (per the revision above) - the script only ever
knew how to spawn `reasoning_agent.py`, so what a target was registered *as* never changed what
ran. That stopped being true once the script itself gained a second hand-off kind: the routing
decision's own `target_kind` (`"reasoning"`, default, or `"chatbot"`) now picks which reference
script actually gets spawned, and the target's registered `kind` is what the *spawn module* uses to
resolve which of a router's `handoff_agent_names` plays which role.

`AgentFlavor.max_handoff_agents` (a flat count cap) was replaced outright by `AgentFlavor.
handoff_kinds` (`list[str]`, e.g. `[reasoning, chatbot]` for the `router` flavor) - the count cap
could never have expressed "at most one of *each* kind," which is this flavor's actual limitation
now that there are two kinds to resolve rather than one. `app.core.playground_spawn`'s router branch
groups the router's configured `handoff_agent_names` by each target's own registered `kind`,
keeping at most one target per kind listed in `handoff_kinds` (more than one of the *same* kind is
a clear `SpawnError` - the script has no way to pick between two same-kind targets) and skipping
(not erroring on) a target whose kind isn't in `handoff_kinds` at all, as long as at least one
usable target remains. Each resolved kind gets its own CLI flags: `reasoning` via
`--reasoning-agent-token`/`--reasoning-agent-gateway-key` (unchanged), `chatbot` via
`--chatbot-agent-token` alone - `chatbot.py` never talks to the gateway (no `--gateway-key` flag
exists on it at all), so no corresponding gateway-key flag was added for it.

Both hand-off credential flag pairs on `classifier_router_agent.py` itself were relaxed from
required to optional (a run that will never route to a given kind need not supply its credentials -
genuinely backward compatible, since every existing caller that already passes them keeps working
identically); a routing decision that *does* resolve to a kind this run has no credentials for fails
that turn visibly (a clear `RuntimeError` naming the missing flag) rather than silently misrouting
or crashing on a `None` token deep inside the spawn helper. `chatbot.py` itself has no
self-discovery of its own declared model (unlike `reasoning_agent.py`'s group-name discovery), so
the chatbot branch discovers the hand-off target's declared model on its behalf via `whoami()`,
using the target's own token, and passes it through explicitly as `--model` - falling back to
`chatbot.py`'s own hardcoded default when discovery finds nothing, never blocking the handoff.

The hand-off tool-call span's name/description also became kind-dependent
(`handoff_to_reasoning_agent` / `handoff_to_chatbot_agent`) rather than always literally naming
"reasoning" - continuing the same "never show a misleading static label" principle the real
discovered target-name fix (above) already established for `target_agent`.

`routing_mcp/routes.yaml`'s own rule shape gained an optional `target_kind` field on a `handoff`
action (defaulting to `"reasoning"` when a rule omits it, so every rule set written before this
change keeps resolving exactly as before) - no change to `routing_mcp/server.py`'s `resolve()`
itself was needed, since it already returns a rule's action dict verbatim (minus `task`/`label`);
`target_kind` simply flows through like any other action field. The reference `routes.yaml` was
extended to demonstrate all three branches using the classifier's only two loaded tasks
(`add-classifier-router-agent`'s design.md: `ag_news`/`spam`) - `spam` still short-circuits; the
`ag_news` topics `Sports`/`World` now hand off to a chatbot target; the remaining `ag_news` topics
(matched by the trailing `"*"`, i.e. `Business`/`Sci-Tech`) keep the original behavior, handed off
to a reasoning target. This is explicitly a demonstration split documented as such in both
`routes.yaml` and `agents/README.md`, not a claim that an `ag_news` topic label reliably predicts
how much reasoning a given problem needs - a real deployment would key its own rules off whatever
classifier tasks/labels it actually has.

Alternative considered: reference the target by internal database id. Rejected per explicit
preference - an id is not something an operator configuring a router agent would know or want to
look up, while the target's own registration name is already what they'd use anywhere else in the
UI to find it.

## Risks / Trade-offs

- **[Risk]** A new reversible-secret mechanism is a meaningfully larger attack surface than this
  codebase has had before (a leaked `EVAL_SECRET_KEY` decrypts every stored playground credential).
  → **Mitigation**: scope it to exactly two fields, used by exactly one code path (spawn), never
  read back through any API; document `EVAL_SECRET_KEY` rotation as "re-encrypt both columns for
  every playground-eligible agent, or simpler, re-mark each eligible (re-captures credentials under
  the new key)."
- **[Risk]** A spawned subprocess that never exits (bug, hang, runaway loop) leaks the "one spawn at
  a time" lock forever, permanently blocking that agent's playground use.
  → **Mitigation**: a hard wall-clock timeout on the subprocess (killed and the lock released,
  surfaced as a spawn failure) - a bound every one-shot CLI invocation already has implicitly (an
  operator would eventually Ctrl-C it); this change makes that bound explicit and automatic.
- **[Risk]** `--skill` resolution adds a new, synchronous platform call inside each script's startup
  path, which did not exist before - a slow or unreachable platform now delays every spawn, even a
  terminal-run one that happens to pass `--skill`.
  → **Mitigation**: same timeout/fail-visibly posture the scripts already use for self-discovery
  (`_discover_agent_name()`) - skill resolution failing is a visible startup error, not a silent
  hang.
- **[Trade-off]** Classifier-router's hand-off still spawns a hand-off target's own reference
  script (`reasoning_agent.py` or, since `add-chatbot-handoff`, `chatbot.py`) as its own child
  subprocess exactly as it does today - a playground-spawned router is therefore a process spawning
  a process. Accepted as-is: this already works from a terminal, and the UI only ever manages the
  top-level orchestrator's lifecycle, matching the "pick one agent from the catalog" model the user
  confirmed (not "pick two or three").

## Migration Plan

1. Add `cryptography` dependency; add `Agent.playground_eligible`, `Agent.flavor`,
   `playground_ingest_token_enc`, `playground_gateway_key_enc` columns (migration) - all nullable,
   defaulting every existing row to non-eligible, so no existing agent or its credentials are
   touched.
2. Ship `agents/catalog.yaml` and the three scripts' new flags - purely additive CLI surface,
   existing terminal invocations without the new flags behave exactly as before.
3. Add the gateway virtual-key mint/rotate wiring to `gateway_sync.py`, gated entirely behind
   `playground_eligible` - a non-eligible agent's sync path is unchanged.
4. Add the spawn endpoint, catalog-read endpoint, and skill-fetch-for-single-use endpoint.
5. Add the frontend playground page.
6. Rollback at any step: the new columns/flags/endpoints are additive and inert for every
   already-registered, non-eligible agent; reverting is deleting the new code paths, not undoing
   data for existing agents.

## Open Questions

- Exact wall-clock timeout for a spawn (mentioned in Risks) - a reasonable default (for example,
  five minutes) can be chosen during implementation without changing any spec or the task
  breakdown.
- Whether `EVAL_SECRET_KEY` rotation tooling ships in this change or is documented as a manual
  runbook step for a later change - does not affect the specs or this change's own tasks either
  way.
