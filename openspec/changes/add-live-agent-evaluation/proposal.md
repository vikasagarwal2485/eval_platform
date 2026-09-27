# Proposal

## Why

Today the platform is a **benchmark bench**: the platform drives the models with test suites the user wrote, and scores the answers. That answers "which model is better on my test cases?" but not "**is the AI agent I deployed behaving well on real traffic right now?**" Once an agent (a chatbot, a reasoning assistant) is running, its real conversations are the most valuable test data there is, and nothing today looks at them.

This change adds the second half of the picture: agents run **outside** the platform, every LLM interaction they have is **streamed into** the platform, and each interaction is scored by an **evaluator model that is never the agent's own model**. The user sees, live and over time, how good, how fast and how reliable each agent is, and can drill into the bad turns. It reuses the judge machinery that already exists (rubrics, structured judge output, cross-model "no self-grading" rule) and applies it to live traffic instead of a fixed suite.

## What Changes

- **Register an agent.** A new Agents area lets the user register an agent (name, kind `chatbot` or `reasoning`, the model it uses) and receive an **ingest token** (shown once, stored only as a hash). "Deploying" an agent means running it anywhere with that token and the platform URL; the platform does not host or run agents in this change.
- **Stream interactions in.** A versioned **ingest API** accepts batches of events from agents: a turn started, each LLM (or tool) call with its input, output, token usage and timings, and a turn ended. Ingest is idempotent, tolerant of out-of-order and duplicate events, never blocks on evaluation, and a tiny **agent SDK** sends events from a background queue so a platform outage can never break or slow the agent.
- **Store conversations.** Sessions, turns and calls are stored and browsable as conversations, with agent-reported latency, time to first token, token counts and errors.
- **Evaluate with a different model.** Each finished turn is queued for asynchronous evaluation against a rubric (built-in per kind, or custom per agent) by one or more **evaluator models chosen for the agent**. An evaluator is **never allowed to be a model that produced any part of the turn**; if no eligible evaluator exists the turn is marked *not evaluated* with the reason rather than self-graded. Per-evaluator scores, per-criterion scores and reasons are kept; the turn score is the mean of successful evaluators, as in cross-model judging.
- **Stay out of the way.** Evaluation is queued in the database, paced (quiet period, sampling rate, one evaluator call at a time) and **pauses while a benchmark run is measuring**, so live judging does not distort either the agent's latency or benchmark measurements on a shared local Ollama.
- **Watch it live.** An Agent page shows a live feed of turns as they arrive and get scored, rolling quality score, latency percentiles (p50/p95), error rate and token use over a time window, quality over time, per-evaluator strictness, and a "needs attention" list of low-scoring turns with full conversation drill-down. Turns can be re-evaluated with a different evaluator; earlier evaluations remain readable.
- **Ship two reference agents.** A minimal **chatbot** and a **multi-step reasoning agent** (plan, solve, verify, so one turn produces several LLM calls) run against local Ollama, use the SDK, and exist to demonstrate and test the whole loop end to end.
- **Non-goals:** hosting or launching agents from the platform UI; token-by-token streaming of answers into the platform; OpenTelemetry/OTLP ingest or an LLM proxy/gateway mode (both are compatible follow-ups on the same event model); tool-use quality scoring; alerts and notifications; multi-user auth, tenancy or scale beyond a single machine; cost tracking; automatic prompt improvement; human labelling; calibrating evaluator strictness; and any change to how benchmark runs work.

## Capabilities

### New Capabilities

- `agent-registry`: Registering, editing, pausing and deleting agents; kind, declared model, per-agent evaluation settings (evaluators, rubric, sampling, quiet period); ingest tokens (issue once, hash-only storage, rotate, revoke); agent liveness (`last seen`).
- `trace-ingestion`: The versioned event contract, authentication by agent token, validation and limits, idempotent and out-of-order-tolerant storage of sessions, turns and calls, abandoned-turn handling, retention, and the non-blocking agent SDK.
- `live-evaluation`: Queueing, pacing and executing evaluations of finished turns; the "evaluator is never a model that produced the turn" invariant; rubrics and multi-turn context; reference-based correctness when the agent supplies an expected answer; evaluator panels and aggregation; skip reasons; re-evaluation with history; coordination with benchmark runs.
- `agent-monitoring`: The Agents list and Agent page: live feed, conversations and turn drill-down, rolling quality/latency/error/token metrics, quality over time, evaluator strictness, needs-attention list, export.
- `reference-agents`: The chatbot and the multi-step reasoning agent, their configuration, and the end-to-end acceptance scenario used to test the platform.

### Modified Capabilities

<!-- None. The change is additive: benchmark runs, suites, scoring and the dashboard keep their behaviour. Judge internals are reused, not altered. -->

## Impact

- **Backend:** new modules for agent registry, ingest, trace storage, an evaluation queue/worker and a live-metrics summary; new `/api/agents/**` and `/api/ingest/v1/**` routes and an SSE stream per agent; new tables (`agent`, `agent_session`, `agent_turn`, `agent_span`, `turn_evaluation`, `turn_judgement`) by an Alembic migration. Reuses `run_judge`, rubric schemas, `aggregate_judgements` and model discovery unchanged. The generic event hub gains a keyed channel so agents and runs do not share ids.
- **Coordination with existing runs:** the evaluation worker must consult the run worker's activity so it never overlaps a measured benchmark run; this is a small read-only hook on the run worker.
- **New package:** `agents/` (SDK plus the two reference agents), httpx only, no new backend dependency.
- **Frontend:** an Agents nav entry, list page, agent detail page (Live, Conversations, Quality, Settings) and a turn drill-down that reuses the existing per-judge breakdown and chart components.
- **Privacy and data:** real user conversations are stored in the local database and sent to evaluator models; when the in-flight `add-enterprise-model-providers` change lands, choosing a hosted evaluator sends live traffic to a third party and must show the same disclosure. Retention and deletion controls are included; client-side redaction is supported by the SDK.
- **Compatibility:** existing runs, suites, exports and API callers are unchanged. The design assumes but does not depend on `add-enterprise-model-providers` (evaluators are addressed by model reference and resolved by whichever model router exists).
- **Docs and tests:** README section, event-contract documentation, unit tests for the eligibility invariant and event handling, API tests with a fake Ollama, and an end-to-end test running a reference agent against the fake server.
