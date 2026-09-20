# Design

## Context

Greenfield project on a single developer machine (macOS, Apple Silicon). Ollama 0.34.x is running at `localhost:11434`; currently only `qwen3:8b` (8.2B, Q4_K_M, capabilities: completion, tools, thinking) is installed. See `proposal.md` for motivation and scope; behavior is defined in `specs/`.

Facts about the Ollama API that shape the design:

- `GET /api/tags` lists models (name, digest, size, `details.parameter_size`, `quantization_level`, family); `POST /api/show` gives capabilities; `GET /api/ps` lists loaded models with `size` and `size_vram`.
- `POST /api/chat` streams NDJSON. The final chunk carries `total_duration`, `load_duration`, `prompt_eval_count`, `prompt_eval_duration`, `eval_count`, `eval_duration` (nanoseconds). Time-to-first-token is **not** reported and must be measured client-side.
- Thinking models can return reasoning separately (`think` option / `message.thinking`) or inline in `<think>` tags depending on model and version.
- Ollama keeps a limited number of models resident; requests to a different model trigger an unload/load. Concurrent requests distort timing.

## Goals / Non-Goals

**Goals:**
- One local, single-user app: start it, open a browser, compare models. No cloud, no auth.
- Trustworthy measurements: sequential execution, cold/warm separation, deterministic defaults, full run records.
- Scoring logic that is isolated and testable without a live Ollama server.
- Scores are derived data: recomputable from stored raw outputs.

**Non-Goals:**
- Non-Ollama providers (the Ollama client is behind a small interface, but only one implementation is built).
- Standard benchmark harnesses (MMLU, GSM8K, etc.) as a dependency; import of such datasets is possible later via the suite file format.
- Multi-user access, authentication, remote deployment, horizontal scaling.
- Hardware telemetry beyond `/api/ps`.

## Decisions

### D1. Stack: Python FastAPI backend + React (Vite, TypeScript) SPA + SQLite

The backend does I/O-bound streaming against Ollama, orchestration, and scoring; Python gives `httpx` (async streaming), Pydantic models shared between API validation and scoring, and easy numeric work. React with a charting library gives the dashboard interactivity (sortable leaderboard, live progress, charts). SQLite needs no service and fits a single-user local tool. In production mode FastAPI serves the built SPA so there is one process to run.

*Alternatives:* Streamlit/Gradio (fastest to build, but weak for live multi-run orchestration, custom comparison tables, and cancelable runs); Node/TypeScript full-stack (single language, but less convenient for scoring/statistics); Postgres (unnecessary operational weight).

*Assumption to confirm:* the user did not specify a stack; this is the recommended default and can be swapped before implementation without changing the specs.

### D2. Architecture

```
+-------------------+   REST + SSE    +-------------------------------+
|  React SPA        | <-------------> |  FastAPI                      |
|  - model picker   |                 |  api/   routes, SSE stream    |
|  - prompt/suite   |                 |  core/  runner, scorers,      |
|  - live run view  |                 |         aggregator            |
|  - dashboard      |                 |  ollama/ client (httpx)       |
+-------------------+                 |  db/    SQLAlchemy + SQLite   |
                                      +---------------+---------------+
                                                      | HTTP (NDJSON stream)
                                                      v
                                              +---------------+
                                              |  Ollama       |
                                              |  :11434       |
                                              +---------------+
```

Layering keeps the pieces independently testable: `ollama/` (transport, mockable), `core/runner` (scheduling and metric capture), `core/scoring/*` (pure functions from output + case to score), `core/aggregate` (pure functions over stored rows), `api/` (thin).

### D3. Run execution: single background worker, sequential, model-grouped

A run is executed by one in-process async worker that owns a FIFO queue. Order is `for model in models: warm-up; for case in cases: for repeat in repeats`. This avoids model thrash, keeps timings comparable, and gives predictable cancellation (cancel token checked between chunks; the HTTP stream is closed to abort generation on the server).

Between models the runner asks Ollama to unload the previous model (`keep_alive: 0`) so the next model's cold-start cost is measured and memory is available.

*Alternatives:* parallel execution across models (faster wall-clock, but invalid latency numbers and likely memory exhaustion); external job queue (Celery/RQ) - excessive for a single-user local app.

### D4. Progress delivery: Server-Sent Events

The UI subscribes to `GET /api/runs/{id}/events` (SSE) for run state, per-result completion, and optional token deltas for the preview. SSE is one-directional, works over plain HTTP, reconnects automatically, and needs no WebSocket library. Cancel is a normal `POST`. On reconnect the client refetches run state, so SSE carries hints, not the source of truth.

