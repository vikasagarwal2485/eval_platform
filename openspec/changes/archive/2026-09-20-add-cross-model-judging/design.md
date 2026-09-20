# Design

## Context

Judge-based scoring exists in `add-llm-eval-platform` and is built around **one** `judge_model`. Observed in the current code:

- `RunCreate.judge_model` / `Run.judge_model` / `ScoringAttempt.judge_model` hold a single name. `RescoreBody` and the `rescore` job carry the same single field.
- `scoring/service.py::judge_run` loops over every answer to judge, calls `run_judge` with that one model, and writes **one** `Score(kind="judge")` row per result. `detail.self_judged` is set when the judge equals the author; the summary turns that into a leaderboard `self_judged` flag.
- The run worker (`runner.py`) runs the judge stage after all generation, so judge traffic never affects measured latency, and it disables thinking for thinking-capable judges.
- Aggregation (`aggregate.py`, `summary.py`) reads exactly one primary score per result (`judge` for generation), so any change that keeps *one aggregate row per result* leaves aggregation, composites, export and compare untouched.
- The UI keeps the judge in `RunSetupPage`/`ConfigPanel` state (`judge`), sends `judge_model`, and shows a self-judging warning.
- Two models are the common case here (`qwen3:8b`, `gemma4:e4b`), and a live run showed the self-judge flag firing for one of them.

The in-progress `add-llm-eval-platform` change has not been archived, so there are no main specs to modify; this change adds one new capability (`cross-model-judging`). See `proposal.md` for motivation and scope, and `specs/` for behaviour.

## Goals / Non-Goals

**Goals:**
- A judging mode (none / single / cross-model) chosen in Run setup and when re-scoring.
- In cross-model mode no model ever judges its own answer, with two models as the minimum.
- Keep the existing "one score per answer" contract so leaderboard, composite, compare and export code keep working.
- Keep every individual judgement so judge strictness can be inspected and a cancelled judging stage loses nothing.
- Existing runs, the single-judge flow and their tests keep working unchanged.

**Non-Goals:**
- Calibrating or normalizing judges' strictness, weighting judges, or picking a "best" judge.
- Non-Ollama judges, debates, or a cap on the number of judges (see Open Questions).
- Changing classification or reasoning correctness scoring, or any performance measurement.

## Decisions

### D1. `judge_mode` is a first-class field next to `judge_model`

Add `judge_mode: "none" | "single" | "cross_model"` to `RunCreate`, `RescoreBody`, `Run` and `ScoringAttempt`. It sits beside `judge_model` (not inside `RunConfig`) because the judge is already run-level, not a generation setting. `RunConfig.judge_reasoning` stays where it is and applies to whichever mode is active.

Validation (server, single place used by create, re-run and re-score):

| Request | Result |
|---|---|
| `judge_mode` omitted, `judge_model` null | `none` |
| `judge_mode` omitted, `judge_model` set | `single` (keeps old clients and tests working) |
| `single` without `judge_model` | 422 |
| `none` with `judge_model` | 422 |
| `cross_model` with `judge_model` | 422 (contradictory) |
| `cross_model` with < 2 distinct models | 422 |
| `judge_reasoning` with `none` | ignored, as today |

*Alternative:* infer cross-model from "judge is empty and reasoning/generation present". Rejected: implicit modes are confusing and cannot express "no judge".

### D2. Plan judgements as a pure function

`plan_judgements(mode, judge_model, authors, judge_targets) -> list[JudgeTask]` where a `JudgeTask` is `(result_id, judge_model, kind)`:

- `single`: one task per target answer with `judge_model`.
- `cross_model`: one task per (answer, judge) for every evaluated model that is not the answer's author. Authors and judges are compared by **model snapshot id**, not display name, so two builds of the same tag cannot judge each other by accident.

It is pure, so the "never self-judged" invariant and the counts (`answers x (models - 1)`) are unit-testable without Ollama. The judge stage executes the plan grouped by judge.

