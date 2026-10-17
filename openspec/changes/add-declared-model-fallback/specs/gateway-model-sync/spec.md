# Spec Delta

## Purpose

Keeps the shared LLM gateway's per-agent model groups consistent with what each agent's
`declared_models` actually says, so an operator configures a model and its generation parameters
once, in the registry, instead of maintaining the same information by hand in the gateway's own
configuration.

## ADDED Requirements

### Requirement: A declared model's fallback is synced to its own gateway group
When an agent's declared model for a task type specifies a fallback model reference, the system
SHALL create, update or remove a second gateway model group for that task type - scoped to the
agent the same way the primary group is - configured with the fallback's resolved deployment.

#### Scenario: A declared fallback gets a matching fallback gateway group
- **WHEN** an agent's declared model for a task type specifies a fallback model reference
- **THEN** the system creates a gateway model group for that task type's fallback, configured with
  the fallback model's resolved deployment, in addition to the existing primary group

#### Scenario: A changed fallback updates the existing fallback gateway group
- **WHEN** an agent's fallback for a task type is changed to a different model or different
  generation parameters
- **THEN** the system updates that task type's existing fallback gateway group to match, rather
  than leaving the old configuration in place or creating a duplicate

#### Scenario: Removing a fallback removes its gateway group
- **WHEN** a previously configured fallback is removed from a declared model, the declared model
  itself is removed, or its task type is removed entirely
- **THEN** the system removes that task type's fallback gateway group so it can no longer be
  routed to
