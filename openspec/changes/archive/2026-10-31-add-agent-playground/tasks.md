# Tasks

## 1. Data model and migration

- [x] 1.1 Add `cryptography` to `backend/pyproject.toml` and verify `pip install -e .` (or
  equivalent) resolves it
- [x] 1.2 Add `Agent.kind` enum value `router` in `app/schemas.py`'s `AgentKind` literal and verify
  a `router`-kind registration request passes schema validation while an invalid kind is still
  rejected
- [x] 1.3 Add `Agent.playground_eligible` (bool, default False), `Agent.flavor` (nullable str),
  `Agent.playground_ingest_token_enc` (nullable bytes), `Agent.playground_gateway_key_enc`
  (nullable bytes) columns plus an Alembic migration, and verify the migration applies cleanly to
  an existing dev database with every current row defaulting to non-eligible
- [x] 1.4 Add `EVAL_SECRET_KEY` to `app/config.py`'s `Settings` (unset-by-default, read once at
  startup) and verify marking an agent playground-eligible is rejected with a clear error naming
  the missing env var when it is unset
- [x] 1.5 (discovered during implementation, design.md D7) Add `Agent.handoff_agent_name` plus a
  migration, and validate it in `repo.py` (router-kind only, must name an existing reasoning-kind
  agent, never itself); verify tests for each rejection and the accepted case
- [x] 1.6 (revised per user review, design.md D7) Replace `handoff_agent_name` with
  `handoff_agent_names` (`list[str]`) - the registry places no limit on how many hand-off agents a
  router declares, even though today's one reference router script only consumes the first;
  migrated via the same two-step add-then-drop pattern as `declared_model` -> `declared_models`
  (migrations 0018/0019). Made mandatory (non-empty) for a `router`-kind agent at registration, not
  just on later settings saves - a router with none configured could never hand anything off.
  Added `AgentFlavor.max_handoff_agents` (`agents/catalog.yaml`: `router` flavor declares `1`) and
  a spawn-time check in `playground_spawn.py` that rejects a router configured with more hand-off
  agents than its chosen flavor's script can consume, with a clear `SpawnError` rather than an
  obscure subprocess-argv failure; verified with tests for duplicates, >1 accepted at the registry
  level, and the flavor-cap rejection at spawn time
- [x] 1.7 (revised per user review, design.md D7) Removed the `target.kind != "reasoning"` check
  from `_check_handoff_agent_names` - a hand-off target's own registered kind is purely descriptive
  and unconstrained (`chatbot`/`reasoning`/`router` all valid); nothing in `playground_spawn.py`'s
  router branch or `classifier_router_agent.py`'s own spawn mechanism depends on it. Also removed
  `_check_kind_change`'s now-obsolete matching check (a target's kind could no longer be blocked
  from changing away from `reasoning`) and the `get_agents_with_handoff_target` helper that backed
  it, both now unused. Updated both frontend hand-off pickers (Settings, registration) to stop
  filtering candidates to `kind === 'reasoning'`, showing each candidate's kind alongside its name
  instead; verified with tests for a non-reasoning target being accepted and a target's kind being
  freely changeable while still named as a hand-off target
