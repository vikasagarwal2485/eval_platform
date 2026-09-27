# LLM Eval Platform

Compare **accuracy, reasoning and speed** of the models installed in your local [Ollama](https://ollama.com), *and*
of models hosted by OpenAI or Anthropic. Pick several models in a web UI, send them classification, reasoning and
text-generation prompts (your own or a reusable suite), and get a leaderboard, charts, side-by-side outputs and
exportable results.

**Data sharing:** local (Ollama) evaluations never leave your machine. If you register an enterprise provider,
prompts and model outputs used with its models - including other models' answers when it judges them - are sent to
that provider. See [Enterprise model providers](#enterprise-model-providers) below.

```
                                     +-->  Ollama (localhost:11434)
Browser (React)  <--REST + SSE-->  FastAPI  --HTTP-->  OpenAI API
                                     |          `-->  Anthropic API
                                  SQLite (runs, results, scores)
```

## Prerequisites

| Need | Check |
|---|---|
| [Ollama](https://ollama.com) running, for local models | `ollama list` (and `curl localhost:11434/api/version`) |
| At least one model, ideally two or more | `ollama pull qwen3:8b`, `ollama pull gemma3:4b`, ... |
| *or* an OpenAI / Anthropic API key, for enterprise models | see [Enterprise model providers](#enterprise-model-providers) |
| Python 3.11+ | `python3 --version` |
| Node 18+ and npm | `node --version` |

A single model works (you get absolute scores); comparison views need two or more. Ollama and an enterprise provider
are both optional individually - use Ollama alone, a provider alone (Ollama can be unreachable), or both together.

## Quick start

```bash
make setup      # backend venv + dependencies, frontend dependencies
make run        # builds the UI and serves everything at http://127.0.0.1:8000
```

Open <http://127.0.0.1:8000>. For development with hot reload use `make dev` (UI on :5173, API on :8000).

## Using it

1. **Run setup** - tick the models to compare, grouped as *Local (Ollama)* and one group per registered provider (an
   enterprise model with no key available is shown disabled, naming the missing variable) - then choose what to send:
   - a **test suite** (the built-in *Starter suite* has 6 classification, 6 reasoning and 3 generation cases), or
   - an **ad-hoc prompt**: type text, pick a category, optionally give the expected answer. You can save it into a suite.
2. Choose how generated text is **judged** if you have generation cases (see *Cross-model judging* and *Limitations*):
   no judge, a single judge model (any available local or enterprise model), or cross-model judging. If the run uses an
   enterprise model as contestant or judge, a notice lists which provider(s) will receive data before you can start.
   Adjust settings if you like, and start.
3. **Live run** shows progress, the model currently answering (streamed) and each result as it lands. You can cancel;
   finished results are kept.
4. **Results** shows the leaderboard (sortable; adjust category weights and the composite re-ranks instantly; cloud
   models carry a badge naming their provider), charts (with a note whenever local and cloud speeds are compared),
   classification confusion matrices and, under **Cases**, every model's output side by side with scores, the judge's
   reasons, reasoning traces, timings and, for enterprise models, the model version that answered and any run setting
   it did not honour. Export CSV/JSON, re-score with another judge, or re-run.
5. **History** lists past runs; select two to see what changed (e.g. before/after a new quantization).
6. **Providers** - register OpenAI or Anthropic and their models; see below.

## Enterprise model providers

Register OpenAI or Anthropic on the **Providers** page so their models can be evaluated next to your local ones, or
used as a judge (including a neutral hosted judge for two local models that would otherwise have to judge each other).

- **The application never handles the key itself.** You register a provider with the *name of the environment
  variable* that holds its API key (e.g. `OPENAI_API_KEY`) - there is no field anywhere that accepts a key value. The
  variable is read only at the moment a call is made; it is never written to the database, an API response, an export,
  a log, or an error message.
- **Export the variable before starting the application, and restart after changing it.** A running process cannot
  see a variable exported after it started, so the UI explains this and names the missing variable when a key is not
  found:
  ```bash
  export OPENAI_API_KEY=sk-...
  export ANTHROPIC_API_KEY=sk-ant-...
  make run
  ```
- **Registering a provider requires acknowledging data sharing**: prompts and model outputs used in evaluations -
  including other models' answers when this provider judges them - are sent to it. Run setup shows the same notice,
  naming every provider that will receive data, before a run using one can start.
- Add a provider's models by typing an id or fetching its list (a failed fetch never blocks typing an id by hand); flag
  a model as a **reasoning model** if it supports one, and enable/disable models without losing history.
- **Test connection** performs one lightweight authenticated request and reports *working*, *key not set*,
  *authentication failed*, *rate limited*, or *unreachable* - never the key itself.
- Enterprise models are referenced as `@provider/model` (e.g. `@openai-main/gpt-4o`) everywhere - Run setup, results,
  exports - so they can never be confused with an Ollama model name.
- **Failure isolation:** an authentication failure or an outage after retries stops only that provider's remaining
  requests in the run (recorded as errors); other providers and local models continue, and the run still completes.
  An unreachable *Ollama*, by contrast, still fails the whole run, as it did before enterprise providers existed.
- Removing a provider or a model does not touch past runs; they keep their own results and display the model as
  removed.

## How scoring works

| Category | How it is scored |
|---|---|
| **Classification** | The prompt lists the allowed labels. The answer is normalized and matched to a label; correct = 1, wrong = 0. Unparseable answers (no valid label) count as wrong but are tallied separately. Accuracy, per-label precision/recall/F1 and a confusion matrix are reported. |
| **Reasoning** | The prompt asks for a final line `Final answer: ...`. That answer is extracted (with documented fallbacks) and compared as text, or as a number within a tolerance. Correctness uses the *final answer only*, never the reasoning trace. |
| **Generation** | A **judge** scores each answer 1-5 per rubric criterion (with a one-line reason), normalized to 0-1 (`(mean-1)/4`). The judge is one model you pick (local or enterprise, evaluated or not), or - with cross-model judging - the other evaluated models, local and enterprise alike. Deterministic checks (max/min words, required/forbidden keywords) are reported alongside as pass/fail. |
| **Composite** | Weighted mean of the category scores (equal weights by default; adjustable in the UI). Categories with no scored cases are left out and the remaining weights are renormalized. Unscored cases are excluded from means; failed requests count as 0. |

The instruction suffix added to classification and reasoning prompts is versioned (`v1`) and visible in the case
drill-down, so you can always see exactly what the model was sent.

Thinking models (e.g. `qwen3`, `gemma4`) return a reasoning trace; it is stored separately, collapsed in the UI, and
included in latency and token figures (it is real time you wait for).

### Cross-model judging

Models tend to favour their own writing, so a judge that is also one of the evaluated models is flagged
*self-judged*. With only two local models you cannot avoid that with a single judge. **Cross-model judging** removes it
by construction: each answer is judged only by the *other* selected models, never by its author.

| Models selected | Who judges what |
|---|---|
| 2 | A's answers are judged by B, and B's answers by A |
| 3 or more | each answer is judged by all the other models; the score is their mean |

- Choose **Cross-model judging** in *Run setup* (it needs at least two models) or when **re-scoring** a finished run. No
  separate judge model is needed. If you pick a single judge that is also a contestant, the warning offers a one-click
  switch.
- It also applies to the optional *reasoning-quality* judging.
- It works across **any mix of local and enterprise models**: an enterprise model judges the local ones and is judged
  by them in turn, exactly like local-only cross-model judging. Run setup states which provider(s) will receive other
  models' answers this way.
- Each judge's own score, criterion scores and reasons are kept: see the case drill-down, the *Judge strictness* table
  (each judge's average score) and the `judges` column of the CSV export. If one judge fails, the others still count; if all
  fail, the answer is shown as an error and left out of the category mean.
- **Cost:** up to *(models - 1)* judgements per answer, run judge by judge after all generation (so speed figures are
  unaffected), unloading each judge before the next. The setup screen shows an estimate.
- **Fairness caveat:** different models grade different answers, and judges differ in strictness (a harsh judge lowers the
  score of whoever it judges). Treat cross-judged scores as informative, not perfectly like-for-like: check the judge
  strictness table, and use **Re-score** with a single neutral judge to compare. Earlier scoring attempts always stay
  available.

## How performance is measured

Per request: total latency, **time to first token** (measured client-side; Ollama does not report it), time to the first
*answer* token (after thinking), model load time, prompt/output token counts, tokens per second
(`eval_count / eval_duration`) and the model's memory footprint from `/api/ps`.

- Requests run **one at a time, grouped by model**, and each model is **warmed up** first, so load time is not mixed into
  speed numbers. Load time is reported separately; requests that still include a load are flagged *cold* and excluded
  from speed statistics unless you tick "Include cold-start requests".
- Speed is summarized as median, p95, min and max over warm requests. Use **Repeats** to reduce noise.
- Defaults are reproducible: temperature 0, fixed seed, explicit context size and output limit; all are recorded with
  the model digest, quantization and Ollama version.
- Speed is shown next to output token counts: a verbose model can be slower overall while generating faster.

**Enterprise models are measured differently, and the UI says so wherever local and cloud models are compared:**

- Latency and time to first token are measured by the client and **include network transfer and the provider's own
  queueing** - they are not directly comparable to a local model's numbers. Token counts come from the provider's own
  usage report.
- There is no load phase: enterprise models get **no warm-up request** (every request is billable), are **never
  flagged cold**, and report **no memory footprint** (shown as not applicable, not zero).
- **Reproducibility varies by provider.** A run's temperature and seed are applied where the provider accepts them;
  where they are not (e.g. Anthropic accepts no seed; some models reject a temperature setting), the request omits
  the setting and the result records that it was not applied - visible per result in the case drill-down. Even an
  accepted seed is typically *best-effort*, not a strict guarantee, unlike Ollama's deterministic sampling at
  temperature 0.

## Limitations (please read)

- **LLM judges are biased and noisy.** Small local models are imperfect judges and favour their own writing. If a single
  judge is also an evaluated model, its scores are labelled *self-judged*; **cross-model judging** avoids that, at the price
  of judges with different strictness (see above). Prefer a different (ideally larger) judge when you have one, and use
  **Re-score** to compare judges. Without a judge, generation cases are shown as *unscored* (not as 0).
- **The starter suite is small.** With a handful of cases per category, differences of one case swing a score by many
  points. The UI shows how many cases stand behind every score. Add your own cases or import a bigger suite.
- **Results are specific to your machine** (chip, memory pressure, thermals, Ollama version). Compare runs made on the
  same machine under similar load.
- **Answer extraction is heuristic.** Models that ignore the "Final answer:" or single-label instruction may be scored
  `unparseable`; those are counted, visible, and never silently dropped.
- Models are evaluated **sequentially**, so large suites with thinking models can take a while.
- **Enterprise providers cost money and are rate-limited.** Every request to a registered provider is billable; Run
  setup shows an estimated request count, split by destination, before you start. Rate limits and transient failures
  are retried with backoff; a sustained outage or an authentication failure stops only that provider's remaining
  requests in the run (see *Enterprise model providers*), not the whole run.
- **A key exported after the application started is invisible to it.** Restart after changing a provider's key.
- Only OpenAI and Anthropic are supported (or an OpenAI-compatible endpoint via a custom base URL); there is no
  authentication on the web UI itself, so keep it bound to localhost or otherwise restrict access - this matters more
  once enterprise provider keys are in play.

## Suite file format

Suites import/export as JSON or YAML:

```yaml
name: My suite
description: optional
cases:
  - category: classification          # classification | reasoning | generation
    prompt: "Sentiment of: I love it"
    labels: [positive, negative]      # >= 2 allowed labels
    expected: positive                # optional; must be one of the labels
  - category: reasoning
    prompt: "What is 15% of 240?"
    comparison: numeric               # or text
    tolerance: 0                      # absolute, numeric only
    expected: "36"
  - category: generation
    prompt: "Write a two-sentence product blurb for a water bottle."
    constraints: {max_words: 60, required_keywords: [cold]}
    rubric:
      - {name: Relevance, description: Describes the product}
      - {name: Fluency, description: Natural, grammatical}
```

## Configuration

| Variable | Default | |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Where Ollama listens |
| `EVAL_DB_PATH` | `data/eval_platform.db` | SQLite file (created and migrated on start) |
| `EVAL_REQUEST_TIMEOUT_S` | `300` | Per-request timeout (can be overridden per run) |
| `EVAL_MAX_RETRIES` | `2` | Retries for a dropped Ollama connection before a run is marked failed |
| `EVAL_RETRY_BACKOFF_S` | `1.0` | Backoff between those Ollama retries |
| `EVAL_PROVIDER_MAX_RETRIES` | `4` | Retries for a rate-limited or failing enterprise-provider request, before that request errors |
| `EVAL_PROVIDER_BACKOFF_S` | `1.0` | Starting backoff for provider retries; doubles each attempt, capped at 30 s (or the provider's own `Retry-After`, if given) |
| `PORT` / `HOST` | `8000` / `127.0.0.1` | For `make run` |

**Provider API keys are not configured here.** Register a provider on the Providers page by the *name* of the
environment variable that holds its key (commonly `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`), then export that variable
yourself in the environment you start the application from - see *Enterprise model providers* above.

## Development

```bash
make dev        # hot reload
make test       # pytest (backend) + vitest (frontend)
make lint       # ruff, eslint, tsc, prettier
make format
```

`backend/app`: `ollama/` (the only code that talks to Ollama), `providers/` (the enterprise backend abstraction,
model references, secrets/redaction, the OpenAI and Anthropic adapters, and the router that picks a backend per
model), `core/` (runner, scorers, metrics, summaries), `api/` (FastAPI routes), `models.py` + `alembic/` (SQLite
schema and migrations).
`frontend/src`: `pages/`, `components/` (incl. hand-rolled SVG `charts/`), `api/` (typed client, query hooks, SSE hook).
Design notes and specs live under `openspec/`: the finished proposals are archived in `openspec/changes/archive/`,
the current one in `openspec/changes/add-enterprise-model-providers/`, and the synced capability specs in
`openspec/specs/`.

The backend tests need no Ollama and no real provider key: they use in-process fakes and, for the end-to-end tests,
fake HTTP servers that speak the real wire protocols - Ollama (`backend/tests/fake_ollama_server.py`, replaying a
recorded stream from `backend/tests/fixtures`) and OpenAI/Anthropic (`backend/tests/fake_providers.py`). An opt-in
live smoke test against the *real* OpenAI and Anthropic APIs (`backend/tests/test_live_smoke_enterprise.py`) is
skipped unless you export a real `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` yourself; it never runs in CI.

## Troubleshooting

- **"Ollama unreachable"** - start it (`ollama serve`) or set `OLLAMA_BASE_URL`. Local models are disabled meanwhile;
  enterprise models keep working.
- **A model is missing from the list** - press *Refresh* on Run setup after `ollama pull`.
- **Reasoning answers marked `unparseable` / truncated** - raise *Max output tokens* (thinking models can spend thousands
  of tokens before answering).
- **A provider shows "key not set"**, or a model is greyed out naming a missing variable - export that variable in the
  shell you start the application from, then **restart** the application. Exporting it in a different terminal, or
  after the process already started, has no effect on the running process.
- **"Authentication failed" when testing a provider or starting a run** - check the *value* of the variable named on
  the provider (typos, an expired key, extra whitespace); the platform never displays the key to compare it directly.
- **Fetching a provider's model list fails** - the error is shown (rate limited, unreachable, or an invalid key), and
  you can still add a model by typing its id directly; nothing blocks that fallback.
- **`npm install` fails with `EACCES` on `~/.npm/_cacache`** - an old npm bug left root-owned files in your npm cache.
  Fix it with `sudo chown -R "$(id -u):$(id -g)" ~/.npm`, or install with a private cache:
  `npm install --cache /tmp/npm-cache` (or `npm_config_cache=/tmp/npm-cache make setup`).
