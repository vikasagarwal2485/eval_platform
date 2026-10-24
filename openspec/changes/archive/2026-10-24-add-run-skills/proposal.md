# Proposal

## Why

The platform already compares models on quality, latency and tokens/sec (performance-metrics,
response-scoring) across suites of classification/reasoning/generation cases, but every model is
always evaluated "bare" - there is no way to see how giving a model extra, structured guidance
(a *skill*: written instructions, not executable code or a callable tool) changes its measured
performance. The user wants exactly this comparison - the same benchmark methodology this platform
already runs, with one new, optional ingredient: attach one or more skills to a run and see how
each model's quality/latency/tokens-per-sec shifts, by comparing that run against a bare one using
the comparison tooling that already exists.

## What Changes

- **New capability: a Skills Registry.** A skill is a named, Markdown-authored bundle (a short
  description plus free-form instructions - no executable code, no tool/function schema) that can
  be written directly in the UI or uploaded from a file on the user's own machine, mirroring how
  Suites/Providers are already registered, listed, edited and deleted.
- **Benchmark runs can attach one or more skills.** `RunConfig` gains an optional list of skill
  ids. When set, every model's request for every case in that run has the attached skill(s)'
  instructions injected into its prompt, through the existing prompt-building path
  (`build_prompt`/`build_messages`) - no new execution model, no tool-calling, no multi-round-trip
  conversation, and no new axis inside a single run (every model/case/repeat in one run sees the
  same attached skills, exactly as every model/case/repeat already sees the same judge
  configuration today).
- **Comparison reuses what already exists.** A skill-equipped run is scored exactly like any other
  run (the existing judge/reference scoring, unchanged) and compared against a bare run using the
  existing run-vs-run comparison dashboard - no new leaderboard dimension, no skill-specific
  scoring criterion, no new UI beyond picking skills at run-setup time and seeing them recorded in
  that run's stored configuration (exactly like `judge_model` already is).

## Capabilities

### New Capabilities
- `skills-registry`: register, list, edit, delete, and import (paste or upload a file) a named,
  Markdown-authored skill - a description plus instructions, with no executable content.

### Modified Capabilities
- `evaluation-runs`: a run's configuration can optionally name one or more registered skills,
  whose instructions are then injected into every request's prompt for that run.

## Impact

- Backend: a new `Skill` table/registry (model, repo functions, `/api/skills` CRUD + import
  endpoints) mirroring the existing `Suite` registry; `RunConfig` gains a `skill_ids` field;
  `build_prompt`/`build_messages` (or a thin wrapper around them) gain a skill-injection step;
  the run record's stored configuration includes which skills were attached, the same way it
  already stores `judge_model`.
- Frontend: a new Skills page (list/create/edit/delete, a Markdown textarea for hand-authoring, and
  a real file picker for uploading a `.md` file from disk) mirroring the existing Suites/Providers
  pages; Run Evaluation setup gains a skill-selection control next to the existing judge-mode
  control.
- Explicitly out of scope for this phase (confirmed during exploration): executable or tool-backed
  skills (MCP-style function calling), per-case or per-model skill attachment (this phase is
  run-level only), and any new skill-specific scoring dimension - quality is judged exactly as it
  already is today, and a skill-equipped run is compared against a bare run with the platform's
  existing run-vs-run comparison tooling, not a new one.
