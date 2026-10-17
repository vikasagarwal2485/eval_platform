# Spec Delta

## ADDED Requirements

### Requirement: An agent can discover its own registration
The system SHALL let a registered agent read back its own name, kind, declared models, and the
gateway model group name computed for each of its declared task types, authenticated by the same
ingest token it uses to send events. The response SHALL NOT include the ingest token itself, any
gateway credential, or any provider secret.

#### Scenario: An agent reads its own identity and group names
- **WHEN** an agent calls the self-discovery endpoint with its own valid ingest token
- **THEN** the response includes that agent's registered name, kind, declared models, and the
  exact gateway model group name the platform would use (or has used) to sync each declared task
  type, computed the same way the platform's own gateway sync computes it

#### Scenario: An invalid or missing token is rejected
- **WHEN** the self-discovery endpoint is called without a valid ingest token
- **THEN** the request is rejected as unauthorized and no agent's registration is returned

#### Scenario: A paused agent can still discover itself
- **WHEN** a paused agent calls the self-discovery endpoint with its still-valid ingest token
- **THEN** the request succeeds and returns its registration, since discovering its own identity is
  not the same as sending it live traffic

#### Scenario: No secret is ever returned
- **WHEN** any agent calls the self-discovery endpoint
- **THEN** the response contains only its name, kind, declared models and computed gateway group
  names, and never its ingest token, a gateway credential, or a provider secret
