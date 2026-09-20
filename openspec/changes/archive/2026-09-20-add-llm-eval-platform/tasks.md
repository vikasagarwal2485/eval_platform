# Tasks

## 1. Project Setup

- [x] 1.1 Scaffold repo layout (`backend/`, `frontend/`, `data/`) with Python project config (dependencies: fastapi, uvicorn, httpx, pydantic, sqlalchemy, alembic, pytest) and verify `pip install -e backend` (or equivalent) succeeds
- [x] 1.2 Add backend app skeleton with `GET /api/health` and config loading (`OLLAMA_BASE_URL`, DB path, request timeout) and verify a pytest test asserts the endpoint returns 200 and the effective config
- [x] 1.3 Scaffold the React + Vite + TypeScript frontend with routing for Run Setup, Run Live, Results, Suites, History and verify `npm run build` and `npm run dev` load all routes
- [x] 1.4 Add dev tooling (lint/format for both stacks, a single `make dev` / script that starts backend and frontend) and verify the command starts both and the SPA reaches `/api/health`

## 2. Persistence

- [x] 2.1 Define SQLAlchemy models for model_snapshot, suite, test_case, run, run_case, result, score, scoring_attempt per design D8 and verify a test creates the schema in an in-memory SQLite DB
- [x] 2.2 Set up Alembic with an initial migration and verify `alembic upgrade head` on an empty file DB creates all tables
- [x] 2.3 Implement repository functions for suites/cases, runs, results, scores and verify unit tests cover create/read/update/delete and that run_case freezes case content when the source case is edited or deleted

## 3. Ollama Client and Model Discovery (`model-discovery`)

- [x] 3.1 Implement Ollama client module (`/api/tags`, `/api/show`, `/api/ps`, streaming `/api/chat`, unload via `keep_alive: 0`, version) behind an interface and verify with contract tests against recorded fixtures
- [x] 3.2 Implement `GET /api/models` (with `refresh`) returning name, digest, size, params, quantization, family, capabilities, thinking flag and verify tests for populated, empty, and refreshed lists
- [x] 3.3 Implement connectivity reporting in `/api/health` and error responses when Ollama is unreachable and verify a test with the server mocked as down returns the "unreachable" state and configured URL
- [x] 3.4 Verify against the live local Ollama that `qwen3:8b` is listed as thinking-capable (manual check documented in the test notes)

## 4. Test Suites (`test-suites`)

- [x] 4.1 Implement Pydantic schemas and validation for the three categories (classification labels/expected-in-labels, reasoning comparison mode and tolerance, generation rubric/constraints) and verify unit tests reject empty prompts, unknown categories, and expected labels not in the label set
- [x] 4.2 Implement suite and case CRUD endpoints including duplicate suite and verify API tests cover create, edit, duplicate, delete, and mixed-category suites
- [x] 4.3 Implement suite import/export (JSON or YAML) with schema validation and no partial import on error, and verify a round-trip test yields identical suites and a malformed file creates nothing and reports field errors
- [x] 4.4 Author the built-in starter suite (at least 5 classification, 5 reasoning, 3 generation cases with expected answers/rubrics) and seed it on first launch, verifying a fresh DB contains it after startup
- [x] 4.5 Support ad-hoc prompts (single-case run input, optional expected answer, save-to-suite) and verify tests for ad-hoc creation with and without expected answer

## 5. Prompt Templates and Scoring (`response-scoring`)

- [x] 5.1 Implement versioned per-category prompt suffix templates and verify unit tests assert the suffix content and version id are attached to results
- [x] 5.2 Implement thinking/answer separation (structured `thinking` field and inline `<think>` stripping) and verify unit tests for both forms and for outputs with no reasoning
- [x] 5.3 Implement classification scorer (normalization, label matching, ambiguity handling, `unparseable`) and verify parametrized unit tests for correct, wrong, multiple-label, and no-label outputs
- [x] 5.4 Implement classification aggregates (accuracy, per-label precision/recall, confusion matrix) and verify against a hand-computed example
- [x] 5.5 Implement reasoning scorer (final-answer extraction with fallbacks; numeric tolerance and text comparison) and verify unit tests for marked answer, fallback extraction, tolerance, and unparseable cases
- [x] 5.6 Implement deterministic generation constraint checks (length, required/forbidden keywords) and verify unit tests including the max-words violation scenario
- [x] 5.7 Implement LLM-judge scorer (rubric prompt, JSON-schema structured output, single retry, `error` on failure, self-judge flag) and verify tests using a fake Ollama client for valid, invalid-then-valid, and always-invalid responses
- [x] 5.8 Implement per-category and weighted composite aggregation (excluding unscored cases, weight renormalization for missing categories) and verify unit tests including the "no reasoning cases" scenario
- [x] 5.9 Implement re-scoring endpoint that creates a new scoring attempt without touching outputs/metrics and verify a test that a second judge model leaves results unchanged and keeps the first attempt readable

## 6. Run Orchestration (`evaluation-runs`)

