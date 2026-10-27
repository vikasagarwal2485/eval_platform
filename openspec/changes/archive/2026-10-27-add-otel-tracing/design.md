# Design

## Context

Grounded in what exists today (see proposal.md for the full "why"):

- **Static eval**: `app/core/runner.py` executes model-grouped, sequentially; each request becomes
  one flat `Result` row with a `metrics` JSON blob (`app/core/metrics.py`). No trace concept, no
  cost.
- **Live agents**: a custom, versioned JSON batch-event contract (`app/traces/schemas.py`:
  `turn.start`/`span`/`turn.end`) streamed into `POST /api/ingest/v1/events`
  (`app/api/ingest.py`), reconstructed into `AgentSession -> AgentTurn -> AgentSpan` rows
  (`app/models.py`). `AgentSpan.kind` is `llm` or `tool`; `AgentTurn.models` is currently *derived*
  by aggregating its spans' model fields. Everything downstream - sampling, evaluator eligibility
  (`live-evaluation`), rubric judging, the attention dashboard (`agent-monitoring`) - reads these
  rows directly via SQL, computed in Python at read time over a bounded window (same philosophy as
  `cross-model-judging`'s per-judge stats and `performance-metrics`' aggregates: no separate
  pre-aggregation store, single-machine scale, by explicit design elsewhere in this project).
- The agent SDK (`agents/eval_agent_sdk/__init__.py`) is explicitly documented as "dependency-light
  - httpx only" so it can run inside any agent's process without pulling in a large dependency
  tree. Adding the OpenTelemetry SDK is a real change to that stated design goal, not a drop-in.
- Nothing in the repo today touches OpenTelemetry, Grafana, Tempo, or Loki, or computes a cost
  figure (confirmed by a full-repo grep - the only "cost" hits are the English word in comments).
- `gateway/` is the existing precedent for "a self-contained, separately-deployed subsystem with
  its own config and docker-compose, not wired into the main backend's own deploy" - LiteLLM there,
  mirrored here for the Collector/Tempo/Grafana stack.

## Goals / Non-Goals

**Goals:**
- Both evaluation surfaces get a real OpenTelemetry trace of the full call tree, viewable in the
  platform's own frontend (as a structured tree, live-queried from Tempo by `trace_id`) and in
  Grafana.
- Evaluation (sampling, eligibility, judging, the attention dashboard) keeps working identically,
  with zero dependency on Tempo's availability - confirmed per-decision in the exploration that
  led to this change.
- A per-request/per-turn cost figure, computed from token usage and a maintained price list,
  absent (never fabricated) for an unpriced model.
- The three reference agents demonstrate real OpenTelemetry instrumentation end to end, so they
  remain a faithful template for anyone building a real agent against this platform.

**Non-Goals:**
- Loki (log storage) - not requested for this change.
- Routing the lightweight turn-summary channel itself through OTel/the Collector - the existing
  custom JSON ingest stays, explicitly chosen over Collector-side span-filtering/routing.
- Changing what the eval DB treats as the source of truth for scoring/judging - unchanged; OTel is
  observability, never an evaluation dependency.
- A pre-aggregated metrics/trace store, or anything beyond "query Tempo live when a human asks to
  see a trace" - no new standing infrastructure duplicates what Tempo already does well.
