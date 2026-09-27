# Spec Delta

## ADDED Requirements

### Requirement: Unified list of available models
The system SHALL present one list of available models that combines the models installed on the Ollama server with the enabled models registered under enterprise providers. Each entry SHALL carry a reference, display name, source (`local` or `cloud`), provider (for cloud models), capabilities, and availability with the reason when unavailable.

#### Scenario: Mixed list
- **WHEN** Ollama has two installed models and one provider has two enabled models with its key available
- **THEN** the list contains all four, each marked local or cloud, with cloud models showing their provider

#### Scenario: Cloud model without a key
- **WHEN** an enabled model belongs to a provider whose key variable is not set
- **THEN** it is listed as unavailable with the reason and the variable name

#### Scenario: Ollama down, providers up
- **WHEN** Ollama is unreachable but a provider's key is available
- **THEN** the list still contains the enterprise models as available, and no Ollama models

#### Scenario: Nothing available
- **WHEN** there are no installed models and no enabled enterprise models
- **THEN** the list is empty and the UI explains both ways to add models: pull one with Ollama, or register a provider

## MODIFIED Requirements

### Requirement: Report Ollama connectivity
The system SHALL report whether the Ollama server is reachable and SHALL surface a clear, actionable error when it is not. An unreachable Ollama SHALL prevent only the use of Ollama models; runs that use only enterprise models SHALL remain possible.

#### Scenario: Server unreachable
- **WHEN** the Ollama server cannot be reached at the configured base URL
- **THEN** the system reports "Ollama unreachable", shows the configured URL, and disables starting new runs

#### Scenario: Configurable server address
- **WHEN** the user configures a different Ollama base URL (default `http://localhost:11434`)
- **THEN** the system uses that URL for discovery and for all subsequent runs

#### Scenario: Only enterprise models needed
- **WHEN** Ollama is unreachable and the user starts a run whose models and judge are all enterprise models
- **THEN** the run starts normally
