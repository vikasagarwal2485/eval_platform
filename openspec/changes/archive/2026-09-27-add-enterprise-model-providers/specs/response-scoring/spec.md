# Spec Delta

## MODIFIED Requirements

### Requirement: Judge-based scoring
The system SHALL score generation cases, and optionally reasoning quality, using an LLM judge (any available local or enterprise model chosen by the user, or the evaluated models themselves when cross-model judging is used) against a rubric, producing an integer 1-5 score per criterion with a short justification, normalized to 0-1.

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

#### Scenario: Enterprise judge
- **WHEN** the selected judge is an enterprise model
- **THEN** the answers are scored by that model with the same rubric and normalization as a local judge, and the UI states that the answers are sent to its provider

#### Scenario: Judge outside the evaluated set
- **WHEN** the judge is a model that is not one of the evaluated models
- **THEN** the scores are not labelled self-judged
