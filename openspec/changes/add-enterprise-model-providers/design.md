# Design

## Context

Everything model-facing is currently Ollama-shaped. Observed in the code:

- The runner, the judge and model discovery talk to one `OllamaClient` (`chat_stream`, `unload`, `ps`, `version`, `list_models`, `show`). Models are identified by their bare **name** everywhere: `RunCreate.models`, `judge_model`, `ModelSnapshot.name`, exports, the UI and cross-model planning.
- `chat_stream` yields **Ollama-shaped chunks** (`message.content`, `message.thinking`, a final chunk with `prompt_eval_count`, `eval_count`, `eval_duration`, `load_duration`, ...). `StreamCollector` and `compute_metrics` turn those into latency, TTFT, tokens per second, cold flags and thinking-token approximations; the judge reads the same chunks.
- The runner assumes local concepts: a warm-up request, unloading the previous model, reading `/api/ps` for memory, a `think` flag for thinking-capable models, and connection loss (`OllamaUnreachable`) failing the whole run after retries; other `OllamaError`s are recorded per request.
- Settings hold one `ollama_base_url`; the README states nothing leaves the machine.
- The specs for judging, metrics and the dashboard were written for local models (for example "a locally hosted model", "as reported by Ollama").

The user chose to keep **API keys out of the application entirely**: a provider is registered with the *name of an environment variable* and the app reads it at call time. See `proposal.md` for motivation and `specs/` for behaviour.

## Goals / Non-Goals

**Goals:**
- Call OpenAI and Anthropic models for generation and judging with the same runner, scoring, summary, export and UI as local models.
- Keep everything downstream of the backend (runner logic, `StreamCollector`, scorers, aggregation, cross-model planning) unaware of which provider produced a chunk.
- Never let a key reach the database, API, logs, exports or error text.
- Existing bare-name callers, runs and exports keep working unchanged.
- Be honest about what cloud metrics mean and which parameters were not honoured.

**Non-Goals:**
- Storing or encrypting keys, pricing or spend tracking, providers beyond OpenAI and Anthropic (an OpenAI-compatible `base_url` is supported, nothing more), parallel or batch requests, function calling, vision, or changing how any score is computed.

## Decisions

### D1. A backend abstraction that emits Ollama-shaped chunks

Introduce `ModelBackend` (the shape `OllamaClient` already has: `chat_stream`, `aclose`) plus a small `BackendCaps` (`warmup`, `unload`, `footprint`, `seed`, `context_size`) describing what a backend supports. `HttpOllamaClient` stays as is and gains caps; new `OpenAIBackend` and `AnthropicBackend` live in `app/providers/`. A `ModelRouter` resolves a model reference to `(backend, provider model id, registry row)` and exposes the same methods the runner and judge call today (`chat_stream(ref, ...)`, `unload(ref)` as a no-op for cloud, `capabilities(ref)`).

Adapters **translate provider streams into the existing chunk shape**: content deltas become `message.content`, reasoning deltas `message.thinking`, and a final `done` chunk carries `prompt_eval_count` and `eval_count` mapped from usage plus a `_provider` block (`model_version`, `attempts`, `retry_wait_ms`, `params_applied`, `params_ignored`, `reasoning_tokens`, `finish_reason`). Because `StreamCollector`, `split_thinking`, the judge and the scorers only see chunks, they need no provider knowledge.

*Alternatives:* a provider-neutral chunk type with conversion in the runner (cleaner in theory, but rewrites `StreamCollector`, the judge and every test double for no functional gain); a vendor SDK per provider (adds dependencies and hides streaming/timing details we need; we already use `httpx`).

### D2. Model references: `@provider/model`, bare names stay Ollama

An enterprise model is referenced as `@<provider-name>/<model-id>` (for example `@openai-main/gpt-4o`). A leading `@` cannot start an Ollama model name, so references cannot collide with existing names and **every existing API field that carries a model name keeps working** (`RunCreate.models`, `judge_model`, exports, snapshot names). Provider names are restricted to `[a-z0-9][a-z0-9_-]{0,39}`; the reference splits at the first `/` after the `@`, so model ids may contain `/` and `:` (gateways often do). Two providers of the same kind (two keys or organisations) are two providers with two names.

*Alternatives:* `provider:model` (collides with Ollama `name:tag`); numeric registry ids in the API (breaks the "names everywhere" contract and makes exports unreadable).

### D3. Registry tables and snapshots

New tables: `provider(id, kind, name unique, key_env, base_url, ack_at, created_at)` and `registered_model(id, provider_id, model_id, display_name, enabled, reasoning, unique(provider_id, model_id))`. `ModelSnapshot` gains `provider_kind` (null = Ollama) and `source` (`local`/`cloud`, default `local`). A cloud snapshot uses the reference as `name`, an empty `digest`, and no size/quantization; the provider-reported **model version** is stored per result in its metrics and summarised on the run, because it is only known after the first response. Snapshots hold no foreign key to the registry, so removing a provider or model never breaks history; the UI marks references not found in the registry as "removed".

