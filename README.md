# LLM Eval Platform

Compare **accuracy, reasoning and speed** of the models installed in your local [Ollama](https://ollama.com).
Pick several models in a web UI, send them classification, reasoning and text-generation prompts (your own or a
reusable suite), and get a leaderboard, charts, side-by-side outputs and exportable results. Everything runs on
your machine; nothing leaves it.

```
Browser (React)  <--REST + SSE-->  FastAPI  --HTTP-->  Ollama (localhost:11434)
                                     |
                                  SQLite (runs, results, scores)
```

## Prerequisites

| Need | Check |
|---|---|
| [Ollama](https://ollama.com) running | `ollama list` (and `curl localhost:11434/api/version`) |
| At least one model, ideally two or more | `ollama pull qwen3:8b`, `ollama pull gemma3:4b`, ... |
| Python 3.11+ | `python3 --version` |
| Node 18+ and npm | `node --version` |

A single model works (you get absolute scores); comparison views need two or more.

## Quick start

```bash
make setup      # backend venv + dependencies, frontend dependencies
make run        # builds the UI and serves everything at http://127.0.0.1:8000
```

Open <http://127.0.0.1:8000>. For development with hot reload use `make dev` (UI on :5173, API on :8000).

## Using it

1. **Run setup** - tick the models to compare, then choose what to send:
   - a **test suite** (the built-in *Starter suite* has 6 classification, 6 reasoning and 3 generation cases), or
   - an **ad-hoc prompt**: type text, pick a category, optionally give the expected answer. You can save it into a suite.
2. Choose how generated text is **judged** if you have generation cases (see *Cross-model judging* and *Limitations*):
   no judge, a single judge model, or cross-model judging. Adjust settings if you like, and start.
3. **Live run** shows progress, the model currently answering (streamed) and each result as it lands. You can cancel;
   finished results are kept.
4. **Results** shows the leaderboard (sortable; adjust category weights and the composite re-ranks instantly), charts,
   classification confusion matrices and, under **Cases**, every model's output side by side with scores, the judge's
   reasons, reasoning traces and timings. Export CSV/JSON, re-score with another judge, or re-run.
5. **History** lists past runs; select two to see what changed (e.g. before/after a new quantization).

## How scoring works

| Category | How it is scored |
|---|---|
| **Classification** | The prompt lists the allowed labels. The answer is normalized and matched to a label; correct = 1, wrong = 0. Unparseable answers (no valid label) count as wrong but are tallied separately. Accuracy, per-label precision/recall/F1 and a confusion matrix are reported. |
| **Reasoning** | The prompt asks for a final line `Final answer: ...`. That answer is extracted (with documented fallbacks) and compared as text, or as a number within a tolerance. Correctness uses the *final answer only*, never the reasoning trace. |
| **Generation** | A **judge** scores each answer 1-5 per rubric criterion (with a one-line reason), normalized to 0-1 (`(mean-1)/4`). The judge is one model you pick, or - with cross-model judging - the other evaluated models. Deterministic checks (max/min words, required/forbidden keywords) are reported alongside as pass/fail. |
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
- Only Ollama is supported; there is no authentication, so keep it bound to localhost.

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
| `EVAL_MAX_RETRIES` | `2` | Retries for dropped connections before a run is marked failed |
| `PORT` / `HOST` | `8000` / `127.0.0.1` | For `make run` |

## Development

```bash
make dev        # hot reload
make test       # pytest (backend) + vitest (frontend)
make lint       # ruff, eslint, tsc, prettier
make format
```

`backend/app`: `ollama/` (the only code that talks to Ollama), `core/` (runner, scorers, metrics, summaries),
`api/` (FastAPI routes), `models.py` + `alembic/` (SQLite schema and migrations).
`frontend/src`: `pages/`, `components/` (incl. hand-rolled SVG `charts/`), `api/` (typed client, query hooks, SSE hook).
Design notes and specs live in `openspec/changes/add-llm-eval-platform/`.

The backend tests need no Ollama: they use an in-process fake and, for the end-to-end test, a fake Ollama HTTP server
that replays a recorded stream (`backend/tests/fixtures`).

## Troubleshooting

- **"Ollama unreachable"** - start it (`ollama serve`) or set `OLLAMA_BASE_URL`. The UI disables starting runs meanwhile.
- **A model is missing from the list** - press *Refresh* on Run setup after `ollama pull`.
- **Reasoning answers marked `unparseable` / truncated** - raise *Max output tokens* (thinking models can spend thousands
  of tokens before answering).
- **`npm install` fails with `EACCES` on `~/.npm/_cacache`** - an old npm bug left root-owned files in your npm cache.
  Fix it with `sudo chown -R "$(id -u):$(id -g)" ~/.npm`, or install with a private cache:
  `npm install --cache /tmp/npm-cache` (or `npm_config_cache=/tmp/npm-cache make setup`).
