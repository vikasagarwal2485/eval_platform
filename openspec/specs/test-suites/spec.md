# test-suites Specification

## Purpose

Defines how evaluation inputs are authored, stored, and reused: categorized test cases (classification, reasoning, generation) with optional ground truth, plus one-off ad-hoc prompts.

## Requirements

### Requirement: Categorized test cases
The system SHALL support test cases in exactly three categories: `classification`, `reasoning`, and `generation`. Every test case SHALL have an input prompt and a category, and MAY have a system prompt, an expected answer, and metadata tags.

#### Scenario: Create a classification case
- **WHEN** the user creates a `classification` case with a prompt, a set of allowed labels, and an expected label
- **THEN** the system stores the case and validates that the expected label is one of the allowed labels

#### Scenario: Create a reasoning case
- **WHEN** the user creates a `reasoning` case with a prompt and an expected final answer
- **THEN** the system stores the case and records how the final answer is compared (exact text, or numeric with tolerance)

#### Scenario: Create a generation case
- **WHEN** the user creates a `generation` case with a prompt and an optional rubric (criteria and 1-5 scale) and optional constraints (e.g. max words, required keywords)
- **THEN** the system stores the case; an expected answer is not required

#### Scenario: Invalid case rejected
- **WHEN** the user submits a case with an empty prompt or an unknown category
- **THEN** the system rejects it with a validation error identifying the offending field

### Requirement: Test suites
The system SHALL group test cases into named suites that can be created, edited, duplicated, and deleted, and SHALL allow a suite to contain cases from multiple categories.

#### Scenario: Build a mixed suite
- **WHEN** the user adds classification, reasoning, and generation cases to one suite
- **THEN** the suite lists all cases with their categories and can be selected as a whole for a run

#### Scenario: Editing a suite does not alter past runs
- **WHEN** a suite or case is edited or deleted after a run used it
- **THEN** the historical run continues to show the exact prompts and expected answers used at run time

### Requirement: Built-in starter suite
The system SHALL ship with a small built-in starter suite covering all three categories (with expected answers where applicable) so the platform is usable immediately after installation.

#### Scenario: First launch
- **WHEN** the user opens the platform for the first time
- **THEN** a starter suite is available containing at least classification, reasoning, and generation cases

### Requirement: Ad-hoc prompts
The system SHALL let the user run a single ad-hoc prompt by entering free text, choosing a category, and optionally supplying an expected answer, without first creating a suite.

#### Scenario: Ad-hoc prompt without expected answer
- **WHEN** the user submits an ad-hoc prompt with no expected answer
- **THEN** the system runs it and reports performance metrics and outputs; correctness scoring is skipped unless a judge is enabled

#### Scenario: Save ad-hoc prompt to a suite
- **WHEN** the user chooses to save an ad-hoc prompt
- **THEN** it is added as a test case to a chosen or newly created suite

### Requirement: Import and export suites
The system SHALL import and export suites in a documented, human-editable file format (JSON or YAML).

#### Scenario: Export then import round-trip
- **WHEN** the user exports a suite and imports the resulting file
- **THEN** the imported suite contains identical cases, categories, expected answers, and rubrics

#### Scenario: Malformed import
- **WHEN** the user imports a file that violates the schema
- **THEN** the system rejects the import, reports the line/field errors, and creates no partial suite