- [x] 1.8 (`add-chatbot-handoff`, discovered during implementation, design.md D7) Gave
  `classifier_router_agent.py` a second hand-off kind: a routing decision's `target_kind`
  (`"reasoning"`, default, or `"chatbot"`) picks which reference script gets spawned.
  `AgentFlavor.max_handoff_agents` (a flat count cap) was replaced by `AgentFlavor.handoff_kinds`
  (`agents/catalog.yaml`'s `router` flavor: `[reasoning, chatbot]`) - `playground_spawn.py`'s
  router branch now resolves at most one hand-off target of each listed kind (a `SpawnError` on two
  of the same kind; a target of an unlisted kind is skipped, not an error, as long as one usable
  target remains), wiring `--reasoning-agent-token`/`--reasoning-agent-gateway-key` for a
  `reasoning`-kind target and `--chatbot-agent-token` alone for a `chatbot`-kind one (`chatbot.py`
  never talks to the gateway). Both of `classifier_router_agent.py`'s own hand-off credential flag
  pairs were relaxed from required to optional (backward compatible); a routing decision wanting a
  kind this run has no credentials for now fails that turn visibly. The chatbot branch discovers
  its target's declared model via `whoami()` (using the target's own token) since `chatbot.py` has
  no self-discovery of its own, and passes it through as `--model`. `routing_mcp/routes.yaml`
  gained an optional `target_kind` field on `handoff` rules (default `"reasoning"`, so pre-existing
  rule sets are unaffected) and was extended with a demonstration three-way split documented as
  such; `routing_mcp/server.py` needed no code change (its generic action-dict passthrough already
  carries `target_kind`). Verified with tests for: the chatbot branch spawning `chatbot.py` instead
  of `reasoning_agent.py`, model discovery being passed through, a failed/missing-credentials
  chatbot handoff each failing visibly, the symmetric missing-credentials case for reasoning, an
  unsupported `target_kind` failing visibly, and `playground_spawn.py`'s per-kind resolution
  (ambiguous same-kind rejection, both kinds wired together, an unusable-kind target skipped, no
  usable target at all rejected)
- [x] 1.9 (found via live testing) Fixed `routing_mcp`'s `resolve()`: a bare label match was enough
  to short-circuit a turn as spam, even when the classifier's `spam` confidence was barely above its
  0.5 binary decision boundary (e.g. 0.54) for a problem the *other* loaded task (`ag_news`)
  classified with real confidence (0.79) - a genuine partial-differential-equation problem was
  discarded as spam with zero chance to answer it. Added an optional `min_confidence` field to a
  rule; a label match below it is treated as no match at all and resolution keeps checking the
  remaining rules, rather than guessing which signal to trust. The reference `routes.yaml`'s `spam`
  rule gained `min_confidence: 0.8` - short-circuiting is this rule set's most consequential action
  (it discards the problem outright, no model ever sees it), so it gets the file's highest bar.
  `server.py`'s `resolve_route` tool itself needed only its own matching loop touched - the field is
  read generically, same as `target_kind` before it. Verified with tests for: a below-threshold
  label match falling through to the next rule, an at/above-threshold match still winning, a
  missing `confidence` on a gated rule never being assumed sufficient, and an ungated rule
  (every `ag_news` rule here) still matching on label alone as before this field existed

## 2. Encryption helper

- [x] 2.1 Add a small `app/core/secrets.py` wrapping Fernet encrypt/decrypt keyed by
  `Settings.playground_secret_key`, and verify a round-trip unit test (encrypt then decrypt returns
  the original plaintext) and a missing-key unit test (encrypt raises a clear, catchable error)
- [x] 2.2 Verify no code path outside the spawn flow ever calls the decrypt function, via a grep-based
  or import-boundary test asserting `secrets.decrypt` is referenced only from the spawn module

## 3. Agent flavor catalog

- [x] 3.1 Create `agents/catalog.yaml` listing `chatbot`, `reasoning`, `router` flavors, each with
  its entrypoint command, declared-model task slots, and its accepted new flags, and verify a
  schema/lint check (e.g. a small loader script) parses it without error
- [x] 3.2 Add a backend loader for the catalog (mirrors `model_pricing.yaml`'s existing loading
  pattern) and a read endpoint, and verify a request returns the three flavors with their task
  slots

## 4. Reference agent script changes

- [x] 4.1 Add `--system-prompt`, `--skill` (repeatable), `--task` flags to `agents/chatbot.py`;
  implement skill-name-to-content resolution via a platform GET call using the agent's own ingest
  token; verify unit tests for: override replaces the default prompt, skills prepend in order, and
  `--task` answers once and exits without entering the interactive loop
  (`--system-prompt` already existed on this script; added `--skill`/`--task` and skill resolution)
- [x] 4.2 Add the same three flags to `agents/reasoning_agent.py`, applied to its
  planning/solving/verification prompts only; verify unit tests mirroring 4.1, plus a test that the
  classification call is unaffected by `--system-prompt`
  (`--task` is an alias for the pre-existing `--problem`, which was already one-shot)
