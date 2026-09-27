# cross-model-judging Specification

## Purpose

Lets the evaluated models judge one another so that no model grades its own output. This removes self-preference bias from judge-based scores, including when the user has only two local models and therefore cannot name a neutral third judge.

## Requirements

### Requirement: Choose a judging mode in Run setup
The Run setup screen SHALL let the user choose how judge-based scoring is done, with exactly three modes: **No judge**, **Single judge model**, and **Cross-model judging**. The chosen mode SHALL be stored with the run's configuration. When no mode is chosen, the platform SHALL behave as it does today (no judge).

#### Scenario: Three modes are offered
- **WHEN** the user opens Run setup
- **THEN** the judging control offers No judge, Single judge model, and Cross-model judging, with a one-line explanation of each

#### Scenario: Single judge behaves as before
- **WHEN** the user selects Single judge model and picks a judge model
- **THEN** every judged answer is scored by that one model exactly as it was before this change, and a judge that is also an evaluated model still marks the scores as self-judged

#### Scenario: Cross-model mode needs no separate judge model
- **WHEN** the user selects Cross-model judging
- **THEN** the single judge model picker is hidden or disabled, and the run can be started without choosing a judge

### Requirement: Cross-model judging needs at least two models
Cross-model judging SHALL be available only when at least two models are selected for the run. The system SHALL enforce this both in the UI and when a run is created or re-scored.

#### Scenario: Only one model selected
- **WHEN** fewer than two models are selected
- **THEN** the Cross-model option is disabled and explains that at least two models are needed

#### Scenario: Selection shrinks after choosing the mode
- **WHEN** the user has chosen Cross-model judging and then deselects models until fewer than two remain
- **THEN** the mode is reset to No judge and the user is told why

#### Scenario: Server rejects an invalid request
- **WHEN** a run is created with cross-model judging and fewer than two distinct models
- **THEN** the request is rejected with a validation error naming the problem and no run is created

#### Scenario: Conflicting judge settings
- **WHEN** a request selects cross-model judging and also names a single judge model
- **THEN** the request is rejected with a validation error, because the two settings contradict each other

### Requirement: A model never judges its own answers
In cross-model mode, a judged answer SHALL be scored only by evaluated models other than the model that produced it. This SHALL hold for generation judging and for the optional reasoning-quality judging.

#### Scenario: Two models judge each other
- **WHEN** models A and B are evaluated with cross-model judging
- **THEN** A's answers are judged by B, B's answers are judged by A, and neither model judges its own answers

#### Scenario: Three or more models
- **WHEN** models A, B and C are evaluated with cross-model judging
- **THEN** each of A's answers is judged by both B and C, each of B's by A and C, and each of C's by A and B

#### Scenario: Reasoning-quality judging
- **WHEN** reasoning-quality judging is enabled together with cross-model judging
- **THEN** a model's reasoning traces are judged only by the other evaluated models

### Requirement: Combine and keep every judge's score
When an answer is judged by more than one model, the answer's judged score SHALL be the arithmetic mean of the successful judges' normalized scores, and the system SHALL keep each judge's own score, criterion scores and reasons.

#### Scenario: Mean of several judges
- **WHEN** an answer is judged by two models that give normalized scores 0.50 and 0.75
- **THEN** the answer's judged score is 0.625 and both individual judgements remain available

#### Scenario: One judge fails
- **WHEN** one of an answer's judges returns unusable output after the retry and another succeeds
- **THEN** the answer's score is based on the successful judge, and the failed judgement is recorded as an error with its reason

#### Scenario: Every judge fails
- **WHEN** all judges of an answer fail
- **THEN** the answer's judged outcome is `error`, it is excluded from category means, and the run is not failed

### Requirement: Judge only answers that exist
Only answers from successful requests SHALL be judged. Failed requests SHALL keep the score behaviour defined for failed requests and SHALL NOT be sent to any judge.

#### Scenario: Errored request
- **WHEN** a model's request for a generation case failed
- **THEN** no judge is asked to score it and the case keeps its error outcome

### Requirement: Cross-model judging spans local and enterprise models
Cross-model judging SHALL work across any mix of evaluated local and enterprise models, following the same rule that a model never judges its own answers, and SHALL disclose which providers will receive other models' answers.

#### Scenario: Mixed pair
- **WHEN** one local model and one enterprise model are evaluated with cross-model judging
- **THEN** the enterprise model judges the local model's answers, the local model judges the enterprise model's answers, and neither judges its own

#### Scenario: Disclosure
- **WHEN** cross-model judging includes an enterprise model as judge
- **THEN** Run setup states that the other models' answers will be sent to that provider

