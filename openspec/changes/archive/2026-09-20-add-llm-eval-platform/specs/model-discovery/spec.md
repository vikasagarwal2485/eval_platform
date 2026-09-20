# Spec Delta

## Purpose

Lets the platform discover which models are installed on the local Ollama server and report whether the server is reachable, so users only ever select models that can actually be run.

## ADDED Requirements

### Requirement: List installed Ollama models
The system SHALL retrieve the models installed on the configured Ollama server and expose, for each model: name/tag, digest, size on disk, parameter size, quantization level, model family, and reported capabilities (e.g. completion, thinking, tools).

#### Scenario: Models are listed
- **WHEN** the Ollama server is reachable and has models installed
- **THEN** the system returns every installed model with its name, digest, size, parameter size, quantization, family, and capabilities

#### Scenario: No models installed
- **WHEN** the Ollama server is reachable but has no models installed
- **THEN** the system returns an empty list and the UI explains how to pull a model (e.g. `ollama pull <model>`)

### Requirement: Refresh model list on demand
The system SHALL let the user refresh the model list without restarting the application, and SHALL reflect models pulled or removed since the last refresh.

#### Scenario: New model appears after refresh
- **WHEN** the user pulls a new model in Ollama and triggers a refresh
- **THEN** the new model appears in the list and is selectable

#### Scenario: Removed model disappears after refresh
- **WHEN** a model is removed from Ollama and the user triggers a refresh
- **THEN** the model is no longer offered for selection, while historical results referencing it remain viewable

### Requirement: Report Ollama connectivity
The system SHALL report whether the Ollama server is reachable and SHALL surface a clear, actionable error when it is not.

#### Scenario: Server unreachable
- **WHEN** the Ollama server cannot be reached at the configured base URL
- **THEN** the system reports "Ollama unreachable", shows the configured URL, and disables starting new runs

#### Scenario: Configurable server address
- **WHEN** the user configures a different Ollama base URL (default `http://localhost:11434`)
- **THEN** the system uses that URL for discovery and for all subsequent runs

### Requirement: Identify model capabilities relevant to evaluation
The system SHALL indicate for each model whether it supports a separate "thinking" (reasoning trace) output, so that reasoning evaluation and metrics can treat thinking output correctly.

#### Scenario: Thinking-capable model
- **WHEN** a model reports the `thinking` capability
- **THEN** the model list flags it as thinking-capable and run configuration offers a thinking on/off option for that model
