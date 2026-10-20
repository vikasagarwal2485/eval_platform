# Tasks

**Prerequisite**: `add-custom-model-provider-kind` must be implemented and applied first - task 3.6 and 6.1
below depend on its `custom`-kind provider registration and `whoami`'s `custom_model_endpoints` field.

## 1. Dependencies and scaffolding

- [ ] 1.1 Add `langchain`, `langchain-openai`, `langgraph`, and an MCP library (`mcp`) to
      `agents/requirements.txt` with a short comment on what each is for (mirroring the existing
      comments there), and verify `make agents-setup` installs cleanly into `agents/.venv`
- [ ] 1.2 Create `agents/routing_mcp/` with a `routes.yaml` (the ordered rule list from design.md:
      `task`/`label`/`action`, `"*"` wildcard label, trailing `default: {action: error}`) seeded
      with two rules - `spam`/`spam` -> `short_circuit`, `ag_news`/`"*"` -> `handoff` to
      `reasoning-agent` - and verify the file parses with `yaml.safe_load`

## 2. Routing-mapping MCP server

- [ ] 2.1 Implement `agents/routing_mcp/server.py`: an MCP server (stdio transport) exposing one
      `resolve_route` tool that takes a classifier result (per-task label/confidence dict) and
      returns the first matching rule's action (and target agent, for `handoff`) from
      `routes.yaml`, or the `default` action when nothing matches; verify a unit test covering a
      match on each configured rule and the no-match/default case
- [ ] 2.2 Verify the mapping is reloadable without code changes: edit `routes.yaml` to add a new
      rule, restart the server, and confirm a classifier result matching only the new rule now
      resolves correctly with zero changes to `server.py` or the router agent

## 3. Router agent core

- [ ] 3.1 Create `agents/classifier_router_agent.py` with `reasoning_agent.py`-style CLI flags
      (`--platform-url`, `--token`, `--gateway-url`, `--gateway-key`, `--classifier-url` (an
      override - unset by default, see task 3.6), `--routing-model-group`,
      `--routing-fallback-group`, `--reasoning-agent-token`, `--reasoning-agent-gateway-key`,
      `--problem`) and verify `--help` lists them with the same documentation style as
      `reasoning_agent.py`
