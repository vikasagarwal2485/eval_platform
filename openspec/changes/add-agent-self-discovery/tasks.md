# Tasks

## 1. Backend endpoint

- [ ] 1.1 Add `GET /v1/whoami` to `backend/app/api/ingest.py`, reusing `_bearer_token`/
      `repo.verify_agent_token`; return 401 on a missing/invalid token exactly like
      `POST /v1/events`, but do NOT reject a paused agent (see design.md - "Decisions"); verify
      with a unit test for the 401 case and a test confirming a paused agent still gets 200.
- [ ] 1.2 Build the response body: `{"name": agent.name, "kind": agent.kind, "declared_models":
      agent.declared_models, "gateway_model_groups": {task_type: model_group_name(agent_slug(
      agent.name), task_type) for task_type in agent.declared_models}}`, importing
      `agent_slug`/`model_group_name` from `backend/app/core/gateway_sync.py` (reused, not
      reimplemented); verify with a unit test asserting the computed group names exactly match what
      a real sync call for the same agent would use.
- [ ] 1.3 Verify by inspection and a dedicated test that the response never includes `token`,
      `token_hash`, `token_prefix`, or any gateway/provider credential field - only the four fields
      above.

## 2. Agent SDK helper

- [ ] 2.1 Add `whoami(platform_url: str, token: str, *, timeout: float = 10.0) -> dict` to
      `agents/eval_agent_sdk/__init__.py` as a standalone synchronous function (not a method on
      `AgentClient` - see design.md), making a plain `httpx.get` to `{platform_url}/api/ingest/v1/
      whoami` with the bearer token, raising on a non-2xx response or timeout rather than
      swallowing the error (the caller decides the fallback policy); verify with a unit test using
      a fake HTTP server or `httpx` mock covering both the success and the error-raises case.
- [ ] 2.2 Export `whoami` from `agents/eval_agent_sdk/__init__.py`'s `__all__`.

## 3. Reference reasoning agent

- [ ] 3.1 In `agents/reasoning_agent.py`'s `main()`, when neither `--reasoning-model-group` nor
      `--generation-model-group` was explicitly passed and `--model` is not set, call
      `eval_agent_sdk.whoami(args.platform_url, args.token)` once and use its
      `gateway_model_groups` entries for `reasoning`/`generation` in place of
      `REASONING_MODEL_GROUP`/`GENERATION_MODEL_GROUP`; verify with a unit test (mocking `whoami`)
      that the discovered names are what gets passed to `run_once`/`run_suite`.
- [ ] 3.2 On a `whoami` call that raises (network error, non-2xx, timeout), catch it, log a visible
      warning naming the fallback, and continue with the existing hardcoded
      `REASONING_MODEL_GROUP`/`GENERATION_MODEL_GROUP` constants; verify with a unit test that a
      simulated discovery failure still lets the agent run using the defaults.
- [ ] 3.3 Confirm an explicit `--reasoning-model-group`/`--generation-model-group` flag always
      skips the discovery call entirely for that task (not just overrides its result) - verify with
      a unit test asserting `whoami` is not called when both flags are explicitly given.
- [ ] 3.4 Update the module docstring: replace the "TEMPORARY stopgap" framing for the explicit
      flags with "override discovery when you need a different agent's groups," and add discovery
      as the default documented behavior with an example invocation that passes no group flags.
- [ ] 3.5 Live-verify end to end against the running backend + gateway: register an agent under a
      new name, run `reasoning_agent.py` with no group-override flags and confirm (via the
      backend's turn/span view) its calls were routed through that agent's own discovered groups,
      not the hardcoded `reasoning-agent__*` defaults. Clean up test artifacts afterward.

## 4. Docs

- [ ] 4.1 Update `agents/README.md` to document the new default discovery behavior, reframing
      `--reasoning-model-group`/`--generation-model-group` as an override rather than the primary
      mechanism, and noting the visible-warning fallback when discovery fails.
- [ ] 4.2 Note in `gateway/README.md` or `agents/README.md` (whichever already documents the
      "Approach A" stopgap) that this change supersedes it as the default path while keeping the
      override available.