### D4. Keys: environment only, redacted everywhere

- `key_env` must be an env-var name (`^[A-Z_][A-Z0-9_]*$`, at most 64 chars, and not key-shaped such as `sk-...`); a value that looks like a key is rejected with an explanation. There is no API field or UI input that accepts a key.
- A `KeyProvider` reads `os.environ` **at call time**; `key_available` is computed on read and returned as a boolean. Because a process cannot see variables exported after it started, the UI says a restart is needed.
- A `Redactor` scrubs the current values of every registered provider's key (and generic `sk-`/`sk-ant-` shapes) from any exception text before it is stored, logged or returned. Adapters send the key only in the auth header (`Authorization: Bearer` for OpenAI, `x-api-key` for Anthropic), never in a URL, and requests do not follow redirects, so a key cannot be sent to another host.
- Run configuration, results, exports and `ProviderOut` contain no key material. A test plants a sentinel key value and scans the SQLite file, every API response, both exports, captured logs and stored error strings for it.

### D5. OpenAI adapter

Chat Completions streaming with `stream_options.include_usage` (one HTTP call, usage in the last event). `max_completion_tokens` is sent for the official base URL (needed by reasoning models) and `max_tokens` for a custom `base_url`, since compatible gateways usually accept only the latter. Temperature is omitted for models flagged as reasoning; `seed` is sent (best effort) and recorded as applied but non-guaranteed. `usage.completion_tokens_details.reasoning_tokens` becomes exact thinking tokens; the reasoning text is not returned by this API, so there is no trace. The judge's schema is sent as `response_format: json_schema` with `additionalProperties: false` added recursively, as strict mode requires. Model list and connection test: `GET /v1/models` (free).

### D6. Anthropic adapter

Messages API streaming (`x-api-key`, `anthropic-version` header). The system prompt is passed separately and `max_tokens` is always set. `seed` and `num_ctx` are not supported and are recorded as ignored. Input tokens come from `message_start`, output tokens from `message_delta`, and the resolved model from `message_start.message.model`. For a model flagged as reasoning with thinking enabled the adapter sets `thinking.budget_tokens` (bounded below `max_tokens`), drops temperature as the API requires, records that, and maps `thinking_delta` events to `message.thinking`. Anthropic has no JSON-schema response mode in the Messages API, so structured judging uses a single **forced tool call** whose `input_schema` is the rubric schema; the streamed tool input is emitted as the content text. Judges never run with thinking on (forced tool choice is incompatible with it). Model list and connection test: `GET /v1/models`.

### D7. Metrics semantics for cloud requests

`compute_metrics` gains a client-timing path: when `eval_duration` is absent, tokens per second is `output_tokens / (t_end - t_first_token)`, marked `tokens_per_s_source: "client"`; load duration, prompt/eval durations and memory are `None`; `is_cold` is false; thinking tokens are exact when `reasoning_tokens` is reported. Latency and TTFT are measured from the start of the **successful attempt**; time spent waiting between retries is recorded separately as `retry_wait_ms` and `attempts`, not folded into generation time. Metrics carry `is_cloud` so the UI can label latency as including network and queueing and show the local-vs-cloud caveat.

### D8. Runner integration and failure semantics

- The runner takes a `ModelRouter` instead of a single client. For backends without `warmup`/`unload`/`footprint` caps it skips `_warmup`, `unload` and `_record_footprint` (no billable warm-up, no memory figure). `think` is sent only to models flagged thinking/reasoning; `num_ctx` and `seed` are passed through and the adapter reports what it applied.
- Provider errors are a new hierarchy under a common `ModelBackendError` (`OllamaError` moves under it): `ProviderAuthError`, `ProviderRateLimited`, `ProviderUnavailable`. Retries with exponential backoff and jitter, honouring `Retry-After`, happen **inside the adapter before the first byte** (429, 5xx, overloaded, connection reset), bounded by `EVAL_PROVIDER_MAX_RETRIES` (default 4).
- Provider errors never use `OllamaUnreachable`, so they never fail the run. After a `ProviderAuthError` the runner opens a per-run **circuit** for that model (its remaining requests are recorded as errors without being sent); after retries are exhausted on `ProviderUnavailable` it opens the circuit for that provider. Ollama unreachability keeps its current run-fatal behaviour.
- Preflight (`router.preflight(refs)`) runs in create, re-run and re-score before anything is queued: each ref must be a known Ollama name, or a registered, enabled cloud model whose provider key is available; otherwise 422 `model_unavailable` listing `{ref, reason}` for every problem, judges included.

### D9. Judging over a mixed model set

Judging modes and validation are unchanged; the difference is the set of candidates. `single` accepts any available model reference (a hosted model can judge two local ones and is not a contestant, so it is never "self-judged"). `cross_model` plans over the run's model references; `plan_judgements`, `judge_think` and the unload callback already work on names, so they work on references, and unloading is a no-op for cloud judges. Judge calls go through the router; `ProviderAuthError`/`ProviderUnavailable` during judging become `error` judgements with a per-judge circuit, not run failures. The Judge strictness table and per-judge breakdown need no change.

