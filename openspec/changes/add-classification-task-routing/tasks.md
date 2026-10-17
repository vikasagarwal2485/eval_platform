# Tasks

## 1. Gateway config

- [ ] 1.1 Add the `reasoning-agent__classification` model group to `gateway/config.yaml` and
      verify the proxy starts cleanly and the group responds to a direct test request
- [ ] 1.2 Add the third entry to the reasoning agent's `declared_models` via the registry
      (`add-agent-multi-model-registry`) and verify the agent's settings view shows all three
      declared models

## 2. Agent change

- [ ] 2.1 Add a `classify()` call to `reasoning_agent.py`'s `solve_one()`, preceding `plan`,
      addressed to `reasoning-agent__classification`, and verify a unit test asserts the call
      order (classify, then plan, then solve, then verify)
- [ ] 2.2 Record the classification call as its own span, and verify a test asserts the resulting
      turn has four spans in order with the classification span first
- [ ] 2.3 Verify the classification result is not used to alter plan/solve/verify's prompts in
      this phase (regression check matching the Non-Goals in design.md) - a test asserting
      plan/solve/verify prompts are unchanged regardless of the classification output is
      sufficient

## 3. Verify against the spec

- [ ] 3.1 Verify "A classification call precedes planning, using a third task-scoped model group"
      with an integration test against a locally running gateway
- [ ] 3.2 Verify "A third task type does not disturb the first two" - run the existing
      plan/solve/verify-focused tests from `add-reasoning-agent-task-routing` unchanged and
      confirm they still pass with the classification step present
- [ ] 3.3 Run the full reference-agent end-to-end flow once more (register with three declared
      models, run, evaluate) and confirm turns still appear evaluated with no self-judged score
