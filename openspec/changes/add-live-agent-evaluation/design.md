# Design

## Context

Everything in the platform today is **pull-based and finite**. Observed in the code:

- A `Run` is a frozen list of `RunCase`s sent by the platform to chosen models; a single FIFO worker (`core/runner.py`) executes one job at a time on purpose so latency measurements are never disturbed (`max_concurrent_jobs` must stay 1). Interrupted runs fail on restart.
- Scoring is a separate stage (`core/scoring/service.py`). Judging is built from reusable, mostly pure parts: `run_judge(client, model, JudgeCall)` (structured JSON, one retry, never raises except on connection loss), `rubric_schema`, `parse_judge_output`, `normalize_scores`, `plan_judgements`, and `aggregate_judgements` (duck-typed over anything with `judge_model/value/outcome/detail`). Cross-model judging already enforces "no model grades its own answer" by comparing **snapshot ids**, and stores every individual `Judgement` plus one aggregate `Score` per answer.
- Storage is SQLite via SQLAlchemy + Alembic. `Judgement` and `Score` are keyed to `Result -> Run -> RunCase`, so they cannot hold live traffic without contortion.
- Live UI is fed by `EventHub` (SSE), keyed by an integer `run_id`. The React app already has charts, a leaderboard and a per-judge breakdown.
- `add-enterprise-model-providers` (in progress) introduces a model router so that a model reference can be local or hosted. This design only assumes "an evaluator is a model reference that a client can call through the judge interface".

New here: the **agent is the driver**. Traffic arrives unprompted, at unpredictable times, from processes the platform does not control, and it contains real user text. See `proposal.md` for motivation and scope.

## Goals / Non-Goals

**Goals:**
- One small, stable **event contract** that any agent can emit, so the platform is decoupled from how the agent is built.
- The agent is never slowed, blocked or broken by the platform (ingest is cheap; evaluation is fully asynchronous; the SDK drops rather than blocks).
- An evaluator is **provably** not a model that produced the turn, or the turn is not scored.
- Reuse the existing judge core and UI components; do not fork them.
- Live evaluation and benchmark runs coexist on one machine without corrupting each other's numbers.
- Works end to end with two local models and no cloud.

**Non-Goals:**
- Horizontal scale, multi-tenancy or a message broker. The target is one developer machine and tens of events per second, on SQLite.
- Defining a universal agent tracing standard. The contract is deliberately smaller than OpenTelemetry GenAI and maps onto it later.
- Judging quality beyond a rubric score (no root-cause analysis, no automatic fixes).

## Architecture

```
  DEPLOYED AGENTS (any host)                        EVAL PLATFORM (one process)
  +------------------------+                 +----------------------------------------------+
  | chatbot / reasoning    |                 |  /api/ingest/v1/events                       |
  |  agent code            |   HTTP batch    |   auth(token) -> validate -> upsert          |
  |   |                    |  (NDJSON/JSON)  |   session/turn/span  (idempotent)            |
  |   v                    | --------------> |        |                                     |
  |  SDK: non-blocking     |   202 fast      |        +--> EventHub(agent:{id}) --SSE--> UI |
  |  queue + retry + drop  |                 |        |                                     |
  |   |                    |                 |        v   turn.end                          |
  |   v                    |                 |   turn_evaluation(status=pending)  (DB queue)|
  |  agent's own LLM       |                 |        |                                     |
  |  (e.g. Ollama qwen3)   |                 |        v                                     |
  +------------------------+                 |   EvaluationWorker                           |
                                             |    gates: quiet period, sampling,            |
                                             |           no benchmark run active,           |
                                             |           eligible evaluator exists          |
                                             |        |                                     |
                                             |        v   run_judge(evaluator, rubric)      |
                                             |   evaluator LLM  (never a model in the turn) |
                                             |        |                                     |
                                             |        v                                     |
                                             |   turn_judgement  -> aggregate on turn_eval  |
                                             |        +--> EventHub(agent:{id}) --SSE--> UI |
                                             +----------------------------------------------+
```

Lifecycle of one turn:

```
 agent                    platform ingest            eval queue / worker             UI (SSE)
   | turn.start ---------------> create turn(open) ---------------------------------> "typing..."
   | span (llm #1) ------------> add span ----------------------------------------> feed updates
   | span (llm #2) ------------> add span
   | turn.end ------------------> close turn(ok|error)
   |                             create turn_evaluation(pending) ----> wait quiet period
   |                                                                   pick evaluators = panel - {models in turn}
   |                                                                   none? -> skipped(no_eligible_evaluator)
   |                                                                   run_judge x N (one call at a time)
   |                                                                   write judgements + aggregate ---------> score badge
   | (no turn.end for T min) --> turn := abandoned (not evaluated)
```