### D5. Metrics capture

- From Ollama final chunk: load, prompt-eval, eval durations and token counts; tokens/s = `eval_count / eval_duration`.
- Client-side: monotonic timestamps for request sent, first chunk of any kind (TTFT), first answer chunk (after thinking), and last chunk (wall-clock latency).
- Thinking tokens are approximated from the thinking segment when Ollama does not report them separately; the approximation is flagged in the record.
- Warm-up: one small request per model before measured requests (configurable). Any measured request that still shows non-trivial `load_duration` is flagged `cold` and excluded from warm aggregates by default.
- `/api/ps` is polled once after the warm-up to record memory/VRAM footprint.
- Absent values are stored as `NULL`, never `0`.

### D6. Deterministic defaults

`temperature=0`, fixed `seed`, explicit `num_ctx` and `num_predict` per run. All are stored in the run record along with each model's digest, so a result can always be tied to the exact model artifact. Repeats (default 1) exist to measure performance variance; with temperature 0 they mostly help latency statistics.

### D7. Scoring pipeline

Scoring is a separate stage that reads stored results and writes score rows, so it can be re-run (new judge, corrected expectations) without regenerating output.

```
result(output, thinking) --> split_thinking --> final_answer
   classification: normalize -> match allowed labels -> 0/1 | unparseable
   reasoning:      extract "Final answer:" -> compare (text | numeric+tol)
   generation:     constraint checks + judge(rubric) -> 0..1
```

- **Prompt templates** add a short, fixed instruction suffix per category (e.g. "Answer with exactly one of: <labels>", "End with `Final answer: <answer>`"). The suffix is versioned and stored with the result; the original user prompt remains visible.
- **Classification:** normalize, then pick the allowed label appearing in the answer; if several labels appear, the first one in the answer text wins, and ambiguity is noted. No label found -> `unparseable`.
- **Reasoning:** extract text after the last `Final answer:`; fallback to the last number/last line by documented rule. Numeric compare with tolerance; else normalized string compare.
- **Judge (LLM-as-judge):** a user-selected local model receives the case prompt, the rubric, and the answer, and must return JSON `{criterion: {score 1-5, reason}}`. Uses Ollama's structured output (`format` JSON schema) to raise parse reliability, with a single retry. Judge runs at temperature 0, and its own metrics are stored but excluded from the evaluated models' performance numbers. Judging runs after all generation completes so judge model loading does not interfere with measured latency.
- **Composite:** weighted mean over categories that have scored cases; weights are a presentation-time parameter (not stored in results) so they can be changed instantly in the UI.

*Alternatives:* embedding-similarity scoring for generation (cheap but poorly correlated with quality on open-ended text); string-overlap metrics like BLEU/ROUGE (require references and mislead on paraphrase). Judge + deterministic constraints is more useful, with the caveat in Risks.

### D8. Data model (SQLite)

```
model_snapshot(id, name, digest, params, quant, family, size_bytes, capabilities)
suite(id, name, description)            test_case(id, suite_id, category, prompt, system_prompt,
                                                   expected, config_json, rubric_json, tags)
run(id, status, config_json, judge_model, created_at, finished_at, parent_run_id)
run_case(id, run_id, category, prompt, system_prompt, expected, config_json, rubric_json)  -- frozen copy
result(id, run_id, model_snapshot_id, run_case_id, repeat_idx, status, output, thinking,
       error, is_cold, metrics_json)
score(id, result_id, scoring_attempt_id, kind, value, outcome, detail_json)
scoring_attempt(id, run_id, judge_model, created_at)
```

Runs freeze a copy of cases and model snapshots so later edits/deletions never rewrite history (spec: test-suites, evaluation-runs). `metrics_json` keeps the raw Ollama counters and client timings; typed columns are added for the fields the dashboard sorts on. Alembic migrations version the schema.

### D9. API surface (indicative)

```
GET  /api/health                 GET  /api/models[?refresh=1]
CRUD /api/suites, /api/suites/{id}/cases    POST /api/suites/import  GET /api/suites/{id}/export
POST /api/runs                   GET  /api/runs, /api/runs/{id}
POST /api/runs/{id}/cancel       GET  /api/runs/{id}/events (SSE)
POST /api/runs/{id}/rescore      GET  /api/runs/{id}/results, /api/runs/{id}/summary?weights=...
GET  /api/runs/{id}/export?format=csv|json
GET  /api/runs/compare?a=..&b=..
```