### D3. Store each judgement, then one aggregate row per result

New table `judgement(id, attempt_id, result_id, kind, judge_model, value, outcome, detail)` holds every individual judgement (`judged` / `error`, criteria, reasons, judge call metrics). The existing `Score(kind="judge"|"judge_reasoning")` row remains the **one aggregate** per result and is what summary, composite, export and compare read:

- `value` = mean of the successful judgements' normalized scores; `outcome` = `judged` if at least one succeeded, else `error`.
- `detail.mode`, `detail.judgements` (the individual ones, denormalized for the API), `detail.judges_used`, and `self_judged` (always false in cross mode).
- For single-judge mode the aggregate keeps today's shape (`detail.criteria` at top level), so existing consumers and tests are unaffected; `detail.judgements` is added alongside it.

Judgements are written as they complete; the aggregate rows are written when a judge group finishes and again in a `finally` block for anything judged before a cancel. This gives "judgements already made are kept" without holding state in memory.

*Alternatives:* (a) store only the aggregate with judgements inside JSON: loses partial progress on cancel and makes per-judge statistics awkward. (b) one `Score` row per judge and aggregate at read time: changes every consumer of "primary score". Rejected for blast radius.

### D4. Combine judges with a plain mean

The answer's score is the arithmetic mean of successful judges' normalized scores (each already `(mean of 1-5 criteria - 1) / 4`). With two models there is exactly one judge per answer, so mean = that judge's score. Equal weights keep the rule explainable; median would be identical for one or two judges and only matters for larger sets.

### D5. Execute grouped by judge model

The judge stage iterates judge models in the run's model order and, inside each, judges every assigned answer, then unloads that judge before the next (reusing the existing quiet unload). This bounds model loads to one per judge instead of thrashing between models per answer, which matters for 8 GB-class local models. Judge calls keep today's options (temperature 0, fixed seed, structured JSON output, one retry, thinking disabled for thinking-capable judges, connection loss aborts the stage). The stage still runs only after all generation, so speed figures are untouched, and it checks the cancel flag between judgements.

### D6. Expose per-judge information without new aggregate shapes

- `/summary`: add `judging: { mode, judges: [{ model, judged, mean_score, errors }] }` for the selected attempt, computed from `judgement` rows, plus `judge_mode` on each entry of `attempts`. Leaderboard rows keep `self_judged` (now naturally false for cross mode) and gain `judges_per_answer`.
- `/results`: aggregate score objects already carry `detail.judgements`.
- Export: CSV gains `judge_mode` and `judges` (`model=score;model=score`); JSON export includes the judgements.
- Re-run copies `judge_mode` and `judge_model`.

### D7. Re-score mode handling

`RescoreBody` gains `judge_mode`. The attempt row records mode and the single judge (if any). For cross-model re-scoring the judges are the run's frozen model snapshots, so a judge that is no longer installed simply produces `error` judgements (Ollama returns a model-not-found error, which `run_judge` already turns into an error outcome) while the others continue. Single-judge re-scoring keeps its current up-front "must be installed" check.

### D8. UI

- **Run setup / `ConfigPanel`**: replace the single judge select with a "Judging" radio group (No judge / Single judge model / Cross-model). The judge select appears only for *Single*. *Cross-model* is disabled with a hint when fewer than two models are selected, and the page resets the mode to *No judge* (with a message) if the selection later drops below two. A note states that models never grade themselves and that judge strictness may differ. An estimate ("about N judgements across M judge models") is shown, so the extra cost is visible.
- **Self-judging warning** (single mode, judge among evaluated models) gains a "Use cross-model judging instead" button (enabled with 2+ models).
- **Results**: the leaderboard shows a "cross-judged - n judges" badge instead of "self-judged"; a "Judge strictness" card lists each judge's average score and error count; the drill-down lists every judge's score, criteria and reasons; the Re-score control gains the same mode choice; the attempt selector labels each attempt with its mode.
- The mode drives payloads only through `judge_mode`/`judge_model`; the client keeps sending `judge_model` alone for nothing else, so the API stays backward compatible.

