# Tasks

## 1. Observability stack (`observability/`)

- [x] 1.1 Create `observability/docker-compose.yml` running an OpenTelemetry Collector, Tempo, and
      Grafana (Tempo provisioned as its data source), mirroring `gateway/`'s self-contained
      pattern; verify `docker compose up` in that directory starts all three with no dependency on
      the main backend being up
- [x] 1.2 Configure the Collector to receive OTLP (HTTP and/or gRPC) and export to Tempo; verify a
      manually-sent test span (e.g. via the OTel CLI or a short throwaway script) appears in Tempo
      and is visible in Grafana's Explore view by its trace id
- [x] 1.3 Write `observability/README.md` documenting what each service does, how to start/stop the
      stack, and how the backend/agents are expected to point at the Collector (env vars, default
      local ports); verify the doc's own startup instructions work from a clean checkout

## 2. Backend: cost calculation

- [x] 2.1 Add a maintained price-list file (model/provider -> price per input/output token) and a
      pure `compute_cost(model, prompt_tokens, completion_tokens) -> float | None` function
      returning `None` (never a fabricated figure) for an unpriced model; verify unit tests for a
      priced model, an unpriced model, and missing token counts
- [x] 2.2 Wire `compute_cost` into the Runner's result-building path so every `Result`'s metrics
      include a `cost` figure when the model is priced; verify a test asserting cost appears for a
      priced model and is absent (not zero) for an unpriced one
- [x] 2.3 Add `cost` to the `performance-metrics`-facing API output (results, summary, compare) the
      same way `cached_tokens` was added previously; verify existing results/summary/compare tests
      still pass and a new test confirms `cost` is present when computable

## 3. Backend: trace columns and the Runner's own spans

- [x] 3.1 Add `trace_id: str | None` to `Result`, write and verify the Alembic migration against
      `test_migration_matches_models`/`test_alembic_upgrade_head_creates_all_tables`
- [x] 3.2 Add the backend's own OpenTelemetry tracer setup (OTLP exporter pointed at the Collector,
      configurable via env var, a no-op/graceful path when unset or unreachable so the Runner never
      fails a run because tracing failed); verify a test that tracing errors never propagate into a
      run's own result/status
- [x] 3.3 Instrument the Runner to emit one trace per request with a span per phase it performs
      (warm-up when sent, generate, judge), recording the resulting `trace_id` on the `Result`;
      verify a test (using a fake/no-op exporter) asserting the expected span names and parent/child
      relationship for a request that includes all three phases, and for one that includes only
      generation
- [x] 3.4 Verify a warm-up request's span is distinct from its model's first measured request's
      span (per spec `evaluation-runs`, "A warm-up request's span is distinguishable")

## 4. Backend: querying Tempo for the frontend

- [x] 4.1 Add a small Tempo query client (mirrors `app/ollama/client.py`'s `httpx.AsyncClient`
      shape) with one operation: fetch a trace by id; verify unit tests against a fake Tempo HTTP
      response for found, not-found, and unreachable-server cases
- [x] 4.2 Add `GET /api/traces/{trace_id}` that proxies that client, translating "not found" and
      "unreachable" into a clear, distinguishable response the frontend can render as "no trace
      available" without treating it as a hard error; verify API tests for all three outcomes
- [x] 4.3 Verify this endpoint's failure never touches any other part of the API - no evaluation,
      scoring, or run-status endpoint changes behavior when Tempo is unreachable

## 5. Backend: trace-ingestion contract changes

