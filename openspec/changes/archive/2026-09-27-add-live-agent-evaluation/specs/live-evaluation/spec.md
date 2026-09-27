# Spec Delta

## Purpose

Scores an agent's finished turns against a rubric using a model that never produced any part of the turn, at a pace that never disturbs the agent's own performance or a benchmark run's measurements.

## ADDED Requirements

### Requirement: Finished turns are queued for evaluation
A turn that ends successfully SHALL be queued for evaluation according to the agent's sample rate. A turn excluded by sampling SHALL be visibly marked as not sampled rather than left to look unevaluated by omission.

#### Scenario: Sampled turn is queued
- **WHEN** a turn ends with status ok and the agent's sample rate selects it
- **THEN** an evaluation is created for it in a pending state

#### Scenario: Unsampled turn is not queued
- **WHEN** a turn ends with status ok but the agent's sample rate does not select it
- **THEN** no evaluation is created for it, and it is shown as not sampled rather than as pending or failed

#### Scenario: Failed or abandoned turns are not queued
- **WHEN** a turn ends with an error status, or is marked abandoned
- **THEN** it is not queued for evaluation

### Requirement: An evaluator never scores a turn it helped produce
Only models that did not appear in a turn's own LLM spans SHALL be eligible to evaluate that turn. The check SHALL be based on the models the turn actually used, not on the agent's declared model.

#### Scenario: Two eligible evaluators judge independently
- **WHEN** an agent's configured evaluators are models B and C, and a turn was produced using model A
- **THEN** both B and C evaluate the turn and neither A nor any model that authored the turn is asked to

#### Scenario: A configured evaluator that authored the turn is excluded
- **WHEN** an agent's configured evaluators include model A, and a turn was produced using models A and B
- **THEN** the turn is evaluated only by the other configured evaluators, and A is skipped for this turn specifically

#### Scenario: No eligible evaluator
- **WHEN** every configured evaluator for an agent also appears among the models that produced a given turn
- **THEN** the turn's evaluation is marked not evaluated with a reason stating no eligible evaluator was available, and the turn is never scored by one of its own models

#### Scenario: Turn's model set is unknown
- **WHEN** a turn is flagged as having an unknown model set
- **THEN** it is marked not evaluated with a reason stating the agent's model could not be determined, rather than being evaluated by default

### Requirement: An unavailable evaluator is skipped, not substituted
When a configured evaluator is disabled or its provider's key is unavailable at evaluation time, that evaluator SHALL be skipped for the affected turns with the specific reason recorded, without silently using an ineligible model in its place and without failing evaluators that remain available.

#### Scenario: One evaluator's key is missing
- **WHEN** a panel of two evaluators is configured and one provider's API key is currently unavailable
- **THEN** the turn is evaluated by the remaining available evaluator, and the unavailable one's absence and reason are recorded

#### Scenario: All configured evaluators unavailable
- **WHEN** every configured evaluator is disabled or unavailable at evaluation time
- **THEN** the turn's evaluation is marked not evaluated with that reason, and is retried on the next evaluation pass rather than being scored by an ineligible model

### Requirement: Combine multiple evaluators' scores and keep each one
When a turn is evaluated by more than one eligible evaluator, the turn's score SHALL be the arithmetic mean of the successful evaluators' normalized scores, and each evaluator's own score, criterion scores and reasons SHALL remain individually visible.

#### Scenario: Mean of two evaluators
- **WHEN** two eligible evaluators score a turn 0.6 and 0.8
- **THEN** the turn's evaluated score is 0.7 and both individual evaluations remain available

#### Scenario: One of several evaluators fails
- **WHEN** one eligible evaluator's call fails after its own retries and another succeeds
- **THEN** the turn's score is based on the successful evaluator, and the failed one is recorded as an error with its reason

### Requirement: Evaluation uses a rubric and recent context
Each turn SHALL be evaluated against a rubric: the agent's custom rubric if configured, otherwise a built-in rubric for its kind. The rubric used SHALL be recorded on the evaluation so that later rubric edits do not change the meaning of past scores. The evaluator SHALL be given the turn's input, its final output, and a bounded window of the session's preceding turns as context.

#### Scenario: Built-in rubric by kind
- **WHEN** an agent of kind chatbot has no custom rubric configured
- **THEN** its turns are evaluated against the built-in chatbot rubric, and this is recorded on each evaluation

#### Scenario: Rubric edit does not rewrite history
- **WHEN** the user edits an agent's custom rubric after turns have already been evaluated
- **THEN** previously recorded evaluations keep showing the rubric that was active when they ran, and only new evaluations use the edited rubric

### Requirement: Reference-based correctness is scored separately when available
When a turn's start event includes an expected answer, the system SHALL additionally compute a reference-based correctness result for it and store it alongside, not blended into, the evaluator-judged score.

#### Scenario: Reference supplied
- **WHEN** a turn is started with an expected answer and later evaluated
- **THEN** the evaluation shows both the evaluator-judged score and a separate reference-based correctness result

### Requirement: Evaluation is paced and never overlaps a measured benchmark run
The system SHALL evaluate a finished turn only after a configurable quiet period has elapsed since it ended, SHALL process one evaluator call at a time, and SHALL NOT run any evaluation while a benchmark run is actively measuring models.

#### Scenario: Quiet period delays evaluation
- **WHEN** a turn ends and the agent is still actively producing further turns
- **THEN** its evaluation is deferred until the configured quiet period has passed without new activity

#### Scenario: Benchmark run takes priority
- **WHEN** a benchmark run is actively measuring models
- **THEN** pending evaluations wait and resume automatically once the benchmark run finishes, without affecting the benchmark's own measurements

### Requirement: A growing backlog degrades visibly instead of unbounded
When the number of pending evaluations exceeds a configured limit, the oldest pending evaluations SHALL be marked skipped due to backlog rather than left to grow indefinitely, and the number skipped SHALL be visible.

#### Scenario: Backlog cap reached
- **WHEN** pending evaluations exceed the configured limit
- **THEN** the oldest excess pending evaluations are marked skipped with a backlog reason, and the count of backlog-skipped evaluations is shown to the user

### Requirement: Turns can be re-evaluated without losing history
The user SHALL be able to trigger re-evaluation of one turn or a set of turns with the current or a different evaluator configuration. Re-evaluation SHALL create a new evaluation attempt and SHALL leave prior attempts readable.

#### Scenario: Re-evaluate with a different evaluator
- **WHEN** the user re-evaluates a turn with a different evaluator than the one originally used
- **THEN** a new evaluation attempt is created and shown as current, and the original attempt remains viewable

#### Scenario: Bulk re-evaluation
- **WHEN** the user requests re-evaluation of every turn below a score threshold within a time window
- **THEN** a new evaluation attempt is queued for each matching turn without re-running the agent