- [x] 4.3 Add the same three flags to `agents/classifier_router_agent.py`, applied to its
  routing-decision prompt only; verify unit tests mirroring 4.1
  (`--task` is an alias for the pre-existing `--problem`, which was already one-shot)
- [x] 4.4 Update `agents/README.md` documenting the three new flags and a one-shot invocation
  example for each script

## 5. Gateway virtual-key automation

- [x] 5.1 Add a `mint_virtual_key(groups: list[str]) -> str` helper in `app/core/gateway_sync.py`
  calling the gateway's `/key/generate` with the admin key, and verify a unit test against a mocked
  gateway response
  (signature is `mint_virtual_key(session, agent, settings) -> MintResult`, deriving groups via
  the new `agent_gateway_group_names()` rather than taking them as a bare list, so it can be called
  with just the agent)
- [x] 5.2 Wire minting into the "mark playground-eligible" flow: mint a key scoped to the agent's
  currently-synced groups, encrypt it, store it; verify an integration test that marking eligible
  stores a decryptable key allow-listing exactly that agent's groups
- [x] 5.3 Wire re-minting into the existing declared-model-change sync path so a group change
  re-mints the stored key before the next spawn is accepted; verify a test that changing declared
  models updates the stored key's scope
- [x] 5.4 Add a rotate-credentials endpoint (re-mints the gateway key, re-issues and re-encrypts the
  ingest token, invalidates the previous token) and verify a test that the previous ingest token is
  rejected after rotation
- [x] 5.5 Verify minting/re-minting failures are reported on the triggering response without
  blocking it, mirroring the existing model-group sync failure behavior (integration test against
  an unreachable mocked gateway)
