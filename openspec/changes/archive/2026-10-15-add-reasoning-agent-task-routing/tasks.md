# Tasks

## 1. Dependency and CLI

- [x] 1.1 Add `litellm` (pinned, per the companion proposal doc's dependency-risk note) to
      `agents/requirements.txt` and verify `pip install -r agents/requirements.txt` succeeds in a
      clean virtual env
- [x] 1.2 Replace `--ollama-url` with `--gateway-url` in `reasoning_agent.py`'s argument parser
      (default to the gateway's local address) and verify `--help` shows the new flag
- [x] 1.3 Document the new `--model` / `--gateway-url` semantics and the two model group names in
      `agents/README.md`, and verify by following the doc from a clean checkout to run one case

## 2. Replace the call path

- [x] 2.1 Replace `call_ollama()` with a `call_llm()` using `litellm.completion()`, keeping the
      `(content, usage)` return shape, and verify a unit test asserts the same return shape as the
      previous implementation for a mocked response
- [x] 2.2 Route the plan and verify calls in `solve_one()` to `reasoning-agent__reasoning` and the
      solve call to `reasoning-agent__generation`, and verify a test asserts the three calls use
      the expected model strings (mocked `litellm.completion`, asserting on `model=`)
- [x] 2.3 Prefix each model group name with `openai/` before passing it to `completion()`
      (required for the SDK to treat the gateway's `api_base` as an OpenAI-compatible endpoint -
      see design.md), and read each span's recorded model from
      `resp._hidden_params["additional_headers"]["llm_provider-x-litellm-model-name"]`, not
      `resp.model` (which is the group alias). Verify a test confirms the span's `model` field
      differs from the model group name when the mock returns a different concrete model, and a
      second test confirms `completion()` is called with the `openai/`-prefixed group name

## 3. Error handling

- [x] 3.1 Replace `httpx.HTTPError` catches in `run_once()`/`run_suite()` with LiteLLM's exception
      types and verify the existing "print and keep going" tests
      (`test_reasoning_agent_suite_mode_continues_past_a_connection_failure`) still pass against
      the new exception type
- [x] 3.2 Verify a gateway-unreachable error does not fall back to a direct provider call: add a
      test that fails the gateway call and asserts no direct-provider call is attempted

## 4. Verify against the spec

- [x] 4.1 Verify "Reasoning turn has multiple spans" and "Reasoning agent can replay a suite with
      expected answers" still pass unchanged (regression check - this change must not alter turn/
      span structure)
- [x] 4.2 Verify "Plan and verify calls use the reasoning-scoped model group" and "The solve call
      uses the generation-scoped model group" with an integration test against a locally running
      gateway (from `add-litellm-gateway-infra`) using distinguishable mock deployments per group
- [x] 4.3 Verify "A gateway failure does not silently fall back to a direct provider call" with
      the gateway stopped and the agent run once, confirming a visible error and no provider
      traffic
- [x] 4.4 Run the full reference-agent end-to-end flow (register, run, evaluate) once with the
      gateway up, confirming turns still appear evaluated in the platform with no self-judged
      score, matching "The reference agents demonstrate evaluation by a different model"