- [ ] 3.2 Implement the single-task discovery helper (explicit `--routing-model-group` override,
      else `whoami()`'s `gateway_model_groups["routing"]`, else a hardcoded
      `classifier-router-agent__routing` default, with the same visible stderr warning on
      discovery failure as `reasoning_agent.py`'s `_resolve_model_groups()`) and verify unit tests
      for: explicit override skips discovery, discovery used when no override, failed discovery
      falls back to the hardcoded default with a warning - mirroring
      `test_reference_agents.py`'s existing coverage for the same three behaviors
- [ ] 3.3 Implement the gateway-routed LLM call via `ChatOpenAI` (`base_url=gateway_url,
      api_key=gateway_key, model=<routing group>`) and empirically verify against the running
      gateway whether any provider-hint prefix (like litellm's `openai/`) is actually needed;
      document the finding in a code comment either way (design.md Decision 3)
- [ ] 3.4 Implement the fallback-group passthrough via `ChatOpenAI`'s `extra_body`/`model_kwargs`
      and verify live against the gateway: break the primary routing group, configure a fallback,
      confirm the call still succeeds and the span records the fallback's concrete model
      (mirroring `add-declared-model-fallback`'s existing verification approach)
- [ ] 3.5 Implement the classify step: an HTTP `POST` to the discovered (or overridden) classifier
      base URL's `/classify` with the problem text, recorded via `Turn.tool_call()` (`kind: "tool"`,
      not `kind: "llm"`), and verify a test asserts this span has no `model` field and precedes
      every other span in the turn
- [ ] 3.6 Implement the classifier-address discovery helper (explicit `--classifier-url` override,
      else `whoami()`'s `custom_model_endpoints["classification"]["base_url"]`
      (`add-custom-model-provider-kind`), else the hardcoded `http://127.0.0.1:8765` default, with
      the same visible stderr warning on discovery failure as task 3.2's routing-group helper); verify
      unit tests for the same three behaviors: explicit override skips discovery, discovery used
      when no override, failed discovery falls back to the hardcoded default with a warning

## 4. Routing decision (tool-calling)

- [ ] 4.1 Build the LangGraph node that calls the routing LLM with the classify step's result and
      the `resolve_route` tool bound (via an MCP client connecting to the server from section 2
      over stdio, spawned as a subprocess of the router), instructed by its system prompt to call
      the tool before answering
- [ ] 4.2 Implement the bounded one-round-trip loop: execute at most the first tool call the model
      requests, feed its result back, take the model's next response as the final routing
      decision; verify a test with a fake/mock chat model confirms exactly one tool invocation
      occurs even if the model's response names more than one
- [ ] 4.3 Record the routing LLM call as its own span (`Turn.llm_call()`, concrete model from the
      gateway response) and the tool invocation as its own span (`Turn.tool_call()`), and verify a
      test asserts both spans are present, in order, classify -> routing-llm -> resolve-route-tool
- [ ] 4.4 Verify "the routing decision resolves through a tool call, not a hardcoded branch": a
      test asserts the orchestrator's own code never branches on the classifier's raw labels
      directly - only on the MCP tool's returned action

## 5. Downstream branches

- [ ] 5.1 Implement the `handoff` branch: spawn `reasoning_agent.py` (using
      `--reasoning-agent-token`/`--reasoning-agent-gateway-key`) as a subprocess with `--problem`
      set to the original problem text, wait for it synchronously, and parse its final stdout line
      as the answer; record the hand-off and its result as a `Turn.tool_call()` span; verify an
      integration test (fake reasoning-agent script standing in for the real one) confirms the
      router's own turn has no `llm` spans for this branch and the sub-agent's turn appears
      separately under its own agent identity, live against the running platform
- [ ] 5.2 Implement the `short_circuit` branch: finish the turn immediately with the configured
      canned response, with no further LLM or sub-agent call; verify a test confirms zero further
      spans are recorded after the routing decision for this branch
- [ ] 5.3 Implement the `error` (no-match) outcome: the turn ends in a visible error naming "no
      route matched" rather than guessing a branch; verify a test covers a classifier result that
      matches no configured rule

## 6. Registration and end-to-end verification

- [ ] 6.1 Register the classifier service as a `custom`-kind provider/model
      (`add-custom-model-provider-kind`), then register this agent on a running platform instance
      (kind `reasoning`, declared_models `{"routing": "<model-ref>", "classification":
      "@<custom-provider>/<model-id>"}`, `routing` optionally with a `fallback`, via a direct API
      call - no Agents page UI change in this phase, per design.md's Non-Goals) and verify `GET
      /api/ingest/v1/whoami` returns a `routing` entry in `gateway_model_groups` (continuing the
      same proof `add-classification-task-routing` established for a third task name, now for a
      fourth, agent-invented one) and a `classification` entry in `custom_model_endpoints` (not in
      `gateway_model_groups` - there is no gateway group for it)
- [ ] 6.2 Configure an evaluator for this agent that is not one of its own declared/sub-agent
      models (the existing "reference agents demonstrate evaluation by a different model"
      requirement is already generic enough to cover this agent), run both branches at least once
      live, and verify both turns appear evaluated in the platform with no self-judged score
- [ ] 6.3 Verify the hard constraint end to end: with the gateway stopped, confirm the routing call
      fails visibly (no silent direct-provider fallback) exactly like `reasoning_agent.py`'s
      existing gateway-failure behavior; with the gateway running and the classifier stopped,
      confirm the classify step fails visibly too, distinct from a gateway failure
- [ ] 6.4 Add a section to `agents/README.md` documenting how to run this agent (mirroring the
      existing reasoning-agent runbook: prerequisites, example commands, the two branches, and how
      to point `--classifier-url` at a different classifier instance)
