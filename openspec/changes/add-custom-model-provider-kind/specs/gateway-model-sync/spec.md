# Spec Delta

## ADDED Requirements

### Requirement: A declared model that is not gateway-routable is never synced as an error
When an agent's declared model for a task type resolves to a provider kind that has no
chat-completions-shaped gateway deployment to create (a `custom`-kind provider), the system SHALL
report that task type's sync outcome as explicitly not applicable, rather than as a sync error, and
SHALL NOT attempt to create, update or remove any gateway model group for it.

#### Scenario: A custom-kind declared model is reported as not gateway-routed, not an error
- **WHEN** an agent is registered or updated with a declared model for a task type that resolves
  to a `custom`-kind provider
- **THEN** that task type's sync result reports it is not gateway-routed, the request otherwise
  succeeds, and no gateway model group is created, updated or queried for that task type

#### Scenario: A previously gateway-routed task type switched to a custom-kind model removes its old group
- **WHEN** a task type's declared model is changed from one that resolved to a gateway-routable
  provider to one that resolves to a `custom`-kind provider
- **THEN** the system removes that task type's existing gateway model group (it is no longer
  routable) and reports the task type as not gateway-routed, not as an error
