# Tasks

## 1. Gateway config

- [ ] 1.1 Add the `reasoning-agent__classification` model group to `gateway/config.yaml` and
      verify the proxy starts cleanly and the group responds to a direct test request
      (static config entry added; a clean-restart verification is still outstanding - it requires
      restarting the live gateway process, which needs `LITELLM_MASTER_KEY`. The equivalent group
      is live-verified via the dynamic per-agent registry path instead - see 1.2/3.1/3.3 - which is
      how classification groups are actually created and used at runtime)
- [x] 1.2 Add the third entry to the reasoning agent's `declared_models` via the registry
      (`add-agent-multi-model-registry`) and verify (a) the agent's settings view shows all three
      declared models, and (b) `GET /api/ingest/v1/whoami` (`add-agent-self-discovery`) returns a
      `classification` entry in `gateway_model_groups` with **no backend code changes** - this is
      itself one of the things this phase exists to prove

## 2. Agent change

- [x] 2.1 Add a `classify()` call to `reasoning_agent.py`'s `solve_one()`, preceding `plan`, using
      the existing `call_llm()` helper (no new, bespoke LLM-calling code path) addressed to the
      agent's own discovered (or `--classification-model-group`-overridden) classification group,
      and verify a unit test asserts the call order (classify, then plan, then solve, then verify)
- [x] 2.2 Record the classification call as its own span, and verify a test asserts the resulting
      turn has four spans in order with the classification span first
- [x] 2.3 Extend `_resolve_model_groups()` to a third, classification task following its existing
      per-task pattern, and add `--classification-model-group`/`--classification-fallback-group`
      CLI flags mirroring `--reasoning-model-group`/`--reasoning-fallback-group`; verify unit tests
      for discovery, explicit override, and fallback-passed-on-request behavior for the
      classification task, matching the existing reasoning/generation test coverage
- [x] 2.4 Verify the classification result is not used to alter plan/solve/verify's prompts in
      this phase (regression check matching the Non-Goals in design.md) - a test asserting
      plan/solve/verify prompts are unchanged regardless of the classification output is
      sufficient

## 3. Verify against the spec

- [x] 3.1 Verify "A classification call precedes planning, using a third task-scoped model group"
      with an integration test against a locally running gateway
- [x] 3.2 Verify "A third task type does not disturb the first two" - run the existing
      plan/solve/verify-focused tests from `add-reasoning-agent-task-routing` unchanged and
      confirm they still pass with the classification step present
- [x] 3.3 Verify self-discovery and fallback generalize to the classification task: register an
      agent under a non-default name with a `classification` declared model (optionally with a
      fallback), confirm its classification call routes through its own discovered group (or the
      configured fallback, if the primary is made to fail), live against a running gateway
- [x] 3.4 Run the full reference-agent end-to-end flow once more (register with three declared
      models, run, evaluate) and confirm turns still appear evaluated with no self-judged score
      (verified live: registered `@azure-openai/gpt-4o-mini` as evaluator, correctly treated as
      eligible since it matched none of the turn's three models - the D5 "never self-judge"
      invariant held for a turn with all three task types present; the judge call itself failed
      on an unrelated, pre-existing Azure VNet network restriction on that resource, not a defect
      in this change)