#### Scenario: Cost estimate
- **WHEN** the run setup shows the estimated number of judgements
- **THEN** it distinguishes judgements made by enterprise models from those made locally

### Requirement: Judging runs after generation and limits model loading
Cross-model judging SHALL run only after all generation in the run has finished, so it cannot disturb measured latency. Judging work SHALL be grouped by judge model so each judge model is loaded once per scoring pass rather than alternating between models, and only local judge models SHALL be unloaded between groups. Thinking SHALL be disabled for thinking-capable local judges, as for single-judge mode.

#### Scenario: Speed figures unaffected
- **WHEN** a run with cross-model judging completes
- **THEN** every generation request was measured before any judging request started, and judging requests do not appear in the evaluated models' performance figures

#### Scenario: Grouped by judge
- **WHEN** models A and B judge each other's answers
- **THEN** all of A's judgements are made before any of B's judgements begin

#### Scenario: Cancellation while judging
- **WHEN** the user cancels during the judging stage
- **THEN** judging stops promptly, judgements already made are kept, and the run is marked cancelled

#### Scenario: Enterprise judge group
- **WHEN** an enterprise model is one of the judges
- **THEN** its judgements are made as one group like any other judge, and no unload request is sent for it

### Requirement: Re-score with cross-model judging
A finished run SHALL be re-scorable with any judging mode without regenerating outputs. Each re-scoring SHALL create a new scoring attempt that records its judging mode and the judge models used, and earlier attempts SHALL remain readable.

#### Scenario: Switch a self-judged run to cross-model
- **WHEN** the user re-scores a finished single-judge run that had self-judged scores, choosing cross-model judging
- **THEN** a new scoring attempt is created, outputs and performance metrics are unchanged, and the previous attempt and its self-judged scores remain viewable

#### Scenario: Not enough models in the run
- **WHEN** the user tries to re-score a run that evaluated only one model with cross-model judging
- **THEN** the option is unavailable and the reason is shown

#### Scenario: Judge no longer installed
- **WHEN** a model needed as a judge is no longer installed in Ollama at re-scoring time
- **THEN** its judgements are recorded as errors and the remaining judges are still used

### Requirement: Show how scores were judged
Results SHALL state the judging mode used for the displayed scoring attempt. In cross-model mode the leaderboard SHALL mark generation scores as cross-judged and SHALL NOT mark any score as self-judged. The case drill-down and exported data SHALL show, for each judged answer, which model gave which score together with its criterion scores and reasons.

#### Scenario: Leaderboard indicator
- **WHEN** the user views results of a run scored with cross-model judging
- **THEN** generation scores are marked as cross-judged with the number of judges per answer, and no "self-judged" marker or self-judging warning appears

#### Scenario: Per-judge breakdown
- **WHEN** the user opens a judged generation case in the drill-down
- **THEN** each judge's name, score, criterion scores and reasons are listed, together with the combined score

#### Scenario: Export
- **WHEN** the user exports a run scored with cross-model judging
- **THEN** the export identifies the judging mode and includes each judge's score for every judged answer

### Requirement: Explain the fairness trade-off
The UI SHALL tell the user that in cross-model mode different models grade different answers, and that judges differ in strictness, so judged scores are informative but not perfectly like-for-like. The per-judge scores SHALL be visible so the user can check for a systematically harsh or lenient judge.

#### Scenario: Explanation shown
- **WHEN** the user selects Cross-model judging in Run setup
- **THEN** a short note states that models never grade themselves and that differing judge strictness can affect comparisons

#### Scenario: Judge strictness visible
- **WHEN** the user views a run scored with cross-model judging
- **THEN** the average score each judge gave is shown, so a much harsher or more lenient judge can be spotted

### Requirement: Offer cross-model judging when self-judging is chosen
When the user selects Single judge model and the chosen judge is also one of the selected models, the existing self-judging warning SHALL offer a direct action to switch to cross-model judging (when at least two models are selected).

#### Scenario: Switch from the warning
- **WHEN** the self-judging warning is shown and the user activates its switch action
- **THEN** the mode changes to Cross-model judging, the single judge selection is cleared, and the warning disappears

### Requirement: Existing runs remain valid
Runs and scoring attempts created before this capability existed SHALL continue to load and display. They SHALL be shown as No judge or Single judge model according to whether a judge was used.

#### Scenario: Open an older run
- **WHEN** the user opens a run created before cross-model judging existed
- **THEN** it displays as before, with its judging mode shown as single or none, and can be re-run or re-scored with any mode

#### Scenario: Re-run keeps the mode
- **WHEN** the user re-runs a run that used cross-model judging
- **THEN** the new run uses cross-model judging with the same models