- [x] 5.1 Remove the `span` event type from `app/traces/schemas.py`'s discriminated union; extend
      `TurnEndEvent` with `models: list[str]`, `prompt_tokens`/`completion_tokens` totals, `cost:
      float | None`, `trace_id: str | None`, and `thinking: str | None` (the turn's reasoning
      trace, previously assembled from retired `span` events - scope added during apply after a
      test exposed the gap, confirmed with the user); verify a test that a batch containing a (now
      unrecognized) `span` event has only that event rejected, with `turn.start`/`turn.end` events
      in the same batch still accepted (per spec `trace-ingestion`, "Malformed events are rejected
      individually" - unmodified, exercised against the new shape)
- [x] 5.2 Add `trace_id`, `cost` and `thinking` columns to `AgentTurn` (it already has `models`,
      `prompt_tokens`, `completion_tokens`); stop deriving `models`/token totals/reasoning trace
      from aggregated `AgentSpan` rows and read them directly from `turn.end` instead; write and
      verify the Alembic migration
- [x] 5.3 Verify evaluator eligibility (`live-evaluation`'s "a model cannot judge a turn it appears
      in") still works correctly when `models` comes from `turn.end` directly instead of derived
      span aggregation
- [x] 5.4 Verify a turn whose `turn.end` omits `trace_id` is still fully sampled, evaluated and
      shown in the attention dashboard - only its own span-tree view is affected (per spec
      `trace-ingestion`, "A turn with no trace is still fully evaluable")

## 6. Agent SDK: real OpenTelemetry instrumentation

- [x] 6.1 Add `opentelemetry-sdk` and an OTLP exporter to `agents/requirements.txt` (pinned,
      commented, following the existing litellm/langchain precedent) and `eval_agent_sdk`'s own
      tracer-provider setup helper (OTLP endpoint from an env var/constructor argument, matching
      the Collector's receiver); verify a test that configuring it against a fake OTLP receiver
      produces spans with the expected shape
- [x] 6.2 Replace `Turn.llm_call()`'s span emission with a real OpenTelemetry span carrying the
      GenAI semantic-convention attributes for model, prompt/completion token usage, and (via
      task 2.1's cost function) computed cost; keep `Turn.llm_call()`'s existing call signature so
      agents don't need to change their own call sites yet; verify a test asserting the emitted
      span's attributes match a recorded call's model/usage
- [x] 6.3 Replace `Turn.tool_call()`'s span emission the same way, using plain span attributes
      (name, args, result) since GenAI semconv doesn't cover non-model tool calls; verify
      equivalently
- [x] 6.4 Update `Turn`'s `turn.end` emission to include the turn's `models` (collected from its
      own `llm_call()`s), summed token totals, summed cost, its assembled reasoning trace
      (`thinking`, concatenated from its own `llm_call()`s' thinking output), and the trace's id,
      sent via the existing JSON ingest call exactly as `turn.start` already is; verify a test
      asserting `turn.end`'s payload shape matches `trace-ingestion`'s extended contract
- [x] 6.5 Verify a turn with multiple `llm_call()`s produces one real OpenTelemetry trace
      containing one span per call, in order, correlated by the same trace id reported in
      `turn.end`

## 7. Migrate the reference agents, one at a time

- [x] 7.1 Update `chatbot.py` to use the SDK's new instrumentation (no change expected to its own
      call sites, per task 6.2's compatibility goal); verify `test_reference_agents.py`'s chatbot
      coverage passes and a live run's turn shows a real OTel trace in Tempo (live portion: group 9)
- [x] 7.2 Update `reasoning_agent.py`'s four calls (classify/plan/solve/verify); verify
      `test_reference_agents.py` passes and a live run shows all four spans under one trace in
      Tempo, each with its own model/usage/cost attributes (live portion: group 9)
- [x] 7.3 Update `classifier_router_agent.py`'s tool call (external classifier) and routing LLM
      call/hand-off; verify `test_classifier_router_agent.py` passes and a live run shows the
      classification `tool` span and routing `llm` span under one trace, with the handed-off
      agent's own turn carrying its own separate trace (per spec `reference-agents`, "that agent's
      own interactions appear under its own identity... not attributed to the orchestrator's
      spans")

## 8. Frontend: the structured span-tree view

- [x] 8.1 Add a shared span-tree component that, given a `trace_id`, calls `GET
      /api/traces/{trace_id}` and renders the tree (name, kind, duration, and for a model-call
      span its tokens/cost) or a clear "trace unavailable" state; verify component tests for a
      successful tree, a not-found trace, and an unreachable-Tempo response
- [x] 8.2 Wire it into the benchmark results case drill-down (`results-dashboard`), shown when a
      result has a `trace_id`; verify a component test and that the rest of the drill-down
      (output, scores, existing metrics) is unaffected when the trace fetch fails
- [x] 8.3 Wire it into the agent turn drill-down (`agent-monitoring`), shown when a turn has a
      `trace_id`; verify equivalently

## 9. End-to-end verification against the spec

- [x] 9.1 Live: start the observability stack, run a small benchmark suite, and verify a result's
      `trace_id` resolves to a real trace in both the platform's own frontend and Grafana, showing
      its warm-up/generate/judge phases
- [x] 9.2 Live: stop the observability stack mid-session and verify an in-progress or new run still
      completes and scores normally, and an already-shown result's drill-down still shows its
      output/scores with only the span-tree section reporting unavailable
- [x] 9.3 Live: run the migrated reference reasoning agent against a real or locally-registered
      agent, with the observability stack up, and verify its turn's trace in Tempo/Grafana shows
      all four calls with cost computed for any priced model among them
- [x] 9.4 Live: repeat 9.3 with the observability stack down, and verify the turn is still
      evaluated normally (sampled, scored, visible in the attention dashboard) with only its trace
      view affected