- [x] 5.6 (found via live testing) Fixed `mint_virtual_key()`: every re-mint (re-enabling
  playground, rotating, or a declared-model change) posted `/key/generate` with the same
  deterministic `key_alias` (`agent_slug(agent.name)`) as the agent's first-ever mint, without ever
  telling the gateway to drop that previous key - litellm enforces globally unique `key_alias`
  values, so the real gateway rejected every mint after the first with `400 Key with alias '...'
  already exists`, even though the "re-mints... discarding the previous key's value"/"mints a new
  virtual key... and discards the previous key's value" scenarios (`gateway-model-sync`) already
  specified it. Our own storage *did* discard the previous key's value (the new one simply
  overwrote `playground_gateway_key_enc`), but the gateway's own copy was left behind under that
  alias forever - an orphaned credential never actually revoked, not just the 400. Added a
  best-effort `/key/delete {"key_aliases": [alias]}` immediately before every `/key/generate` call,
  unconditionally (simpler and more robust than parsing litellm's own error text to detect "alias
  already exists" reactively, and litellm's own `/key/delete` is a no-op, not an error, when the
  alias doesn't exist yet - verified directly against its source). Verified with a test minting the
  same agent twice end to end and asserting the second mint succeeds with a genuinely different key

## 6. Spawn endpoint and process supervision

- [x] 6.1 Add the "mark playground-eligible" endpoint (validates flavor-kind match, captures and
  encrypts the current ingest token, triggers 5.2) and verify a test rejecting a flavor/kind
  mismatch
  (also added the paired disable/rotate endpoints the spec's "reversible"/rotation scenarios need)
- [x] 6.2 Add the skill-fetch-for-single-use endpoint/internal call returning stored skill content
  by name, and verify a test that a deleted skill is rejected by name
- [x] 6.3 Add the spawn endpoint: resolves the agent's catalog entrypoint command, decrypts its
  stored credentials in-process, assembles the full argv (declared models, fallback groups,
  otel endpoint, decrypted credentials, prompt, skills, task - and, for a `router`-flavor agent,
  its resolved `handoff_agent_names` first target's own decrypted credentials, design.md D7), and launches
  it via `asyncio.create_subprocess_exec`; verify an integration test that the exact expected argv
  is passed to a stubbed subprocess launcher
- [x] 6.4 Add the in-memory one-spawn-per-agent lock and a wall-clock timeout that kills the process
  and releases the lock; verify tests for: a concurrent second spawn is rejected, and a spawn
  exceeding the timeout is killed and reported as a failure
- [x] 6.5 Verify a spawn for a non-playground-eligible agent is rejected, naming why (test)
- [x] 6.6 Verify end to end (real or near-real script, local model) that a spawned turn appears in
  the agent's conversation/evaluation history identically to a terminal-run turn of the same script
  (opt-in live smoke test, `tests/test_live_smoke_playground.py`, mirroring
  `test_live_smoke_gateway.py`'s existing "skip unless a live service is configured" convention -
  the default test run never needs a live backend/Ollama/agents-venv; argv assembly and process
  lifecycle are otherwise fully covered by `test_playground_spawn.py`'s non-live tests)

## 7. Frontend playground page

- [x] 7.1 Add the Agent Playground route/page: playground-eligible agent picker, system-prompt
  editor (pre-filled from the agent's last-used value if any), skill multi-select, task textbox,
  spawn button
  (implemented as a new "Playground" tab on the existing per-agent `AgentPage`/`AgentTurnsPanel`
  shell, rather than a separate top-level route - the agent picker is `AgentsPage`'s existing list,
  now showing a "playground" badge, which already links into each agent's page; this avoids a
  second, duplicate agent list. System-prompt pre-fill from a "last-used value" was not built - no
  approved spec scenario calls for it, and adding persisted last-used state was out of this
  change's scope; flagging rather than silently matching the literal task wording)
- [x] 7.2 Add the agent-settings UI for marking an agent playground-eligible (flavor selection) and
  for triggering credential rotation (5.4)
  (enable/disable live in the new Playground tab itself, since they gate what that tab shows;
  rotation is offered from both the Playground tab and, for `handoff_agent_names`, the Settings and
  registration forms, including as a mandatory field at registration for a `router`-kind agent)
- [x] 7.3 Wire the live-conversation panel to `useAgentEvents.ts`'s existing per-agent feed for the
  spawned agent, and verify manually that a spawn's turn start/finish appear live without a manual
  refresh
  (reuses `AgentTurnsPanel agentId={agent.id} mode="live"` verbatim - the exact component the
  existing "Live" tab already uses, per design.md D6; manual live verification deferred to the same
  opt-in live smoke test group as 6.6, since it needs a real running stack)
- [x] 7.4 Verify the page's empty/loading/error states (no playground-eligible agents yet; spawn in
  progress; spawn failed) render meaningful content, matching `results-dashboard`'s existing
  usability requirement
  (`PlaygroundPanel.test.tsx`: loading/error/empty-catalog/not-yet-eligible/spawn-error states)
- [x] 7.5 (found via live testing) Fix `useAgentEvents.ts`'s `RESYNC_ON` set: it only refetched the
  turns list on `turn_finished`/`evaluation_finished`, so a freshly-spawned turn (open/in-progress)
  never appeared in the live panel until the whole run completed - minutes, for the reasoning
  flavor's four sequential calls - violating spec `agent-playground`'s "the turn's start... shown...
  without a manual refresh". Added `turn_started` to the resync set (a general fix to shared
  infrastructure, benefiting every live agent, not just a playground-spawned one); verified with a
  regression test confirmed to fail without the fix and pass with it
  (`AgentPage.test.tsx`: "shows a new turn as soon as it starts, not only once it finishes")
- [x] 7.6 (found via live testing) Fix `useAgentEvents.ts`: the single-agent query (`GET
  /agents/{id}`, which supplies the header's live/idle/offline badge) was never invalidated on any
  live event, so a freshly-spawned agent kept showing its stale pre-spawn liveness indefinitely -
  the query has no polling interval of its own (unlike the agents list) and nothing else ever
  refreshed it. Added it to the same `RESYNC_ON` invalidation already fixed in 7.5 - every event
  that lands there also just moved `last_seen_at` server-side (`touch_agent_liveness`), so it's the
  same signal, not a new one; verified with a regression test confirmed to fail without the fix

## 8. Documentation

- [x] 8.1 Update `agents/README.md` and the main `README.md`'s agent-registration section
  documenting `EVAL_SECRET_KEY`, the catalog file, and the end-to-end "register, mark eligible,
  spawn" flow