### D10. API surface

- `GET /api/models`: unified list; `name` remains the reference, plus `display_name`, `source`, `provider`, `available`, `unavailable_reason`, `reasoning`. Ollama being down still returns enterprise models (today it is a 503 for the whole list).
- `/api/health`: adds `providers: [{name, kind, key_available}]`; the existing `status` still reflects Ollama, and clients decide what is blocked from the models a run needs.
- `/api/providers` (list/create/update/delete), `/api/providers/{id}/test`, `/api/providers/{id}/available-models`, `/api/providers/{id}/models` (add/update/remove). Deleting a provider used by a queued or running run is a 409.
- Run/summary/export payloads gain `source`, `provider`, `model_version`, `params_ignored` where relevant; CSV adds `source`, `provider`, `model_version`.

### D11. Frontend

A Providers page (nav link) for registration (kind, name, variable name, base URL, acknowledgment), status, connection test, adding models by id or from the fetched list, reasoning flag and enable/disable. Model picker groups **Local (Ollama)** and one group per provider, with a cloud badge and disabled entries that name the missing variable. The judge picker lists all available models. Run setup shows a **data-sharing notice** listing every provider that will receive data (contestants and judges, including cross-model judges) and request estimates split into local and per-provider counts. Results add cloud badges, the local-vs-cloud latency note, and the ignored-parameter list per result; History and export show the provider.

### D12. Configuration and migration

`EVAL_PROVIDER_MAX_RETRIES` (default 4), `EVAL_PROVIDER_BACKOFF_S` (default 1, capped at 30). The per-request timeout reuses the run's setting. Alembic `0003` is additive: `provider`, `registered_model`, and the two `model_snapshot` columns (backfilled `local`/null). Downgrade drops them; runs that used cloud models keep their reference names but lose provider metadata.

### D13. Testing without keys

Fake OpenAI and Anthropic HTTP servers (SSE, usage, rate-limit and auth error modes, `Retry-After`) drive contract tests for each adapter and an end-to-end mixed run alongside the existing fake Ollama server. Fixtures are written from the providers' documented stream formats. A live smoke test is opt-in: it runs only when the provider keys are present in the environment and is skipped otherwise, so CI and this repository never need or contain a key.

## Risks / Trade-offs

- **Provider API drift** (streaming events, structured-output rules, reasoning parameters change; models are deprecated). → All provider code sits behind adapters with contract tests; the adapter details above must be re-checked against current provider documentation when implementing; unknown-model and deprecation errors surface as per-request errors with the provider's message.
- **A key leaks** through a log, error string, export or fixture. → Env-only design (nothing to persist), redaction at every boundary, no redirects, a sentinel-scan test over DB, API, exports and logs, and README guidance.
- **Data leaves the machine**, including *other models' answers* when a cloud model judges. → Required acknowledgment at registration, a per-run notice naming each receiving provider, and README wording replacing "nothing leaves your machine".
- **Cost and rate limits** (a suite times repeats times models is many billable calls). → Request estimates per provider before starting, no warm-up requests to cloud models, bounded retries, output-token cap from the run settings, circuit breakers so an auth failure or outage does not burn requests. Pricing and hard budgets are out of scope.
- **Speed is not like-for-like** (network, queueing, shared hardware). → Metrics are labelled client-measured and including network, and the leaderboard shows a caveat whenever local and cloud models are compared.
- **Reproducibility differs**: no seed on Anthropic, best-effort seed on OpenAI, temperature not accepted by some reasoning models. → Per-result applied/ignored parameters shown in the drill-down; repeats remain available; documentation states the limits.
- **Judge strictness differs across providers**, sharpened when a strong hosted judge scores weak local models. → Existing per-judge breakdown and strictness table; single-judge and cross-model attempts remain comparable via re-score.
- **Restart needed for keys**: variables exported after launch are invisible. → The UI says so explicitly and the status shows which variable is missing.
- **Mixed failure semantics** (Ollama outage fails the run; a cloud outage does not). → Documented in the spec; justified because a cloud outage affects only that provider's models while the rest of the run is still meaningful.
- **Larger blast radius in the runner.** → Adapters emit the existing chunk shape, so the runner changes are limited to capability checks, the error hierarchy and routing; the existing test suite must stay green untouched.

## Migration Plan

1. Ship Alembic `0003` (runs automatically at start-up); existing runs keep working and read as local. 2. Deploy backend and frontend together; old clients that send bare names are unaffected. 3. Users who want cloud models export their keys, restart, register providers and models. 4. Roll back by downgrading `0003`; nothing else depends on the new tables.

## Open Questions

- OpenAI: keep Chat Completions or move to the Responses API for newer reasoning models (which changes the stream events and how reasoning is reported)? Decide against current docs at implementation; the adapter boundary makes it a local change.
- Anthropic thinking budget: fixed fraction of `max_tokens` versus a per-run setting; start with a bounded default and expose a setting only if needed.
- Whether to add a hard cap on billable requests per run (a confirm-above-N prompt) after real usage shows typical run sizes.
