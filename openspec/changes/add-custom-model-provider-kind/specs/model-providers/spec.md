# Spec Delta

## MODIFIED Requirements

### Requirement: Register a provider by API-key environment variable
The system SHALL let the user register a provider by choosing its kind (`openai`, `anthropic`, `azure-openai`,
`ollama`, or `custom`), a unique name, and, for every kind except `ollama` and `custom`, the **name of the
environment variable that holds its API key** - `ollama` and `custom` have no key concept at all. It MAY accept
an optional base URL for gateways and OpenAI-compatible endpoints; a `custom` provider instead REQUIRES a base
URL, since it has no shared default endpoint of any kind. The system SHALL NOT accept, store or display an API
key itself.

#### Scenario: Register a provider
- **WHEN** the user registers an OpenAI provider named `openai-main` with key variable `OPENAI_API_KEY`
- **THEN** the provider appears in the provider list with its kind, name, variable name, and whether the key is currently available

#### Scenario: Name and kind are validated
- **WHEN** the user submits a provider with an unsupported kind, an empty or duplicate name, or an invalid environment variable name
- **THEN** the system rejects it with a validation error identifying the offending field and registers nothing

#### Scenario: Optional base URL
- **WHEN** the user supplies a base URL that is not an http or https URL
- **THEN** the system rejects it; a valid URL is stored and used for that provider's calls

#### Scenario: A key value is refused
- **WHEN** the value entered as the environment variable name looks like an API key rather than a variable name
- **THEN** the system rejects it and explains that only the variable name is accepted

#### Scenario: Register a custom provider
- **WHEN** the user registers a provider of kind `custom` with a base URL and no key variable
- **THEN** the provider appears in the provider list with its kind and base URL, and no key-variable field is
  shown or required for it, the same way an `ollama` provider already has none

#### Scenario: A custom provider requires a base URL
- **WHEN** the user submits a provider of kind `custom` without a base URL
- **THEN** the system rejects it, explaining that a base URL is required for this kind

### Requirement: Test a provider connection
The system SHALL let the user test a provider and SHALL report the outcome as one of: working, key not set,
authentication failed, rate limited, or unreachable, without revealing any key. For an `azure-openai` provider,
which has no provider-wide endpoint to call, the test SHALL instead be run against one of its registered
deployments, and SHALL report that a deployment must be registered first if none exists. For a `custom`
provider, which does not speak the chat-completions protocol every other kind does, the test SHALL instead be a
plain request to the provider's base URL at a configurable health-check path (a documented default applies when
none is set), reporting "working" for a successful response and "unreachable" otherwise - never a
chat-completion request, and never a "key not set" or "authentication failed" outcome, since a `custom`
provider has no key.

#### Scenario: Working
- **WHEN** the user tests a provider with a valid key
- **THEN** the system reports that the provider is working

#### Scenario: Authentication failed
- **WHEN** the provider rejects the key
- **THEN** the system reports "authentication failed", suggests checking the variable's value, and does not echo the key

#### Scenario: Unreachable
- **WHEN** the provider cannot be contacted
- **THEN** the system reports "unreachable" with the base URL used

#### Scenario: Azure provider with no deployments
- **WHEN** the user tests an `azure-openai` provider that has no registered deployments
- **THEN** the system reports that a deployment must be registered first, without attempting a call

#### Scenario: Azure provider with a deployment
- **WHEN** the user tests an `azure-openai` provider that has at least one enabled deployment
- **THEN** the system sends a minimal request to that deployment, validating the key, API version and deployment together, and reports the outcome

#### Scenario: Custom provider health check succeeds
- **WHEN** the user tests a `custom` provider whose health-check path responds successfully
- **THEN** the system reports that the provider is working, without ever attempting a chat-completion request

#### Scenario: Custom provider health check fails
- **WHEN** the user tests a `custom` provider that cannot be reached at its health-check path
- **THEN** the system reports "unreachable" with the base URL used