## Decisions

### D1. Push events through one canonical ingest API; SDK first, proxy later

Agents `POST /api/ingest/v1/events` a JSON array (or NDJSON) of events, `Authorization: Bearer <agent token>`. The platform answers `202` immediately with `{accepted, duplicates, rejected: [{index, reason}]}`; nothing in the request path calls a model.

*Alternatives considered:*
- **LLM proxy/gateway** (agent points its base URL at the platform, which forwards to Ollama and records everything). Literally "all interactions stream through", zero agent changes, and captures every call. Rejected for v1: it puts the platform in the agent's critical path (an outage or a slow evaluator would hurt the agent), must re-implement each provider's wire format, and cannot know turn/session boundaries or the agent's tool calls. Kept as a compatible follow-up: a proxy is just another producer of the same events.
- **OTLP/OpenTelemetry GenAI conventions.** Standard and tool-friendly but heavy (protobuf/JSON OTLP, spans-only, unstable attribute names) for a first slice. The event model below maps onto spans one-to-one, so an OTLP receiver can be added later.
- **Agent writes directly to the platform DB / shared file.** Couples deployment to one machine and bypasses validation.

### D2. Event contract (schema version 1)

Three event types are enough to reconstruct a conversation. Every event carries `v: 1`, a client-generated unique `event_id`, `ts` (agent clock, ISO-8601), `session_id`, `turn_id`. The agent identity comes from the token, never from the body.