### D9. Migration

Alembic revision `0002`: add `judge_mode` (NOT NULL, default `none`) to `run` and `scoring_attempt`; backfill `single` where `judge_model` is not null; create `judgement`. All additive; SQLite batch mode is already configured. Downgrade drops the table and columns. Existing scores stay valid because their aggregate rows are unchanged.

## Risks / Trade-offs

- **Judges differ in strictness, so cross-judged scores are not perfectly like-for-like** (A judged by B vs B judged by A; a harsh B depresses A's score). → Show each judge's average score; explain the caveat in the UI; with 3+ models each answer is scored by several judges, which dilutes any one judge; keep earlier attempts so the same run can be re-scored with a single neutral judge and compared. Calibration is out of scope.
- **Weak local models are noisy judges, and a much weaker judge may misgrade a stronger model.** → Same visibility; structured output and the one retry stay; errors are recorded, not hidden.
- **Cost grows with the number of models** (up to `models - 1` judgements per answer). → Show the estimate up front; group by judge to avoid reloading; judging never blocks generation timing. An optional limit on judges per answer is deferred.
- **Cancellation or a crash mid-stage** could leave answers half-judged. → Persist each judgement immediately and rebuild aggregates in `finally`; answers with no successful judgement read as `error`/unscored, never as 0.
- **A judge model that fails to load (memory)** would fail all its judgements. → Recorded as errors per judgement; other judges still score; the UI shows the judge's error count.
- **Compatibility drift**: adding `judge_mode` could break older callers. → Omitted mode is inferred from `judge_model` (D1), aggregate score shape is preserved (D3), migration backfills.
- **Name-based self-judge detection was fragile** (same tag, different digest). → Cross-model planning uses snapshot ids (D2).

## Migration Plan

1. Ship the Alembic `0002` migration (runs automatically at start-up); no manual step. 2. Deploy backend and frontend together; the old UI keeps working against the new API because `judge_mode` is optional. 3. Roll back by downgrading `0002` (drops `judgement` and the two columns); runs made in cross mode would then read as having no judge.

## Open Questions

- Whether to allow capping judges per answer (e.g. at most 2) for large model sets; deferrable because the default full panel is correct and only costs time.
- Whether to suggest cross-model judging as the default whenever two or more models are selected; deferred until users have tried it (default stays *No judge*).
- Whether to offer a later "leniency-adjusted" comparison built on the per-judge averages.

## Implementation Notes

Details settled while implementing; behaviour in `specs/` is unchanged.

- Cross-model planning (`plan_judgements`) iterates **judge-major** so each judge's tasks are contiguous; the executor unloads the previous judge when the judge changes.
- `judge_run` takes a `judge_think` **mapping** (model name -> `think` setting) instead of one value, because cross-model mode uses several judges. Thinking is disabled only for thinking-capable judges.
- A judgement's `detail` is the raw result of one judge call (including its call metrics); the aggregate `Score` copies it to the top level only in single mode with one judge, which keeps the previous output shape byte-for-byte for existing consumers.
- The summary's per-judge statistics are computed from `judgement` rows; `reasoning_mean_score` is kept apart from the generation `mean_score` because the rubrics differ.
- The Results header and attempt selector describe the *displayed* scoring attempt (its mode and judge), not the run's original mode, so a re-scored run is labelled correctly.
- The Run setup notice shown when cross-model judging is switched off automatically is dismissible, because re-selecting the already-checked "No judge" radio fires no event.
- Cost estimate on Run setup counts generation cases (plus reasoning cases when reasoning-quality judging is on) of the selected suites and ad-hoc prompts; cases individually deselected inside a suite are not subtracted, so it is an upper estimate.
- Old databases migrate in place: the real development database with runs made before this change opened as `single`/`none` and kept its self-judged flags.

