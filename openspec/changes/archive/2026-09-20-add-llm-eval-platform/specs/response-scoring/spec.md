# Spec Delta

## Purpose

Turns raw model outputs into comparable scores: automatic correctness scoring where ground truth exists, judge-based scoring where it does not, and aggregation into per-category and composite scores.

## ADDED Requirements

### Requirement: Separate reasoning trace from final answer
The system SHALL separate a thinking model's reasoning trace from its final answer and SHALL score correctness on the final answer only.

#### Scenario: Thinking output present
- **WHEN** a thinking-capable model returns a reasoning trace and a final answer
- **THEN** the stored result keeps both separately, and correctness scoring uses only the final answer

#### Scenario: Inline think tags
- **WHEN** a model embeds its reasoning inside `<think>...</think>` tags in the response text
- **THEN** the system strips that block from the answer used for scoring and keeps it as the reasoning trace

### Requirement: Classification scoring
The system SHALL score classification cases by comparing the model's predicted label with the expected label after normalization (case, whitespace, punctuation), yielding a score of 1 for a match and 0 otherwise, and SHALL record an `unparseable` outcome when no allowed label can be identified in the output.

#### Scenario: Correct label
- **WHEN** the expected label is `positive` and the model answers "Positive."
- **THEN** the case scores 1

#### Scenario: Wrong label
- **WHEN** the model answers `negative` for expected `positive`
- **THEN** the case scores 0 and the predicted label is recorded

#### Scenario: Output contains no valid label
- **WHEN** the model's answer contains none of the allowed labels
- **THEN** the case scores 0 with outcome `unparseable`, counted separately from wrong labels

### Requirement: Classification aggregate metrics
The system SHALL compute, per model, overall accuracy over classification cases and, when there are at least two labels, per-label precision/recall and a confusion matrix.

#### Scenario: Accuracy and confusion matrix
- **WHEN** a model has answered a set of labelled classification cases
- **THEN** the system reports accuracy and a confusion matrix of expected vs. predicted labels

### Requirement: Reasoning scoring
The system SHALL score reasoning cases by extracting the final answer from the model output and comparing it to the expected answer using the case's comparison mode (normalized text or numeric within a tolerance). The system SHALL instruct models, via the prompt template, to end with a clearly marked final answer to make extraction reliable.

#### Scenario: Numeric answer within tolerance
- **WHEN** the expected answer is 42 with tolerance 0 and the model's final answer is "42"
- **THEN** the case scores 1

#### Scenario: Answer not extractable
- **WHEN** no marked final answer can be found
- **THEN** the system falls back to a documented extraction rule; if that also fails, the case scores 0 with outcome `unparseable`

### Requirement: Judge-based scoring
The system SHALL score generation cases, and optionally reasoning quality, using an LLM judge (a locally hosted model chosen by the user) against a rubric, producing an integer 1-5 score per criterion with a short justification, normalized to 0-1.

#### Scenario: Rubric scoring
- **WHEN** a generation case has a rubric with criteria and a judge model is configured
- **THEN** the judge returns a score and justification per criterion, and the case score is the normalized average

#### Scenario: Judge output invalid
- **WHEN** the judge's response cannot be parsed into the required structure
- **THEN** the system retries once, and if it still fails marks the judged score `error` without failing the run

#### Scenario: Judge equals evaluated model
- **WHEN** the selected judge model is also one of the models being evaluated
- **THEN** the UI warns about self-preference bias and the result is labelled accordingly

#### Scenario: No judge configured
- **WHEN** no judge model is configured
- **THEN** generation cases are not judged, show "unscored", and are excluded from composite scores rather than counted as 0

### Requirement: Deterministic constraint checks
The system SHALL support optional deterministic checks on generated text (maximum/minimum length, required keywords, forbidden keywords) that are reported as pass/fail alongside judge scores.

#### Scenario: Length constraint violated
- **WHEN** a generation case sets a maximum of 50 words and the output has 80
- **THEN** the constraint check is reported as failed

### Requirement: Per-category and composite scores
The system SHALL compute a score per model per category (mean of case scores, over repeats) and a weighted composite score using user-adjustable category weights, and SHALL exclude unscored cases from means while reporting how many cases were scored.

#### Scenario: Composite with weights
- **WHEN** the user sets weights classification 0.4, reasoning 0.4, generation 0.2
- **THEN** each model's composite score is the weighted mean of its category scores, recomputed without re-running the models

#### Scenario: Category with no cases
- **WHEN** a run contains no reasoning cases
- **THEN** the reasoning weight is renormalized away and the composite is computed from the remaining categories

### Requirement: Re-scoring without re-running
The system SHALL allow scores to be recomputed for a stored run (for example with a different judge model or corrected expected answer) without regenerating model outputs, keeping prior scoring attempts identifiable.

#### Scenario: Re-judge with a different model
- **WHEN** the user re-scores a completed run with a different judge model
- **THEN** new judged scores are stored and shown, model outputs and performance metrics are unchanged, and the previous scoring remains available
