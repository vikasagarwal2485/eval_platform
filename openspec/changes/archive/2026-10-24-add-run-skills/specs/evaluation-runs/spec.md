# Spec Delta

## ADDED Requirements

### Requirement: A run can attach one or more skills to every model it evaluates
The system SHALL let the user attach one or more registered skills to a run's configuration. When
one or more skills are attached, every request the run sends - for every selected model, every
selected case, every repeat - SHALL have the attached skills' instructions included in its prompt,
in addition to that case's own prompt and template. A run started with no skills attached SHALL
behave exactly as it already does today.

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

### Requirement: A run's attached skills are recorded as they were at run time
The system SHALL store, with the run's configuration, the exact name and instructions of every
skill it attached at the time it started - not merely a reference to the registry entry - so that
editing or deleting a skill afterward never changes what a past run shows it used.

#### Scenario: Editing a skill after a run does not alter that run
- **WHEN** a skill's instructions are edited after a run that attached it has completed
- **THEN** the run's own stored configuration still shows the instructions exactly as they were
  when the run executed

#### Scenario: Deleting a skill after a run does not alter that run
- **WHEN** a skill is deleted after a run that attached it has completed
- **THEN** the run's own record is unaffected and still names the skill and shows the instructions
  it used

#### Scenario: Comparing a skill-equipped run against a bare run
- **WHEN** the user compares a run that attached a skill against a run of the same models and
  suite with no skill attached
- **THEN** the existing run-vs-run comparison shows both runs' quality, latency and tokens-per-sec
  side by side, using the comparison tooling that already exists for comparing any two runs
