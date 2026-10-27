# Proposal

## Why

Neither evaluation surface has a trace today. The benchmark Runner records flat `Result` rows with
a metrics JSON blob - no notion of a request's internal phases (warm-up, generate, judge) as a
structured timeline. Live agents stream a custom JSON event schema (`turn.start`/`span`/`turn.end`)
into this platform's own ingest - not OpenTelemetry, not visible in any standard tracing tool, and
the span detail it carries (model calls, tool calls) only ever lived in this platform's own
database. Neither surface has a cost figure anywhere - a grep of the whole backend turns up zero
cost-tracking code, only the English word in two comments. As both the skill-prefix-caching and
cached-token work already showed, understanding *why* a request was slow or expensive increasingly
needs to see the actual call tree, not just a handful of aggregate numbers - and right now there is
no call tree to look at, for either surface.

## What Changes

- A new, self-contained observability stack - an OpenTelemetry Collector, Grafana Tempo, and
  Grafana itself - is stood up the same way `gateway/` stands up LiteLLM: its own directory, its
  own `docker-compose`, its own README, nothing hand-wired into the main backend's own deploy.
- The benchmark Runner instruments every request's phases (warm-up, generate, judge) as real OTel
  spans under one trace per request, exported to the Collector, which forwards them to Tempo. Each
  `Result` row gains a `trace_id` so the platform's own frontend can fetch that specific trace from
  Tempo on demand - it does not duplicate span data into its own database.
- The three reference agents (`chatbot.py`, `reasoning_agent.py`, `classifier_router_agent.py`)
  move their span-level instrumentation from the custom `AgentClient.llm_call()`/`tool_call()` SDK
  calls to real OpenTelemetry SDK spans, using the OpenTelemetry GenAI semantic conventions
  (`gen_ai.*` attributes) for model calls, exported the same way the Runner's spans are. This is
  the harder half of this change and touches every shipped agent's instrumentation code, not just
  configuration.
- The existing custom ingest contract (`trace-ingestion`) keeps exactly one job: a lightweight,
  always-on turn-level summary (`turn.start`/`turn.end`) that evaluation (sampling, eligibility,
  rubric judging, reference correctness, the attention dashboard) keeps running against, completely
  independent of whether Tempo is reachable. The per-call `span` event type is retired - that
  detail now lives only in OTel/Tempo - and `turn.end` gains the fields the platform used to derive
  by aggregating span events itself: the distinct models used, prompt/completion token totals, a
  computed cost figure, and the `trace_id` to correlate to Tempo.
- A per-model, per-provider cost figure is computed from token usage and a new, hand-maintained
  price-list file (mirroring how `starter_suite.yaml`/`gateway/config.yaml` are hand-authored and
  version-controlled) for both surfaces - the benchmark Runner's `Result` rows and live agents'
  turn summaries.
- The platform's own frontend (not just Grafana) gains a structured span-tree view, for a benchmark
  result's drill-down and for an agent turn's drill-down alike: given a `trace_id`, it queries
  Tempo live (TraceQL) and renders the tree (agent start / reasoning / tool calls / model calls /
  generation, with duration, tokens, cost per span). If Tempo is unreachable at that moment, the
  tree is shown as unavailable - this is the only part of either evaluation surface allowed to
  degrade on Tempo's availability; nothing else does.
- Grafana itself remains available as a second, standard way to look at the same traces, with no
  platform-specific UI work needed there beyond standing up Tempo as its data source.

## Capabilities

### New Capabilities

- `trace-observability`: the OTel Collector/Tempo/Grafana stack, trace-id correlation on both
  `Result` and `AgentTurn`, the live Tempo-backed structured span-tree view in the platform's own
  frontend (for both evaluation surfaces), its graceful degradation when Tempo is unreachable, and
  per-request/per-turn cost calculation from a maintained price list.

### Modified Capabilities

- `evaluation-runs`: the Runner emits real OTel spans for each request's phases and records a
  `trace_id` (and a computed cost figure) on every `Result`.
- `performance-metrics`: a computed cost figure is recorded per request, alongside the existing
  token/cached-token figures.
- `trace-ingestion`: the `span` event type is retired from the custom ingest contract; `turn.end`
  gains `models`, token totals, a computed cost figure, and `trace_id`, so evaluation keeps running
  off local data with no dependency on Tempo.
- `reference-agents`: all three shipped agents instrument their model/tool calls with the real
  OpenTelemetry SDK instead of the custom `AgentClient` span methods, while still sending
  `turn.start`/`turn.end` via the existing ingest.
- `agent-monitoring`: the turn drill-down's per-span display becomes the live, Tempo-backed
  structured tree (by `trace_id`) instead of reading stored `AgentSpan` rows, since spans are no
  longer stored locally; this degrades to "traces unavailable" independently of the rest of the
  drill-down (input, output, evaluator scores) when Tempo can't be reached.
- `results-dashboard`: a benchmark result's case drill-down gains the same structured span-tree
  view, by `trace_id`, with the same graceful degradation.

## Impact

- New: `observability/` (Collector config, Tempo config, Grafana provisioning, `docker-compose`,
  README) - a new operational dependency, optional at runtime for everything except the span-tree
  view.
- Backend: `app/core/runner.py` (OTel span emission per phase), `app/models.py` (`trace_id` and
  `cost` columns on `Result`; `AgentTurn` gains `models` is already present - gains `cost` and
  `trace_id`), `app/traces/schemas.py` (`SpanEvent` retired, `TurnEndEvent` extended), `app/api/ingest.py`,
  a new cost-calculation module reading the maintained price list, and a new backend endpoint/proxy
  that queries Tempo's API on the frontend's behalf (so the browser never needs direct network
  access to Tempo, and Tempo's own auth/location stays a backend concern).
- Agents: `agents/eval_agent_sdk/__init__.py` (drop `llm_call()`/`tool_call()`'s span-emission
  path; add a real `opentelemetry-sdk` + OTLP exporter setup), `agents/chatbot.py`,
  `agents/reasoning_agent.py`, `agents/classifier_router_agent.py` (every model/tool call
  re-instrumented), `agents/requirements.txt` (new OTel dependencies).
- Frontend: a new structured span-tree component shared between the benchmark results drill-down
  and the agent turn drill-down; both already have a drill-down to extend rather than a new page.
- Migration: additive for existing data - a `Result`/`AgentTurn` row from before this change simply
  has no `trace_id`/`cost` and the frontend shows "no trace available" for it, exactly like the
  degraded-Tempo case.
- Explicitly out of scope for this change: Loki (log storage) - not requested; routing the
  lightweight turn-summary channel itself through OTel/the Collector instead of the existing custom
  JSON ingest (explicitly declined in favor of keeping the existing contract); any change to what
  the eval DB treats as the evaluation source of truth (unchanged - OTel/Tempo is observability
  only, never a dependency of scoring/judging/sampling).
