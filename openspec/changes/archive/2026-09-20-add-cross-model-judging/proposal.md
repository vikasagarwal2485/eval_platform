# Proposal

## Why

Generated text is scored by an LLM judge, and models favour their own writing. Today the judge is a single model chosen by the user; if it is also one of the evaluated models, the platform only *labels* those scores "self-judged". A user with just two local models cannot avoid this: whichever model they pick as judge is also a contestant, so one contestant always grades itself. **Cross-model judging** removes self-judging by construction: each answer is judged only by models other than the one that wrote it, so two local models can evaluate each other without needing a third.

## What Changes

- Run setup gains a **judging mode** choice with three options: *No judge*, *Single judge model* (today's behaviour, unchanged), and **Cross-model judging** (each model's answers are judged by the other selected models).
- In cross-model mode a model never judges its own output. An answer is judged by every *other* evaluated model; with two models this means A is judged by B and B by A. With three or more, each answer is scored by all other models and the score is their mean, with every judge's individual score kept.
- Cross-model judging needs at least two selected models. With fewer, the option is disabled with an explanation.
- When a single judge that is also an evaluated model is chosen, the existing self-judging warning gains a one-click way to switch to cross-model judging.
- The same mode is available when **re-scoring** a finished run, and applies to the optional reasoning-quality judging as well as generation judging.
- Results show how each score was judged: a "cross-judged" indicator on generation scores (never "self-judged"), and a per-judge breakdown (which model gave which score and reasons) in the case drill-down and the exported data.
- Scoring attempts record the judging mode and the judges used, so re-scoring with a different mode keeps earlier attempts readable and comparable.
- The UI explains the trade-off: different judges can have different strictness, so scores produced by different judges are not perfectly like-for-like. Per-judge scores are shown so this can be inspected.
- **Non-goals:** using non-Ollama or remote judges; automatic calibration or normalization of judge strictness; multi-round debate or adjudication; changing how classification and reasoning correctness are scored; any change to performance measurements.

## Capabilities

### New Capabilities

- `cross-model-judging`: Selecting a judging mode in Run setup (none / single / cross-model), the rule that a model never judges its own answers in cross-model mode, how multiple judges' scores are combined and reported, availability when re-scoring, and how the mode and judges are recorded and shown in results and exports.

### Modified Capabilities

<!-- None at the spec level: the project has no archived main specs yet. This capability extends the judge-based scoring, run-configuration and dashboard requirements introduced by the in-progress change `add-llm-eval-platform`. -->

## Impact

- **Depends on** `add-llm-eval-platform` (53 of 54 tasks done; its specs are not archived yet). Archiving it first lets the requirements here be reconciled into its `response-scoring`, `evaluation-runs` and `results-dashboard` specs.
- **Backend:** run/rescore request schemas gain a judging mode; run and scoring-attempt records store it (new SQLite migration); the judge stage in the scoring service and run worker changes to plan judge-by-answer pairs; summary, results and export payloads expose mode and per-judge scores.
- **Frontend:** the settings panel in Run setup, the leaderboard and case drill-down indicators, and the re-score control on the Results page.
- **Runtime cost:** cross-model judging makes up to (models - 1) judge calls per judged answer and loads each judge model once per run (work is grouped by judge model to limit model swaps). Judging still runs after all generation, so measured speed is unaffected.
- **Docs and tests:** README scoring/limitations sections; unit tests for pair planning and score combination, API and worker tests with the fake Ollama, and UI tests for the option, its disabled state and the new indicators.
- **Compatibility:** existing runs and the single-judge flow are unchanged; older runs read as "single" or "none" mode.
