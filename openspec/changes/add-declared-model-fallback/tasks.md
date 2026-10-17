# Tasks

## 1. Backend schema and validation

- [x] 1.1 Add `fallback: str | None` to `DeclaredModelSpec` (`backend/app/schemas.py`); verify
      `_validate_declared_models` parses and re-serializes it (object form stores
      `{"model": ..., "params": ..., "fallback": ...}` with `None` excluded) and a new unit test
      confirms a plain-string entry is unaffected.
- [x] 1.2 Reject an invalid `fallback` reference the same way an invalid `model` reference is
      rejected; add a unit test registering/updating an agent with a malformed fallback reference
      and confirm it 422s naming the fallback field.
- [x] 1.3 In `backend/app/repo.py`, extend the refs list passed to `_check_provider_acks` in both
      `create_agent` and `update_agent_settings` to include each declared model's `fallback`
      reference (when present) alongside its primary `model` reference; add tests covering a
      hosted fallback requiring acknowledgment on both create and update.

## 2. Gateway sync

- [x] 2.1 In `backend/app/core/gateway_sync.py`, add a `model_group_name`-based helper (or inline
      suffixing) for the fallback group name (`<agent-slug>__<task_type>__fallback`); verify via a
      unit test that it is distinct from the primary group name and stable across calls.
- [x] 2.2 Extend `sync_agent_model_groups` to upsert the fallback group when `declared_models[task
      type]` carries a `fallback`, reusing `to_litellm_params`/`_upsert_group` against the fallback
      reference instead of the primary one; verify with a test asserting both groups are
      created/updated when a fallback is present.
- [x] 2.3 Extend `sync_agent_model_groups` to delete the fallback group when the fallback is
      removed but the task type remains, or when the task type itself is removed; verify with a
      test for each case using the existing `_delete_group` path. (Corrected from the original
      wording, which also asked to delete the fallback group when its reference fails to resolve -
      that would be inconsistent with the primary group's own established behavior, which reports
      an error and leaves any existing group untouched rather than deleting it; the fallback path
      now matches that exactly, so a once-valid-now-broken fallback reference reports an error the
      same way a broken primary reference already does.)
- [x] 2.4 Confirm (unit test against the sync result shape) that `SyncResult` keys distinguish the
      primary and fallback outcomes per task type (e.g. `"reasoning"` and `"reasoning__fallback"`)
      so a fallback-only sync failure is visible without masking the primary result.

## 3. Reference reasoning agent

- [x] 3.1 Add `fallback_group: str | None = None` to `call_llm`; when set, add `"fallbacks":
      [fallback_group]` to the completion kwargs; verify with a unit test asserting the kwarg is
      present only when a fallback group is passed.
- [x] 3.2 Thread `reasoning_fallback_group`/`generation_fallback_group` (keyword-only, default
      `None`) through `solve_one`, `run_once` and `run_suite`, mirroring how `reasoning_group`/
      `generation_group` are already threaded; verify with a unit test that the plan/verify call
      gets the reasoning fallback and the solve call gets the generation fallback.
- [x] 3.3 Add `--reasoning-fallback-group`/`--generation-fallback-group` CLI flags (optional,
      default `None`, ignored when `--model` is set, matching the existing
      `--reasoning-model-group`/`--generation-model-group` flags); update the module docstring's
      example invocations and verify `build_arg_parser` exposes both with `--help`.
- [x] 3.4 Live-verify end to end against the running gateway: configure a declared model with a
      fallback, confirm both gateway groups exist via `/model/info`, point the agent's virtual key
      at both groups (`gateway/README.md` - "Virtual keys"), force the primary deployment to fail
      (e.g. an invalid `api_key` env var), run the agent with the fallback flag set, and confirm
      the turn still succeeds with a span recording the fallback deployment's concrete model.
      Clean up test artifacts afterward. This caught a real bug: `litellm.completion(...,
      fallbacks=[...])`'s client-side fallback retry (distinct from the gateway's own REST
      `/chat/completions` handling) re-calls `completion()` with the fallback string exactly as
      given, so it needs the same `openai/` provider-hint prefix the primary `model` gets - without
      it the fallback attempt itself fails with `LLM Provider NOT provided`. Fixed in `call_llm`
      (now sends `fallbacks=[f"openai/{fallback_group}"]`) and in design.md/gateway/README.md's
      wording so a future reader isn't misled by the "verified against the gateway" research, which
      was against the proxy's own REST endpoint, not this client-side SDK path. Verified end to end
      after the fix: registered a test agent with a broken primary (`qwen3:8b-does-not-exist`) and
      a working fallback (`qwen3:8b`), confirmed both gateway groups via `/model/info`, ran the
      agent, and confirmed all three spans (plan/solve/verify) succeeded recording
      `ollama_chat/qwen3:8b` with no span errors. All test artifacts (agent, both gateway group
      pairs, virtual key) deleted afterward and confirmed gone.

      **Second real finding, from the user's own live run against `reasoning-agent-verify`
      afterward**: a successful fallback still spammed stdout - a "Give Feedback / Get Help" banner
      plus a full Python traceback per failed attempt (LiteLLM's `fallback_utils.py` logs every
      failed attempt, including the primary's, via `verbose_logger.exception(...)` - ERROR level,
      always with the traceback - even when a later fallback succeeds), plus an unrelated
      `asyncio`/`RuntimeWarning` pair from LiteLLM's sync wrapper spinning a new event loop per
      call and orphaning its global background logging worker across calls. None of this hides a
      genuine failure - `run_once`/`run_suite` already print a clean one-line error for that case -
      so it's pure noise on the success path. Fixed with four narrow, verified-live suppressions at
      the top of `reasoning_agent.py` (`litellm.suppress_debug_info = True`;
      `logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)`;
      `logging.getLogger("asyncio").setLevel(logging.CRITICAL)`; a targeted `warnings.filterwarnings`
      for the "never awaited" message only). Re-verified against the user's real agent and virtual
      key (after also fixing that key's scope, which was missing the fallback group - a separate,
      pre-existing gap, not part of this change) - the fix is real, so: stdout now shows only the
      agent's own final answer.

## 4. Frontend

- [x] 4.1 Add an optional "Fallback model" field next to each declared-model row in
      `DeclaredModelPicker.tsx` (or a sibling control reusing it), gated by the same
      data-sharing-acknowledgment flow a hosted primary model already uses; verify with a component
      test that setting a hosted fallback without prior acknowledgment surfaces the existing
      "Acknowledge and save/register" flow. (Implemented by rendering a second
      `DeclaredModelPicker` instance per row rather than modifying the component itself - it was
      already a generic single-value picker with ack gating and a blank/"no selection" state, so
      no changes to `DeclaredModelPicker.tsx` were needed.)
- [x] 4.2 Wire the fallback field into `AgentsPage.tsx`'s registration form and
      `AgentSettingsPanel.tsx`'s `DeclaredModelsEditor`, sending `fallback` only when set (omitted
      entirely when blank, matching how `params`/temperature is already handled); verify with
      tests mirroring the existing "sends a temperature override as a declared-model object" test
      but for `fallback`.

## 5. Docs

- [x] 5.1 Update `gateway/README.md`'s "What's still out of scope" section: remove the "No
      `fallbacks` are configured on any group" line and add a short "Fallback groups" section
      documenting the per-request `fallbacks` mechanism, linking to this change, and explicitly
      warning that gateway-wide `/config/update` fallback configuration does not reliably apply.
- [x] 5.2 Update `agents/reasoning_agent.py`'s module docstring with an example invocation that
      passes both new fallback flags. (Done alongside task 3.3.)
