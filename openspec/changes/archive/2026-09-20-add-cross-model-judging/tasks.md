# Tasks

## 1. Data model and migration

- [x] 1.1 Add `judge_mode` (`none`/`single`/`cross_model`, default `none`) to `Run` and `ScoringAttempt` and a `Judgement` table (attempt, result, kind, judge model, value, outcome, detail) in the ORM models, and add Alembic revision `0002` that creates them and backfills `single` where `judge_model` is set; verify a migration test upgrades a database populated at revision `0001` (a run with a judge and one without) and finds `single`/`none` respectively, and the existing "no drift between migrations and models" test still passes
- [x] 1.2 Add repository helpers to create an attempt with a mode, add and list judgements for a result or attempt, and rebuild a result's aggregate `judge` score row from its judgements; verify unit tests cover mean of successes, one failed judge, all failed (`error`, value `None`), and idempotent rebuilding

## 2. Request validation and API surface

- [x] 2.1 Add `judge_mode` to the create-run and re-score request schemas and to the run and attempt responses, with a single validation routine implementing the mode/`judge_model` matrix from the design (omitted mode inferred from `judge_model`; single needs a judge; none or cross with a judge is rejected; cross needs 2+ distinct models); verify API tests cover every row of the matrix, including the 422 messages and that no run is created on rejection
- [x] 2.2 Make re-run copy `judge_mode`/`judge_model`, and make re-score accept a mode (cross-model unavailable for a run with fewer than two models); verify API tests for re-run of a cross-model run and for re-scoring a one-model run with cross-model (rejected with a clear reason)

## 3. Judgement planning and execution

- [x] 3.1 Implement the pure `plan_judgements` function (single: one task per target answer; cross-model: one task per answer per other evaluated model, matching authors by snapshot id, for both generation and reasoning-quality kinds); verify unit tests for two models (A judged only by B and vice versa), three models (each answer gets the two others), same tag with different digests treated as different models, and that no task ever has judge equal to author
- [x] 3.2 Implement judgement execution and aggregation in the scoring service: run the plan grouped by judge model in run-model order, persist each judgement as it finishes, and write one aggregate `judge`/`judge_reasoning` row per answer (mean of successes, `detail.judgements`, `judges_used`, `self_judged` false in cross mode, top-level `criteria` preserved for single mode); verify tests with the fake Ollama for 2 and 3 models, one judge returning invalid JSON, all judges failing, and unchanged output shape for single-judge runs (existing scoring tests stay green)
- [x] 3.3 Order and resource behaviour: all of one judge's judgements finish before the next judge starts, the previous judge is unloaded between groups, thinking is disabled for thinking-capable judges, failed requests are never sent to a judge, and connection loss aborts the stage; verify the fake client's call log shows grouped order, the unload calls, `think` false where applicable, and no judge calls for an errored answer
- [x] 3.4 Wire cross-model mode into the run worker and the re-score job (including `scoring_started`/`scoring_progress` totals that count all judgements, cancellation between judgements, rebuilding aggregates for what was judged before a cancel); verify tests that a cancel mid-stage keeps completed judgements and marks the run cancelled, that judging starts only after all generation requests, and that judge requests never appear in the evaluated models' performance figures
- [x] 3.5 Handle a judge model that is no longer installed at re-score time by recording its judgements as errors while other judges continue; verify a re-score test where one model is removed from the fake Ollama

## 4. Summary, results and export

- [x] 4.1 Extend the summary with `judging` (mode and per-judge judged count, mean score and error count for the selected attempt), `judge_mode` on each attempt, and `judges_per_answer` on leaderboard rows; verify API tests that a cross-model run reports each judge's mean and that `self_judged` is false for every model, while a single-judge run with a contestant judge still reports `self_judged` true
- [x] 4.2 Expose per-judge scores in the results payload and add `judge_mode` and `judges` (`model=score;...`) to the CSV export and the judgements to the JSON export; verify export tests parse the CSV columns and the JSON judgements for a cross-model run
- [x] 4.3 Confirm composite, category scores and two-run comparison work unchanged on cross-judged runs, including comparing a cross-judged run with a single-judge run; verify a compare test that flags differing judge modes in its response

## 5. Frontend

- [x] 5.1 Update the API types and mutations for `judge_mode`, per-judge details and the summary `judging` block; verify `npm run typecheck` passes and unit tests assert the create-run payload for each of the three modes
- [x] 5.2 Replace the judge select in the run configuration panel with a Judging control (No judge / Single judge model / Cross-model), show the judge select only for Single, disable Cross-model with an explanation below two selected models, reset to No judge with a message if the selection later drops below two, and show the explanatory note and the judgement-count estimate; verify component tests for each state and for the payload sent
- [x] 5.3 Add the "Use cross-model judging instead" action to the self-judging warning (enabled with two or more models); verify a test that activating it changes the mode, clears the judge and hides the warning
- [x] 5.4 On the Results page show a "cross-judged" badge with judge count instead of "self-judged" for cross-model attempts, suppress the self-judging banner there, add a Judge strictness card listing each judge's mean score and errors, label attempts with their mode, and add the mode choice to Re-score; verify component tests for badge, banner, card and the re-score payload
- [x] 5.5 Show every judge's name, score, criteria and reasons for a judged answer in the case drill-down; verify a component test with two judges and one failed judge
- [x] 5.6 Extend the accessibility tests to cover the new controls, card and drill-down; verify the axe audit reports no violations and that the radio group and disabled option are keyboard-operable with accessible names and descriptions

## 6. Integration and documentation

- [x] 6.1 Add an end-to-end test over the fake Ollama HTTP server: two models with cross-model judging, asserting each model is judged only by the other, no `self_judged`, per-judge scores in results and export, and the judge order on the wire; verify it passes with `pytest`
- [x] 6.2 Run a live cross-model evaluation against local Ollama with the two installed models (`qwen3:8b`, `gemma4:e4b`) on the starter suite, then re-score the same run with a single judge; verify the run completes, no score is marked self-judged, each judge's scores are visible in the UI, and both attempts remain readable
- [x] 6.3 Update the README scoring and limitations sections (cross-model judging, its cost and the judge-strictness caveat) and the design notes; verify `make lint` and `make test` pass and `openspec validate add-cross-model-judging --strict` is valid