- Migrating any *other* agent an operator might already have deployed - this change only
  instruments the three shipped reference agents; a real deployed agent's own OTel instrumentation
  is the agent owner's work, guided by the existing `agents/CACHING.md`-style documentation
  convention (a follow-on doc, not part of this change's tasks).

## Decisions

**1. The observability stack is a new, separately-deployed subsystem: `observability/`.** An
OpenTelemetry Collector (receives OTLP from the Runner and from agents), Tempo (trace storage),
and Grafana (Tempo as its data source, provisioned), each with its own `docker-compose` service,
config checked into the repo (mirroring `gateway/config.yaml`'s "hand-authored, version-controlled,
never a literal secret" convention), and its own README. *Alternative considered*: fold Tempo/the
Collector into the main backend's own deploy - rejected, breaks the "main backend starts without
the stack" goal and the `gateway/` precedent this is explicitly modeled on.

**2. The Runner emits spans directly; agents emit spans via the OTel SDK; neither round-trips
through the platform's own ingest for span detail.** The Runner is the backend's own process, so
it instruments itself in-process (a tracer, spans for warm-up/generate/judge phases, OTLP export to
the Collector) with no network ingestion step of its own. Agents are external processes; they
export OTLP straight to the Collector too - the backend is never in the span-ingestion path for
either surface. This is what makes "Tempo unreachable only affects the trace view" true: nothing
that feeds evaluation has to succeed in delivering spans anywhere.

**3. `trace_id` is the only correlation the backend needs to store.** `Result` gains `trace_id:
str | None`; `AgentTurn` gains `trace_id: str | None` (alongside the `models`/token-total/cost
fields `turn.end` now reports directly, replacing what used to be derived from aggregated `span`
events). No span data is duplicated into either table. *Alternative considered*: store a denormalized
copy of each span's key fields locally too (for faster list views without a Tempo round trip) -
deferred; the explicit choice from the exploration that led to this change was "Tempo unreachable ->
just don't show the tree," which only needs the id, not a cache of its content. Revisit only if the
live Tempo query proves too slow for the drill-down UX in practice.

**4. The backend proxies Tempo queries for the frontend; the browser never talks to Tempo
directly.** A new small module (mirroring `app/ollama/client.py`'s `httpx.AsyncClient` shape)
wraps Tempo's query API (fetch-trace-by-id, the only query this change needs - no TraceQL search
UI), exposed as `GET /api/traces/{trace_id}` from the main backend. This keeps Tempo's own
location/auth a backend-only concern (consistent with how provider keys are handled - never
exposed to the browser) and gives one place to implement the "unreachable -> graceful 503-like
response" behavior the spec requires, rather than every frontend call site handling Tempo's own
error shapes directly.

**5. Agents instrument with the real OpenTelemetry SDK and the (experimental) GenAI semantic
conventions for model-call attributes** (`gen_ai.request.model`, `gen_ai.usage.input_tokens`,
`gen_ai.usage.output_tokens`, and so on - these conventions are still marked experimental upstream,
so attribute names should be pinned to a specific OTel semconv package version and revisited if it
stabilizes with breaking renames). A tool-call span uses plain span attributes (name, args, result)
since GenAI semconv doesn't cover non-model tool calls. `eval_agent_sdk` gains a thin
tracer-provider setup helper so the three reference agents configure OTLP export consistently,
rather than each hand-rolling SDK setup. *Trade-off, named explicitly*: this is a real change to
the SDK's stated "httpx only" design goal - `opentelemetry-sdk` and an OTLP exporter are new
dependencies for every agent that uses it. Accepted per the exploration's explicit "big change,
worth it" call; `agents/requirements.txt`'s existing pinned-dependency convention (litellm,
langchain, etc. pinned and commented) is followed for the new OTel packages too.

**6. `turn.end` becomes the single place a turn's models/tokens/cost/reasoning-trace are
reported**, since they can no longer be derived by the backend aggregating `span` events (that
event type is retired). The agent SDK computes the models/tokens/cost itself (it already holds
the per-call usage it was instrumenting) and assembles the turn's own reasoning trace (previously
the backend concatenated it from `span` events' `thinking` fields) before sending `turn.end` - the
backend's evaluation-eligibility check (`live-evaluation`), the judge-context builder
(`turn_response_text`), and the attention/monitoring aggregates (`agent-monitoring`) read these
fields exactly as they read the old derived ones, with no change to *how* they're consumed, only
*where they come from*. *Gap found and closed during apply*: the first draft of this change
retired `span` events without replacing their role as the only source of a turn's reasoning trace
for judge calls - caught via a test exercising `turn_response_text()`, confirmed with the user, and
closed by adding this one field to `turn.end` rather than silently accepting the judging-quality
regression or reviving `span` events for this alone.

**7. Cost is computed from a single maintained price-list file, read by both surfaces.** A new
`pricing.yaml` (or similar - exact location decided in tasks, likely `backend/app/data/`
alongside `starter_suite.yaml`'s precedent), keyed by model/provider, giving price-per-1K (or
similar unit) input and output tokens. One small, pure function computes cost from
(model, prompt_tokens, completion_tokens) and that table; the Runner calls it when building a
`Result`'s metrics, and the agent SDK calls an equivalent (or the agent calls the backend to look
it up, decided in tasks) when building `turn.end`. *Alternative considered*: fetch live pricing
from each provider's own API - rejected, no provider exposes this as a queryable API; a
hand-maintained file is the only available mechanism and matches this project's existing
precedent for this kind of slow-changing reference data.

## Risks / Trade-offs

- [GenAI semantic conventions are still experimental upstream and may rename attributes in a
  future OTel release] -> pin the semconv package version explicitly in `agents/requirements.txt`
  and `backend/pyproject.toml`; a future bump is a deliberate, reviewed change, not an automatic one
  - the same policy already applied to litellm/langchain.
- [The agent SDK's "dependency-light" design goal is genuinely compromised by this change] -> named
  explicitly rather than quietly dropped; accepted because real OTel instrumentation was the
  explicit, confirmed choice over the lighter-weight alternative (keeping the custom span-event
  type) during exploration.
- [A result/turn's trace-tree view makes a live network call to Tempo on every open, with no local
  cache] -> acceptable per the explicit "Tempo down -> just say so" decision; if this proves slow
  in practice, a short-TTL cache at the backend's Tempo-proxy endpoint is a contained follow-up,
  not a redesign.
- [Three reference agents' instrumentation code all change at once, in a single change, with no
  intermediate state where some use the old SDK and some the new one] -> acceptable given tests
  cover `chatbot.py`/`reasoning_agent.py`/`classifier_router_agent.py` already import directly in
  `test_reference_agents.py`/`test_classifier_router_agent.py`; tasks.md sequences the SDK change
  before any agent migrates, and each agent migrates (and its own tests pass) before the next,
  rather than one large simultaneous rewrite.
- [A price list goes stale as providers change pricing] -> same category of risk as any other
  hand-maintained reference file in this project (`starter_suite.yaml`, `gateway/config.yaml`); no
  different mitigation needed than "update it when it's known to be wrong," since no provider
  exposes pricing as a live, queryable API to automate this against.

## Migration Plan

Additive for existing data: a `Result`/`AgentTurn` row from before this change has no
`trace_id`/`cost` and the frontend shows "no trace available" for it - identical to the
degraded-Tempo case, so no special-casing is needed for old data versus a live outage. The `span`
ingest event type is removed from the contract (a breaking change to that one event type, not to
`turn.start`/`turn.end`); an agent still sending `span` events after this ships has only those
specific events rejected - reported with their index and reason, per `trace-ingestion`'s existing
"Malformed events are rejected individually" requirement, unmodified by this change - while its
`turn.start`/`turn.end` events in the same batch are accepted normally; no whole-batch failure.
Rollback is removing the
`observability/` stack, the new columns, and the OTel instrumentation; nothing else depends on
them, and evaluation was never made to depend on Tempo in the first place.