| type | required payload | notes |
|---|---|---|
| `turn.start` | `input` (the user's message) | optional `reference` (expected answer, enables correctness checks), `metadata` |
| `span` | `span_id`, `kind` (`llm` \| `tool`), `started_at`, `ended_at` | `llm`: `model`, `messages` (as sent), `output`, optional `thinking`, `usage{prompt_tokens, completion_tokens}`, `ttft_ms`, `error`. `tool`: `name`, `args`, `result`, `error` |
| `turn.end` | `status` (`ok` \| `error`) | `output` (the final answer shown to the user), optional `error` |

Rules that make ingest robust:
- **Idempotent by natural key.** Turns are unique on `(agent_id, turn_id)`, sessions on `(agent_id, session_id)`, spans on `(turn_id, span_id)`. A replayed batch is counted as `duplicates`, never double-stored, so the SDK can retry freely (at-least-once).
- **Order-tolerant.** A `span` or `turn.end` that arrives before `turn.start` creates the turn; `turn.start` later fills in the input. This tolerates a retry that reorders events.
- **Bounded.** Limits per request (events, bytes) and per field (a large `output` is truncated with a marker and flagged, never rejected wholesale); unknown fields are ignored so a newer SDK works with an older platform; unknown `v` is rejected with a clear error.
- **Partial batches.** One malformed event is reported by index and does not fail the rest.
- **Abandoned turns.** A turn with no `turn.end` after a configurable timeout becomes `abandoned` and is not evaluated (a crashed agent must not create a phantom evaluation).
- **Model identity is mandatory for `llm` spans.** The set of models a turn used (`agent_turn.models`) is what the evaluator invariant is checked against (D5). An `llm` span without `model` is accepted but marks the turn `models_unknown`, which makes it non-evaluable (D5).

### D3. The SDK protects the agent

`agents/eval_agent_sdk` (httpx only, roughly one file):
- `client = AgentClient(url, token)`; `with client.turn(session_id, input=...) as t:` then `t.llm_call(...)` / `t.tool_call(...)` and `t.finish(output)`. Timing (`started_at/ended_at`, `ttft_ms`) is measured around the agent's own call.
- Events go to a **bounded in-memory queue** drained by a background thread that batches (size or interval), retries with capped exponential backoff, and **drops oldest** when full, counting drops. It never raises into agent code and never blocks the agent's response path. `close()` flushes with a deadline.
- An optional `redact(event) -> event` hook runs before anything leaves the process (PII scrubbing is the agent owner's decision; the platform stores what it receives).

### D4. New tables; reuse judge logic, not judge storage

Reusing `Run/Result/Score/Judgement` for live traffic was rejected: a `Run` is finite with frozen cases and a model snapshot per result, and the FK chain makes an "open-ended run per agent" a pile of special cases in every summary query. Instead:

```
agent(id, name unique, kind chatbot|reasoning, declared_model, status active|paused,
      token_hash, token_prefix, rubric json|null, eval_config json, last_seen_at, created_at)
agent_session(id, agent_id, external_id, started_at, last_event_at)         unique(agent_id, external_id)
agent_turn(id, agent_id, session_id, external_id, seq, input, output, reference, status
           open|ok|error|abandoned, models json, started_at, ended_at, latency_ms,
           prompt_tokens, completion_tokens, truncated bool)                 unique(agent_id, external_id)
agent_span(id, turn_id, external_id, kind, model, name, input json, output, thinking,
           started_at, ended_at, latency_ms, ttft_ms, prompt_tokens, completion_tokens, error)
                                                                             unique(turn_id, external_id)
turn_evaluation(id, turn_id, attempt_no, status pending|running|done|skipped|error, skip_reason,
                rubric json, evaluators json, value, detail json, created_at, finished_at)
turn_judgement(id, evaluation_id, judge_model, value, outcome judged|error, detail json, created_at)
```

`turn_evaluation` is the per-turn aggregate (the analogue of `Score`), `turn_judgement` the per-evaluator record (the analogue of `Judgement`). `aggregate_judgements` is called as-is (it is duck-typed); `run_judge`, `rubric_schema` and `normalize_scores` are reused as-is. Evaluations are keyed by `attempt_no`, so re-evaluation appends rather than overwrites (D8). Indexes on `(agent_id, ended_at)` and `(evaluation.status)` serve the feed and the queue.

`agent.eval_config` (validated JSON): `evaluators` (ordered model references), `sample_rate` (0..1, default 1.0), `quiet_period_s` (default 20), `context_turns` (default 4), `attention_threshold` (default 0.5), `abandon_after_s` (default 600). Holding it as one validated JSON blob keeps the table stable while the knobs evolve.

### D5. The evaluator invariant: decided at evaluation time, on what actually ran

The agent's *declared* model is only a hint; what matters is the models that **actually produced text in this turn**, taken from its `llm` spans (`agent_turn.models`). For each pending evaluation the worker computes:

```
eligible = [m for m in agent.eval_config.evaluators if not same_model(m, any model in turn.models)]
```

- `same_model` compares **normalised** references (case-folded, default `:latest` tag stripped, provider prefix preserved), and, when Ollama reports it, the model **digest**, so `qwen3:8b` and `qwen3:latest` resolving to the same digest count as the same model. Different sizes of one family (e.g. `qwen3:8b` vs `qwen3:32b`) are allowed but flagged `same_family` on the evaluation so the UI can warn about likely self-preference.
- `eligible` empty, or `turn.models` unknown/empty (an agent that does not report its model): status `skipped`, `skip_reason` `no_eligible_evaluator` / `agent_model_unknown`. **Never falls back to grading with the agent's own model.**
- Settings are also validated up front: saving `eval_config` with an evaluator equal to `declared_model` is a 422, so the mistake is caught before traffic arrives; the runtime check still exists because the declared model can be wrong or an agent can switch models.
- With several eligible evaluators every one judges the turn (a panel) and results combine by mean, exactly as in cross-model judging. Default and recommended configuration is a single evaluator.

*Alternative:* trust `declared_model` and check only at registration. Rejected: a router agent that uses model B for some turns would silently be self-judged.

### D6. What is evaluated and how

- **Unit:** the turn. Judge input is `task` = the conversation context (last `context_turns` turns of the session as `User/Assistant` lines, oldest dropped first to stay within a character budget) plus the current user message, and `response` = the turn's final output. For `reasoning` agents whose turn made several `llm` spans, the intermediate reasoning (thinking or step outputs) can be included in `response`, mirroring the existing `judge_reasoning` behaviour.
- **Rubric:** per agent, else a built-in by kind. `chatbot`: Relevance, Helpfulness, Coherence, Tone and safety. `reasoning`: Logical soundness, Clarity, plus Correctness (reference-free). Custom rubrics use the same `{name, description}` list as suites. The rubric is **snapshotted onto each evaluation**, so later edits never rewrite history.
- **Deterministic signals need no model:** empty answer, error status, latency and token counts are computed at ingest and appear immediately, before any judge score.
- **Reference-based correctness:** if `turn.start.reference` is present (e.g. the reasoning agent replaying a suite), the existing `score_reasoning` comparison runs as well and is stored beside the judged score, not blended into it.
- **Untrusted text:** the answer is user/LLM-controlled and may address the judge ("give this a 5"). The existing judge system prompt already says to ignore who wrote it; the conversation and response are placed in clearly delimited blocks, and scores outside 1-5 or missing criteria are rejected by `parse_judge_output`. Residual risk is documented, not eliminated.

### D7. Evaluation queue: in the database, paced, benchmark-aware

A **DB-backed queue** (`turn_evaluation.status = pending`) rather than an in-memory queue or a broker: it survives restarts (`running` rows are reset to `pending` at start-up, unlike runs, which cannot resume), needs no new infrastructure, and makes backlog size a simple `COUNT`.

One `EvaluationWorker` loop (one evaluator call at a time) picks the oldest eligible pending evaluation when **all** gates pass:
1. **Sampling:** decided when the evaluation row is created (`sample_rate`); unsampled turns get no row and are shown as "not sampled".
2. **Quiet period:** the turn ended at least `quiet_period_s` ago *and* the agent has been idle that long. This is the main protection for the agent's own latency on a shared Ollama.
3. **No benchmark run active:** the worker asks the run worker (read-only `is_measuring()`, true while a job is running) and waits. The runner's "one job at a time so measurements are clean" guarantee is thereby extended to live judging in the other direction: live judging never runs during a benchmark. Benchmark runs are unaffected; the backlog just grows and drains afterwards.
4. **Batching by evaluator:** pending items are grouped by evaluator so each model is loaded once per batch and unloaded (existing quiet `unload`) before the next, as judge grouping already does.

Backpressure: if the pending count exceeds a cap (default 500) the oldest pending evaluations are marked `skipped(backlog)` rather than letting the queue grow without bound, and the UI shows the number skipped. Connection loss to the evaluator's backend pauses the worker with backoff instead of erroring each item (mirrors how `OllamaUnreachable` is treated as run-fatal today, but here it is retryable because the queue is durable).

*Alternatives:* evaluate inline during ingest (couples agent latency to judge latency; rejected outright); Redis/Celery/Kafka (heavy for a single-machine tool); evaluate in the agent's SDK (agent owner would then pick and could self-judge, and a second process would compete for the GPU).

### D8. Re-evaluation keeps history

`POST /api/agents/{id}/turns/{turn}/evaluate` and `POST /api/agents/{id}/reevaluate` (a time window or "all turns below X") enqueue a **new** `turn_evaluation` with `attempt_no + 1` using the current or a supplied evaluator list and rubric. The UI shows the latest attempt and lets the user open earlier ones. This mirrors re-scoring of runs, so the user can check a cheap local evaluator against a stronger one on the same real turns without asking the agent to run again.

### D9. Live updates: one hub, keyed channels

`EventHub` becomes keyed by an opaque channel string (`run:12`, `agent:3`); existing call sites pass `run:{id}`, so behaviour is unchanged. `GET /api/agents/{id}/events` streams `turn_started`, `span_added`, `turn_finished`, `evaluation_started`, `evaluation_finished`, `agent_status`. As today, the DB is the source of truth and the feed resyncs from `GET /api/agents/{id}/turns` on reconnect; the buffer is only for catch-up.

### D10. Metrics for agents, and what they mean

`GET /api/agents/{id}/summary?window=1h|24h|7d` returns: turn counts by status; quality score (mean, and percent of turns below `attention_threshold`) over evaluated turns; latency p50/p95 and error rate over turns; token totals; evaluator strictness (mean score and error count per evaluator); backlog (pending, skipped by reason); and a bucketed time series for charts. Percentiles are computed in SQL/Python over the window (single machine scale; no pre-aggregation table yet).

Latency and tokens are **what the agent reported**, measured on its side; they are labelled as agent-reported and are not comparable to benchmark-run measurements, which the platform takes itself. Evaluator calls are stored with their own metrics on `turn_judgement.detail` and never appear in the agent's figures.

### D11. Auth, privacy and retention

- Ingest token: 32 random bytes URL-safe, shown **once** at registration/rotation, stored as SHA-256 hash plus an 8-character prefix for display; compared in constant time; revoked by rotating. A paused agent's ingest is rejected with a clear status so the SDK stops retrying. The token authorises ingest for that agent only. (This does not conflict with the enterprise-providers rule that provider API keys are never stored: this is a credential the platform issues, not one it holds for someone else.)
- The management API and UI remain unauthenticated and local-only, as today; the platform binds to localhost by default and the README says to put it behind a proxy with auth before exposing ingest to a network.
- Conversations contain user data. Deleting an agent cascades to its sessions, turns, spans and evaluations; a per-agent `retention_days` (default off) prunes old turns; the README states what is stored and where it is sent (the evaluator). If the evaluator is a hosted model (enterprise-providers change), the UI shows the same data-leaves-the-machine acknowledgement for that agent's live traffic, at the time the evaluator is chosen.

### D12. Reference agents

`agents/chatbot.py`: a REPL chatbot over Ollama `/api/chat` with a configurable system prompt; each user message is a turn with one `llm` span.
`agents/reasoning_agent.py`: solves problems given on the command line or from the reasoning cases of a suite file, in **three LLM calls per turn** (plan, solve, verify/format the final answer), so one turn has multiple spans and `models` can hold several models. With `--suite` it sends each case's `expected` as `reference`. They exist to demonstrate the contract, to be the acceptance fixture, and to make the "agent model differs from evaluator" story runnable with the two local models already in use (e.g. agent on `qwen3:8b`, evaluator `gemma4:e4b`).

### D13. UI

New nav entry **Agents**. *List:* one card per agent with status (`live` last seen < 60 s, `idle`, `offline`, `paused`), rolling quality, p95 latency, error rate, backlog. *Agent page tabs:* **Live** (feed of turns with pending / scored / not-evaluated badges, updating over SSE), **Conversations** (sessions, then turn drill-down with each span, the evaluators' scores, criteria and reasons, reusing the existing per-judge breakdown and re-evaluate action), **Quality** (score over time, latency percentiles, evaluator strictness, needs-attention list), **Settings** (kind, declared model, evaluators with the eligibility hint, rubric editor, sampling, quiet period, retention, token issue/rotate, connection snippet). Empty states explain how to connect an agent and show the SDK snippet with the platform URL.

## Risks / Trade-offs

- **[GPU/RAM contention on one Ollama]** Agent and evaluator (and benchmarks) fight for a small machine; model swapping can double latency. → Quiet period, one call at a time, benchmark-aware pause, batching by evaluator with unload, sampling, and the option to point the evaluator at a different backend (hosted models once the providers change lands). Documented as the main operational caveat.
- **[Self-preference and family bias persists across sizes of one family]** → Hard block on identical models, `same_family` flag, and per-evaluator strictness/panel visibility; calibration is out of scope.
- **[Weak local evaluators are noisy]** Live scores are indicators, not ground truth. → Structured output with retry, errors recorded not hidden, re-evaluation with a stronger evaluator, and the UI wording says "evaluator score".
- **[Judge prompt injection through agent output]** → Delimited blocks, existing strict system prompt, output validation; residual risk noted.
- **[Sensitive data at rest and in transit to the evaluator]** → Local storage only, cascade delete, retention setting, SDK redact hook, disclosure for hosted evaluators, ingest token hashed.
- **[SQLite under sustained writes]** Ingest writes compete with the run worker and the evaluation worker. → Batch inserts per request, WAL mode, short transactions, and a documented ceiling (tens of events/s); anything beyond needs a different store, which is a stated non-goal.
- **[At-least-once delivery, clock skew]** → Idempotent natural keys; ordering by platform receive time for the feed, agent timestamps for durations; a turn's `latency_ms` uses agent timestamps only within the same agent clock.
- **[Unbounded backlog]** → Cap with `skipped(backlog)` and visible counts instead of silent growth.
- **[Coupling to the run worker]** The `is_measuring()` hook is a new dependency between two workers. → Read-only, one method, covered by a test that a live evaluation never starts while a run job is active.
- **[Scope creep toward a full observability product]** → Non-goals are explicit; the event model is small on purpose.

## Migration Plan

1. Alembic revision adds the six tables and indexes; purely additive, runs at start-up.
2. `EventHub` re-keying is internal: existing run channels become `run:{id}`; SSE for runs is unchanged externally.
3. Ship the backend, then the frontend; the Agents nav entry appears with an empty state. No existing route or table changes.
4. Rollback: downgrade the revision (drops the new tables); benchmark data is untouched.

## Open Questions

- Should token-level `span.delta` events be added for a true "typing" live view? Deferred: the event model can add a type without breaking v1 producers.
- Whether to add a session-level evaluation (conversation goal achieved?) after the turn-level slice; likely yes, additive.
- Whether the first extra producer should be the LLM proxy or an OTLP receiver; decide when there is an agent that cannot use the SDK.
- Exact defaults (quiet period, backlog cap, abandon timeout) to be tuned after trying the two reference agents against real hardware.
