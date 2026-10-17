# Spec Delta

## ADDED Requirements

### Requirement: Model groups can be managed dynamically
The gateway SHALL support creating, updating and removing a model group through its own
management interface, taking effect for new requests without restarting the gateway process, in
addition to any model group defined in its static configuration.

#### Scenario: A dynamically created group routes immediately
- **WHEN** a model group is created through the gateway's management interface
- **THEN** a request addressed to that group name succeeds without the gateway process being
  restarted

#### Scenario: A dynamically removed group stops routing immediately
- **WHEN** a model group created through the gateway's management interface is removed
- **THEN** a subsequent request addressed to that group name is rejected as an unconfigured group,
  without the gateway process being restarted

#### Scenario: Static and dynamic groups coexist
- **WHEN** the gateway has both statically configured model groups and dynamically managed ones
- **THEN** requests to either kind of group are routed correctly, and managing one kind does not
  disturb the other

### Requirement: Dynamically managed credentials are never exposed in the clear
When a model group is created or updated through the gateway's management interface with a
provider credential given by environment-variable reference, the gateway SHALL resolve and store
that credential without exposing its literal value in any management-interface response.

#### Scenario: A credential given by reference is never echoed back
- **WHEN** a caller creates or updates a model group's credential using an environment-variable
  reference rather than a literal value
- **THEN** no response from the gateway's management interface contains that credential's literal
  value
