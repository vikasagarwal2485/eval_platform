# Spec Delta

## ADDED Requirements

### Requirement: Cloud models are labelled in results and Run setup
The web UI SHALL mark enterprise models with a cloud indicator and their provider wherever models are shown (Run setup, live view, leaderboard, charts, drill-down, history), and SHALL list on Run setup which providers will receive data in the configured run, including providers used only as judges.

#### Scenario: Cloud badge
- **WHEN** a run includes an enterprise model
- **THEN** its name is accompanied by a cloud indicator and provider name in the leaderboard and drill-down

#### Scenario: Data-sharing notice
- **WHEN** the user configures a run that uses an enterprise model as contestant or judge
- **THEN** Run setup lists each provider that will receive prompts or answers before the run can be started

#### Scenario: Local-only run
- **WHEN** a run uses only local models
- **THEN** no data-sharing notice is shown

## MODIFIED Requirements

### Requirement: Model selection
The web UI SHALL show all available models, grouped by source (local Ollama models and enterprise models by provider) with key details, and let the user select multiple models via checkboxes for a run. Enterprise models whose provider key is not available SHALL be shown as unavailable with the reason.

#### Scenario: Select multiple models
- **WHEN** the user ticks three models
- **THEN** the UI shows the count of selected models and enables starting a run

#### Scenario: Ollama unreachable
- **WHEN** Ollama is unreachable
- **THEN** the UI shows the connectivity error and disables run creation

#### Scenario: Cloud model without a key
- **WHEN** an enabled enterprise model's provider key variable is not set
- **THEN** its checkbox is disabled and the reason names the variable

#### Scenario: Groups are labelled
- **WHEN** the model list contains local and enterprise models
- **THEN** local models are shown under Ollama and enterprise models under their provider names

### Requirement: Export results
The web UI SHALL let the user export a run's results (scores, metrics, outputs) as CSV and JSON, identifying each model's source and provider.

#### Scenario: Export CSV
- **WHEN** the user exports a run as CSV
- **THEN** the file has one row per model/case/repeat with category, score, outcome, and performance columns

#### Scenario: Provider columns
- **WHEN** the user exports a run that includes enterprise models
- **THEN** each row identifies the model's source (local or cloud) and provider, and the export contains no API key