`summary` computes aggregates on demand from stored rows (cheap at this scale), which keeps weight changes and filters stateless.

### D10. Frontend structure

Pages: **Run Setup** (models, inputs, config), **Run Live** (progress, streaming preview), **Results** (leaderboard, charts, drill-down), **Suites** (editor/import/export), **History** (list/compare). Charts use a lightweight library (Recharts or ECharts). Charts encode models with color plus direct labels/markers to remain readable without color; the trade-off view is a scatter of score (y) versus tokens/s (x). State fetching via TanStack Query; SSE via `EventSource`.

### D11. Configuration

Environment/config file for `OLLAMA_BASE_URL` (default `http://localhost:11434`), DB path, per-request timeout (default 300s to allow slow local generations), and retry policy for transient connection errors. The UI shows the effective Ollama URL.

## Risks / Trade-offs

- **LLM-judge bias and weak local judges** (self-preference, noisy scores from small models) → judge is user-selected, self-judging is flagged, rubric criteria are narrow, re-scoring with a different judge is supported, deterministic checks are reported alongside; UI labels judge scores as judged.
- **Only one model installed today** → single-model paths are first-class (absolute scores, no empty comparison panels); using the same model as judge is likely at first and is flagged.
- **Timing noise (thermal throttling, background load, unified memory pressure)** → sequential execution, warm-up, repeats with median/p95, and cold-start separation; the UI shows spread and notes that results are machine-specific.
- **Thinking models inflate latency and tokens** → thinking tokens/time are recorded separately, TTFT and time-to-first-answer-token are both shown, and a per-model thinking toggle is configurable per run.
- **Answer extraction fragility** (models ignoring the "Final answer:" or single-label instruction) → versioned template suffix, documented fallbacks, `unparseable` tracked as its own outcome rather than silently "wrong".
- **Small starter suite is not statistically meaningful** → the UI shows number of cases behind each score; suites are easily extended/imported; results are presented as indicative comparisons.
- **Long runs on slow hardware** → live progress, cancellation, failure isolation, persisted partial results; an up-front estimate is not attempted (unreliable).
- **Ollama API drift** (fields, `think` behaviour differ across versions) → all Ollama access in one client module with contract tests against recorded fixtures, and the Ollama version is recorded in each run.
- **Prompt suffix influences model behavior** → suffixes are minimal, versioned, and visible in the drill-down so users can see exactly what was sent.

## Open Questions

- Whether to support importing public benchmark datasets (e.g. GSM8K subsets) via a converter script after v1.
- Whether to add an optional "consistency" metric over multiple non-zero-temperature samples later.

## Implementation Notes

Decisions settled while implementing; the specs are unchanged by these.

- **Charts are hand-rolled SVG** (no charting dependency). It keeps the mark specs exact (24px column cap, 4px rounded
  data ends, 2px surface gaps and rings, hairline solid grid), stays testable in jsdom, and adds no bundle weight.
  Categorical colours use a validated 8-slot palette assigned by a model's position in the run, never by rank. Every chart
  has a legend (or direct labels) and a table view.
- **Composite is computed twice with the same rule**: on the server (`/summary?weights=`, used by export and compare) and in
  the browser, so moving a weight slider re-ranks instantly with no request.
- **Judge score normalization** is `(mean of 1-5 criteria - 1) / 4`, so 1 maps to 0% and 5 to 100%.
- **Failed requests score 0** with outcome `error` in every category (including generation), and are counted separately.
- **Classification answer selection**: exact match wins; otherwise text after an explicit marker (`Label:`, `Answer:`)
  is preferred over earlier mentions; otherwise the first allowed label mentioned. Longer labels are matched first so
  `spam` is not found inside `not_spam`. Ambiguity is flagged.
- **Reasoning answer extraction** accepts `Final answer:` (last occurrence, decorations such as `<5>`, `**`, `$` removed),
  `\boxed{}`, `the answer is`, then the last number (numeric) or last line (text). A markerless text answer may *start
  with* the expected text ("Yes, because..."); marked answers are compared strictly.
- **The built-in suite is read-only** (duplicate it to customise), which makes seeding idempotent without a marker table.
- **Ad-hoc prompts** can be saved into an existing user suite or a new one.
- **Restart safety**: runs left `queued`/`running` by a previous process are marked `failed` on startup.
- **Warm-up uses the run's exact `num_ctx`** (only `num_predict` differs); a different context size would force a reload.
- **Cold detection** flags a measured request whose `load_duration` exceeds 300 ms.

