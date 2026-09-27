# Proposal

## Why

The platform can only evaluate models served by a local Ollama, so users cannot compare a local model against the enterprise models they actually choose between (OpenAI, Anthropic), and cannot use a strong hosted model as a neutral judge. With two small local models the only judges available are the contestants themselves. Supporting enterprise providers lets a user put local and hosted models in the same run, compare accuracy and speed on the same test cases, and pick any of them (or the evaluated models, via cross-model judging) as judge.

## What Changes

- **Register providers.** A new Providers screen lets the user register an enterprise provider (OpenAI or Anthropic) by giving it a name and the **name of the environment variable that holds its API key**. The application never stores, displays, logs, returns or exports the key itself; it reads the variable when it makes a call. An optional base URL supports gateways and OpenAI-compatible endpoints.
- **Register models.** For each provider the user adds the models to evaluate, either by typing a model id or by picking from the provider's own model list (fetched with the key). Each registered model can be enabled or disabled and flagged as a reasoning model.
- **Select and run.** Registered enterprise models appear in Run setup next to installed Ollama models, clearly marked as cloud models. Local and enterprise models can be mixed in one run; the same suites, ad-hoc prompts, settings, scoring, leaderboard, charts, drill-down, export and history apply.
- **Judge with any of them.** The existing judging modes keep working and now span both kinds of model: **single judge** may be any available local or enterprise model (for example a hosted model judging two local ones), and **cross-model judging** works across a mixed model set.
- **Call local and enterprise APIs.** The evaluation backend calls Ollama as today and calls the OpenAI and Anthropic APIs through provider adapters that stream answers, report usage, honour cancellation and timeouts, retry rate limits and transient errors with backoff, and isolate provider failures to that provider's models.
- **Honest metrics.** Cloud requests are measured the same way where possible (latency, time to first token, output tokens, tokens per second) but include network time, and have no load time, cold start or memory footprint. These are labelled, not faked, and speed comparisons across local and cloud models carry a clear note.
- **Be explicit about data leaving the machine.** Registering a provider requires acknowledging that prompts and model outputs used in evaluations are sent to it, and runs that use a provider (as contestant or judge) show which providers receive data.
- **Parameters that a provider cannot honour** (for example a seed, or temperature for some reasoning models) are recorded per request as ignored rather than silently dropped.
- **Non-goals:** storing or encrypting keys, prices or spend tracking, providers other than OpenAI and Anthropic (beyond an OpenAI-compatible base URL), fine-tuning, parallel/batched requests, provider-side batch APIs, and changing how correctness or judged scores are computed.

## Capabilities

### New Capabilities

- `model-providers`: Registering enterprise providers by API-key environment variable, registering and enabling their models (typed or fetched), key availability status, connection testing, data-sharing acknowledgment, and the Providers screen.
- `enterprise-model-execution`: How runs and judging call OpenAI and Anthropic models: normalized streaming and metrics, parameter mapping and recording, retries and failure isolation per provider, structured judge output, and key redaction.

### Modified Capabilities

- `model-discovery`: The model list becomes a unified list of installed Ollama models and registered enterprise models; Ollama being unreachable no longer blocks runs that use only enterprise models.
- `evaluation-runs`: Runs may include enterprise models; run configuration records provider and model version and applicability of parameters; failure isolation covers provider errors.
- `performance-metrics`: Metrics for cloud requests come from provider usage and client timing; cold start, warm-up and memory footprint do not apply; network latency is disclosed.
- `response-scoring`: The judge for judge-based scoring may be any available local or enterprise model.
- `results-dashboard`: Run setup groups local and cloud models and shows key availability; results and export label cloud models and their providers.
- `cross-model-judging`: Cross-model judging spans local and enterprise models, unloading applies only to local judges, and enterprise judges receiving other models' answers is disclosed.

## Impact

- **Backend:** a model-backend abstraction in front of the Ollama client with OpenAI and Anthropic adapters (HTTP via the existing `httpx` dependency, no vendor SDK); a router that resolves a model reference to its backend; provider and registered-model tables and a snapshot extension (Alembic migration); new `/api/providers` endpoints and a unified `/api/models`; runner, judge and summary adjustments for capabilities that only some backends have (unload, warm-up, footprint).
- **Frontend:** a Providers page, provider/cloud badges and grouping in the model picker, judge selection over all available models, data-disclosure banner, cloud-latency notes in results, and provider columns in export.
- **Configuration and secrets:** API keys live only in the environment of the process that starts the app; documented in the README. Keys must never appear in the database, API responses, logs, error messages, exports or test fixtures.
- **Model naming and compatibility:** existing bare model names remain Ollama models and existing runs, exports and API callers are unchanged; enterprise models use a distinct reference form that cannot collide with an Ollama name.
- **External dependency and cost:** calls to OpenAI and Anthropic are billable and rate-limited and send evaluation content to a third party; the UI shows the request count up front. CI and tests use fake provider servers and need no keys.
- **Docs and tests:** README (privacy statement, providers, metrics caveats) and unit, contract, API, end-to-end and UI tests with fake OpenAI/Anthropic servers; a live smoke test runs only when keys are present.
