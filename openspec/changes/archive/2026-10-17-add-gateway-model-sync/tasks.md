# Tasks

## 1. Gateway: enable dynamic model management

- [x] 1.1 Run the gateway with `STORE_MODEL_IN_DB=True` and verify `/model/new` creates a group
      that routes a request immediately, without restarting the process
- [x] 1.2 Verify `/model/update` changes an existing group's deployment and/or generation
      parameters and takes effect immediately
- [x] 1.3 Verify `/model/delete` removes a group and a subsequent request to it is rejected as
      unconfigured, without restarting the process
- [x] 1.4 Verify a credential given as `os.environ/<VAR>` at creation time never appears in the
      clear in any `/model/new`, `/model/update` or `/model/info`-style response
- [x] 1.5 Resolve the open question on a model-management-scoped credential vs. the master key
      (design.md); document the chosen credential's scope and storage in `gateway/README.md`

## 2. Registry: declared model value shape

- [x] 2.1 Extend `AgentCreate`/`AgentSettingsUpdate`'s `declared_models` value type to accept
      either a plain string or `{"model": str, "params"?: dict}`, and verify a unit test for each
      shape, plus a test confirming an existing plain-string request still validates unchanged
- [x] 2.2 Verify a unit test rejects a `params` value that isn't a JSON object (e.g. a string or
      number), naming the offending task-type key

## 3. Sync mechanism

- [x] 3.1 Add `backend/app/core/gateway_sync.py` with `to_litellm_params(ref, params) -> dict`
      (bare name → `ollama_chat/...` + configured `ollama_base_url`; `@provider/model` → looked-up
      `Provider` row translated per design.md's mapping) and verify unit tests for both ref forms,
      including the azure-openai prefix resolved in task 1.5
- [x] 3.2 Add `sync_agent_model_groups(agent) -> dict[str, SyncResult]` calling the gateway's
      `/model/new`/`/model/update`/`/model/delete` as appropriate per task type, and verify a unit
      test (mocked gateway) covers create, update and delete paths
- [x] 3.3 Verify a unit test: when the gateway is unreachable, `sync_agent_model_groups` returns
      an error result per affected task type without raising
- [x] 3.4 Verify a unit test: a provider-referencing declared model's sync call never contains the
      provider's literal key, only `os.environ/<key_env>`

## 4. Wire into create/update

- [x] 4.1 Call `sync_agent_model_groups` from `app/api/agents.py` after `repo.create_agent`/
      `repo.update_agent_settings` commit, and fold the result into the response as
      `gateway_sync: {<task_type>: {"status": ..., "detail"?: ...}}`
- [x] 4.2 Verify an integration test: registering an agent with the gateway unreachable still
      returns 201 with the agent created, and `gateway_sync` shows the failure
- [x] 4.3 Verify an integration test: registering `chatbot.py`-style agent (gateway sync attempted
      regardless) behaves identically whether the gateway is up or down, beyond the `gateway_sync`
      field itself
- [x] 4.4 Verify an integration test: updating `declared_models` to drop a task type removes that
      task type's gateway group (against a locally running gateway)

## 5. Frontend

- [x] 5.1 Show `gateway_sync` results (per task type) after registering or saving agent settings,
      distinct from the existing validation-error display
- [x] 5.2 Add optional generation-parameter fields (starting with temperature) to the declared-
      models editor rows added in `add-agent-multi-model-registry`

## 6. Documentation and end-to-end verification

- [x] 6.1 Update `agents/README.md`'s registration examples to show a declared model with
      generation-parameter overrides, and note that `gateway/config.yaml` is no longer the only
      way a per-agent group gets configured
- [x] 6.2 Verify end to end against a real running gateway and platform: register an agent with
      `declared_models` for two task types including a temperature override on one, confirm both
      gateway groups exist with the right deployment and parameter, update one task type's model,
      confirm the gateway group changes without restarting it, remove a task type, confirm its
      gateway group is gone
