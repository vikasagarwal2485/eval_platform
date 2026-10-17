# Tasks

## 1. Backend endpoint

- [x] 1.1 Add `GET /v1/whoami` to `backend/app/api/ingest.py`, reusing `_bearer_token`/
      `repo.verify_agent_token`; return 401 on a missing/invalid token exactly like
      `POST /v1/events`, but do NOT reject a paused agent (see design.md - "Decisions"); verify
      with a unit test for the 401 case and a test confirming a paused agent still gets 200.
- [x] 1.2 Build the response body: `{"name": agent.name, "kind": agent.kind, "declared_models":
      agent.declared_models, "gateway_model_groups": {task_type: model_group_name(agent_slug(
      agent.name), task_type) for task_type in agent.declared_models}}`, importing
      `agent_slug`/`model_group_name` from `backend/app/core/gateway_sync.py` (reused, not
      reimplemented); verify with a unit test asserting the computed group names exactly match what
      a real sync call for the same agent would use.
- [x] 1.3 Verify by inspection and a dedicated test that the response never includes `token`,
      `token_hash`, `token_prefix`, or any gateway/provider credential field - only the four fields
      above.

## 2. Agent SDK helper

- [x] 2.1 Add `whoami(platform_url: str, token: str, *, timeout: float = 10.0) -> dict` to
      `agents/eval_agent_sdk/__init__.py` as a standalone synchronous function (not a method on
      `AgentClient` - see design.md), making a plain `httpx.get` to `{platform_url}/api/ingest/v1/
      whoami` with the bearer token, raising on a non-2xx response or timeout rather than
      swallowing the error (the caller decides the fallback policy); verify with a unit test using
      a fake HTTP server or `httpx` mock covering both the success and the error-raises case.
- [x] 2.2 Export `whoami` from `agents/eval_agent_sdk/__init__.py`'s `__all__`.

## 3. Reference reasoning agent

- [x] 3.1 In `agents/reasoning_agent.py`'s `main()`, when neither `--reasoning-model-group` nor
      `--generation-model-group` was explicitly passed and `--model` is not set, call
      `eval_agent_sdk.whoami(args.platform_url, args.token)` once and use its
      `gateway_model_groups` entries for `reasoning`/`generation` in place of
      `REASONING_MODEL_GROUP`/`GENERATION_MODEL_GROUP`; verify with a unit test (mocking `whoami`)
      that the discovered names are what gets passed to `run_once`/`run_suite`. (Implemented as a
      new `_resolve_model_groups()` helper, called from `main()` - and, per the specs delta's own
      "An explicit override always wins over discovery" scenario, which says discovery's result is
      "not consulted... for that task" (not "discovery never runs at all"), `whoami()` is called
      whenever at least one of the two groups has no explicit override, not only when *both* are
      unset - so setting only `--reasoning-model-group` still lets `generation` be discovered. The
      stricter "only when neither is set" reading is also satisfied as the special case where
      neither override is given. See the dedicated test for the both-explicit case in 3.3.)
- [x] 3.2 On a `whoami` call that raises (network error, non-2xx, timeout), catch it, log a visible
      warning naming the fallback, and continue with the existing hardcoded
      `REASONING_MODEL_GROUP`/`GENERATION_MODEL_GROUP` constants; verify with a unit test that a
      simulated discovery failure still lets the agent run using the defaults.
- [x] 3.3 Confirm an explicit `--reasoning-model-group`/`--generation-model-group` flag always
      skips the discovery call entirely for that task (not just overrides its result) - verify with
      a unit test asserting `whoami` is not called when both flags are explicitly given.
- [x] 3.4 Update the module docstring: replace the "TEMPORARY stopgap" framing for the explicit
      flags with "override discovery when you need a different agent's groups," and add discovery
      as the default documented behavior with an example invocation that passes no group flags.
- [x] 3.5 Live-verify end to end against the running backend + gateway: register an agent under a
      new name, run `reasoning_agent.py` with no group-override flags and confirm (via the
      backend's turn/span view) its calls were routed through that agent's own discovered groups,
      not the hardcoded `reasoning-agent__*` defaults. Clean up test artifacts afterward.
      Verified: registered `discovery-verify` (declared models `qwen3:8b`/`gemma4:e4b`, distinct
      from any `reasoning-agent*` setup already running), confirmed `GET /v1/whoami` returned the
      correct `discovery-verify__reasoning`/`discovery-verify__generation` group names, minted a
      virtual key scoped ONLY to those two groups (deliberately excluding the hardcoded
      `reasoning-agent__*` defaults, so a fallback-to-defaults bug would have surfaced as a loud
      403 rather than silently passing), ran `reasoning_agent.py` with no group flags at all, and
      confirmed via the turn/span view that all three calls succeeded against the declared models
      with no span errors - which could only happen if discovery supplied the right group names,
      since the key had no access to the defaults. Backend restarted first to pick up this
      change's new route (confirmed stale otherwise: `/v1/whoami` 404'd before restart). All test
      artifacts (agent, both gateway groups, virtual key) deleted afterward and confirmed gone.

## 4. Docs

- [x] 4.1 Update `agents/README.md` to document the new default discovery behavior, reframing
      `--reasoning-model-group`/`--generation-model-group` as an override rather than the primary
      mechanism, and noting the visible-warning fallback when discovery fails.
- [x] 4.2 Note in `gateway/README.md` or `agents/README.md` (whichever already documents the
      "Approach A" stopgap) that this change supersedes it as the default path while keeping the
      override available. (Confirmed by repo-wide search: the only two places that framing
      actually lived were `agents/README.md` - "Task-routed calls", updated in 4.1 - and
      `reasoning_agent.py`'s own module docstring, updated in task 3.4. `gateway/README.md` never
      mentioned it; nothing further to change there.)