- [x] 6.1 Implement run creation (`POST /api/runs`) with validation (models exist, at least one case, config bounds), defaults (temperature 0, fixed seed, 1 repeat, warm-up on), and frozen run/case/model snapshots, verified by API tests including the nothing-selected error
- [x] 6.2 Implement the sequential, model-grouped worker with a FIFO queue and single active run and verify with a fake client that all model A requests precede model B and a second run never overlaps the first
- [x] 6.3 Implement per-request execution with the streaming client, per-request timeout, transient-error retry, and failure isolation, verifying tests for timeout, model error, and server disconnect (run `failed`, partial results preserved)
- [x] 6.4 Implement unloading the previous model between models and per-model warm-up request and verify with the fake client that the unload/warm-up calls occur in the expected order
- [x] 6.5 Implement cancellation (cancel token, abort the stream, status `cancelled`, keep completed results) and verify a test cancels mid-run and confirms remaining requests never start
- [x] 6.6 Implement SSE endpoint `GET /api/runs/{id}/events` (state, result-completed, token-delta events) and verify a test client receives progress events in order and can resync via `GET /api/runs/{id}`
- [x] 6.7 Implement run history endpoints (list, get, delete, re-run linked via parent_run_id) and verify a re-run reproduces the same configuration and links to the original
- [x] 6.8 Run judge scoring as a post-generation stage (after all generation completes) and verify judge metrics are stored but excluded from evaluated-model performance aggregates

## 7. Performance Metrics (`performance-metrics`)

- [x] 7.1 Capture Ollama counters and client-side timings (TTFT, time to first answer token, wall-clock latency) into per-request metrics with `NULL` for unavailable values, verifying unit tests with recorded stream fixtures and a failed-before-first-token case
- [x] 7.2 Compute tokens/second, thinking token counts (flagged approximate when derived), and cold flag from `load_duration`, verifying unit tests for the formulas
- [x] 7.3 Record memory/VRAM footprint via `/api/ps` after warm-up and verify a test with a fixture asserts it is stored per model
- [x] 7.4 Implement aggregate statistics (mean, median, p95, min, max; per model and per category; warm-only by default with an include-cold option) and verify unit tests against hand-computed values
- [x] 7.5 Implement `GET /api/runs/{id}/summary` returning leaderboard rows (category scores, composite for supplied weights, performance stats, counts of scored cases) and verify API tests including weight changes and single-model runs

## 8. Export and Comparison

- [x] 8.1 Implement CSV and JSON export (one row per model/case/repeat with category, score, outcome, and performance columns) and verify a test parses the CSV and checks columns and row count
- [x] 8.2 Implement two-run comparison (`/api/runs/compare`) producing per-model and per-case score/performance deltas for overlap and verify a test with overlapping and non-overlapping models

## 9. Frontend

- [x] 9.1 Build API client and typed models, TanStack Query setup, and SSE hook, verifying with a component test that the hook updates on mocked events and reconnects
- [x] 9.2 Build Run Setup: model list with multi-select (details, thinking flag, connectivity error/disabled state), refresh button, and verify component tests for select count, unreachable state, and no-models empty state
- [x] 9.3 Build input entry: ad-hoc prompt form (category, labels, expected answer) and suite/case picker with per-case deselect, verifying component tests for validation and submission payloads
- [x] 9.4 Build run configuration panel (temperature, seed, repeats, context size, thinking, warm-up, judge model with self-judge warning) with defaults and verify tests for defaults and the warning
- [x] 9.5 Build Run Live view: progress bar, current model/case, incrementally appearing results, streaming preview, and cancel button, verifying with a simulated SSE stream
- [x] 9.6 Build Results leaderboard: sortable columns, category scores, composite, performance figures, scored-case counts, and adjustable weights that recompute immediately, verifying component tests for sorting and weight changes
- [x] 9.7 Build charts (per-category score bars, latency/throughput, quality-vs-speed scatter) with direct labels/markers and accessible text alternatives, verifying rendering tests and a manual check that models are distinguishable without color
- [x] 9.8 Build case drill-down: side-by-side outputs, expected answer, scores, judge justification, collapsible reasoning trace, metrics, and failure filter, verifying component tests for the filter and collapse behavior
- [x] 9.9 Build Suites page (list/editor/import/export, save ad-hoc to suite) and History page (list, open, delete, re-run, two-run compare), verifying component tests and a manual round-trip import/export
- [x] 9.10 Add loading, empty, and error states across pages plus keyboard operability and control labels, verifying via an accessibility lint run (e.g. axe) with no critical violations

## 10. Integration and Delivery

- [x] 10.1 Serve the built SPA from FastAPI in production mode and verify a single command starts the app and the UI loads at one URL
- [x] 10.2 Write an end-to-end test with a fake Ollama server (recorded streams) covering select models -> run -> scoring -> summary -> export, and verify it passes in CI/local `pytest`
- [x] 10.3 Run a live smoke evaluation against local Ollama using `qwen3:8b` with the starter suite (and a second model if pulled), verifying the run completes, scores and metrics appear in the UI, and the results match manual spot checks
- [x] 10.4 Write README (prerequisites, pulling models, running, scoring methodology and limitations such as judge bias and small-suite caveat) and verify a fresh clone follows it successfully end to end
