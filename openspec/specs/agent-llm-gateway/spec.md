# agent-llm-gateway Specification

## Purpose

Gives agent processes one shared place to reach any configured LLM provider by a routing name
scoped to a task, instead of each agent holding its own direct, hardcoded connection to a single
provider endpoint.

## Requirements

### Requirement: Task-scoped model groups
The gateway SHALL expose a named model group for each `(agent, task type)` pair it is configured
for, and SHALL route a request addressed to that name to the provider deployment configured for
it.

#### Scenario: A request reaches the configured deployment
- **WHEN** a caller sends a completion request addressed to a configured model group name
- **THEN** the gateway routes the request to the provider deployment configured for that group
  and returns that deployment's response

#### Scenario: An unconfigured group name is rejected
- **WHEN** a caller sends a completion request addressed to a model group name that is not
  configured
- **THEN** the gateway rejects the request with an error identifying the unknown group, rather
  than guessing a deployment to use

### Requirement: Gateway-held provider credentials
The gateway SHALL hold the credential for each configured provider deployment itself, read from
its own environment, and SHALL never require or accept a caller-supplied provider credential for
a routed request. A caller authenticates to the gateway with a gateway-issued credential scoped
to the model groups it may use.

#### Scenario: A caller reaches a provider without holding its credential
- **WHEN** an agent process sends a request through the gateway using only its gateway-issued
  credential
- **THEN** the request reaches the underlying provider using a credential the agent process never
  held

#### Scenario: A credential scoped to other groups is rejected
- **WHEN** a caller presents a gateway-issued credential that is not scoped to the model group a
  request addresses
- **THEN** the gateway rejects the request without routing it to any provider

### Requirement: No silent deployment substitution
When the gateway cannot reach the provider deployment configured for a model group, it SHALL
return an error to the caller rather than silently substituting a different deployment, unless a
fallback deployment has been explicitly configured for that group.

#### Scenario: An unreachable deployment surfaces as an error
- **WHEN** the provider deployment configured for a model group is unreachable and no fallback is
  configured for that group
- **THEN** the gateway returns an error to the caller rather than routing the request to an
  unrelated deployment

#### Scenario: A configured fallback is used and is visible to the caller
- **WHEN** the primary deployment for a model group is unreachable and a fallback deployment is
  configured for that group
- **THEN** the gateway routes the request to the fallback deployment and the response identifies
  which deployment actually produced it

### Requirement: Model groups are scoped per agent
Model group names SHALL be unique per `(agent, task type)` pair, so that a request made under one
agent's model group can never be routed to a deployment configured for a different agent's model
group of the same task type.

#### Scenario: Two agents' same-task-type groups stay isolated
- **WHEN** two different agents are each configured with a model group for the same task type
  (for example, both have a `reasoning` group)
- **THEN** each agent's requests are routed only to the deployment configured under that agent's
  own group name, never the other agent's
