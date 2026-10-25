# Spec Delta

## MODIFIED Requirements

### Requirement: A run can attach one or more skills to every model it evaluates
The system SHALL let the user attach one or more registered skills to a run's configuration. When
one or more skills are attached, every request the run sends - for every selected model, every
selected case, every repeat - SHALL have the attached skills' instructions included in its prompt,
in addition to that case's own prompt and template. A run started with no skills attached SHALL
behave exactly as it already does today. When a model's warm-up request is sent, it SHALL also
include the run's attached skill(s) instructions, so that any one-time cost of processing that
prefix is absorbed by the (already-excluded-from-measurement) warm-up request rather than by the
first measured case.

#### Scenario: A skill's instructions reach every model in the run
- **WHEN** the user attaches a skill to a run that selects two models and ten cases
- **THEN** all twenty requests (times the configured repeat count) include that skill's
  instructions in their prompt, and none of the run's other behavior (sequencing, scoring,
  live progress) changes

#### Scenario: Multiple skills attach together
- **WHEN** the user attaches two skills to a run
- **THEN** every request in that run includes both skills' instructions

#### Scenario: No skills attached is unchanged behavior
- **WHEN** the user starts a run without attaching any skill
- **THEN** every request's prompt is built exactly as it was before this capability existed

#### Scenario: An unknown or removed skill id is rejected at start
- **WHEN** the user attempts to start a run naming a skill id that does not exist
- **THEN** the system refuses to start the run and names the missing skill, the same way an
  unavailable model selection is already refused

#### Scenario: Warm-up carries the skill prefix
- **WHEN** a run has one or more skills attached and warm-up is enabled for a model that supports it
- **THEN** that model's warm-up request includes the attached skill(s) instructions, identically to
  how every measured request for that model will include them

#### Scenario: No skills attached means warm-up is unchanged
- **WHEN** a run has no skills attached
- **THEN** the warm-up request is built exactly as it already is today
