# model-providers Specification

## Purpose

Lets the user register enterprise model providers (OpenAI, Anthropic) and their models without the application ever handling the API key itself, so hosted models can be selected for evaluation and judging next to local ones.

## Requirements

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

### Requirement: Register an Azure OpenAI provider
The system SHALL let the user register a provider of kind `azure-openai`, which additionally requires a base URL (the Azure resource endpoint) and an API version. Unlike `openai` and `anthropic`, these two fields are required, not optional, because Azure OpenAI has no shared default endpoint and every call must name an API version.

#### Scenario: Register with required fields
- **WHEN** the user registers an `azure-openai` provider with a base URL and an API version
- **THEN** the provider appears in the provider list with its kind, base URL, API version, and key status

#### Scenario: Base URL required
- **WHEN** the user submits an `azure-openai` provider without a base URL
- **THEN** the system rejects it, explaining that the Azure resource endpoint is required for this kind

#### Scenario: API version required
- **WHEN** the user submits an `azure-openai` provider without an API version
- **THEN** the system rejects it, explaining that an API version is required for this kind

#### Scenario: API version applies to every call
- **WHEN** the user later changes an `azure-openai` provider's API version
- **THEN** every subsequent call to that provider's deployments uses the new value

### Requirement: API keys are never stored or exposed
The system SHALL read a provider's API key from the process environment only at the moment it makes a call. The key value SHALL NOT be written to the database, run configuration, exports, logs, or API responses, and SHALL NOT appear in any error message shown to the user or recorded with a result.

#### Scenario: Not in any API response
- **WHEN** the client lists or fetches providers, models or runs
- **THEN** no response contains a key value; providers expose only the variable name and a boolean "key available"

#### Scenario: Not in stored or exported data
- **WHEN** a run that used an enterprise model is stored, exported as CSV or JSON, or re-run
- **THEN** none of the stored or exported data contains the key value

#### Scenario: Errors are redacted
- **WHEN** a provider's error response or a transport error would contain the key value
- **THEN** the message stored and shown replaces it with a redaction marker

#### Scenario: Key not passed in URLs
- **WHEN** the system calls a provider
- **THEN** the key is sent only in the provider's authentication header, never in a URL or query string

### Requirement: Report key availability
The system SHALL report for each provider whether its key environment variable is currently set to a non-empty value, and SHALL make models of a provider without a key unavailable for selection while explaining why.

#### Scenario: Key present
- **WHEN** the variable named by a provider is set in the environment the application was started with
- **THEN** the provider is shown as ready and its enabled models are selectable

#### Scenario: Key missing
- **WHEN** the variable is not set or is empty
- **THEN** the provider is shown as "key not set" naming the variable, its models are listed as unavailable with that reason, and starting a run that needs them is refused

#### Scenario: Key added after start
- **WHEN** the user exports the variable after the application has started
- **THEN** the UI explains that the application must be restarted from an environment that contains the variable

### Requirement: Acknowledge data sharing when registering a provider
Registering a provider SHALL require the user to acknowledge that prompts and model outputs used in evaluations (including answers from other models when the provider is used as a judge) are sent to that provider. The acknowledgment SHALL be recorded with the provider.

#### Scenario: Acknowledgment required
- **WHEN** the user submits a provider without acknowledging data sharing
- **THEN** the system rejects the registration and explains what is sent to the provider

#### Scenario: Acknowledgment recorded
- **WHEN** the user registers a provider with the acknowledgment
- **THEN** the provider record shows that it was acknowledged and when

### Requirement: Register and manage a provider's models
The system SHALL let the user add models to a provider by typing a model id, enable or disable each model, mark a model as a reasoning model (optionally with a reasoning-effort level), and remove a model. A model id SHALL be unique within its provider. For an `azure-openai` provider, the model id SHALL be presented as the Azure **deployment name**.

#### Scenario: Add a model by id
- **WHEN** the user adds model id `gpt-4o` to an OpenAI provider
- **THEN** the model appears under that provider and becomes selectable in Run setup once the key is available

#### Scenario: Duplicate model rejected
- **WHEN** the user adds a model id that already exists for the provider
- **THEN** the system rejects it without creating a duplicate

#### Scenario: Disable a model
- **WHEN** the user disables a model
- **THEN** it is no longer offered for new runs or as a judge, and past runs that used it stay viewable

#### Scenario: Remove a model
- **WHEN** the user removes a model that past runs used
- **THEN** the runs keep their recorded results and show the model as removed

#### Scenario: Deployment name terminology
- **WHEN** the user adds or views a model under an `azure-openai` provider
- **THEN** the field and its display are labelled "deployment name" rather than "model id"

#### Scenario: Set reasoning effort
- **WHEN** the user marks a model as a reasoning model and sets a reasoning-effort level
- **THEN** the level is stored with the model and applied to every run that uses it

### Requirement: Discover a provider's models
The system SHALL let the user fetch the list of models offered by a provider, using the provider's key, and add chosen models to the registry with one action. Failure to fetch SHALL NOT prevent adding models by typing their ids. This action SHALL NOT be offered for an `azure-openai` provider, since listing deployments requires a separate management-plane credential this system does not hold; the UI SHALL explain this and point the user at adding a deployment name directly.

#### Scenario: Fetch and add
- **WHEN** the user fetches the models of a provider whose key is available and selects two of them
- **THEN** both models are registered under that provider

#### Scenario: Already registered models are marked
- **WHEN** a fetched list contains a model that is already registered
- **THEN** it is shown as already added and cannot be added twice

#### Scenario: Fetch fails
- **WHEN** the fetch fails because the key is invalid, the provider is unreachable, or the key is missing
- **THEN** the user sees an actionable, redacted error and can still add a model by typing its id

#### Scenario: Not available for Azure OpenAI
- **WHEN** the user opens an `azure-openai` provider
- **THEN** no fetch-models action is offered, and the screen explains that Azure deployments cannot be auto-discovered and must be added by name

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

### Requirement: Edit and remove providers
The system SHALL let the user rename a provider's display settings (variable name, base URL) and remove a provider. Removing a provider SHALL remove its registered models from selection while past runs remain viewable. A provider used by a queued or running run SHALL NOT be removed.

#### Scenario: Change the variable name
- **WHEN** the user changes the environment variable name of a provider
- **THEN** key availability is re-evaluated against the new variable

#### Scenario: Remove a provider with history
- **WHEN** the user removes a provider whose models were used in past runs
- **THEN** the provider and its models disappear from selection and past runs still show their results and the provider and model names they used

#### Scenario: Provider in use
- **WHEN** the user tries to remove a provider that a queued or running run is using
- **THEN** the system refuses and explains that the run must finish or be cancelled first

### Requirement: Providers screen
The web UI SHALL provide a Providers screen listing registered providers with their status and models, and forms to add a provider, add or fetch models, test a connection, enable or disable models, and remove providers. It SHALL show meaningful empty, loading and error states and SHALL be keyboard-operable with accessible labels.

#### Scenario: Empty state
- **WHEN** no provider is registered
- **THEN** the screen explains what a provider is, that only the key's variable name is entered, and how to set the variable before starting the application

#### Scenario: Status is visible
- **WHEN** providers exist
- **THEN** each shows its kind, variable name, key status (ready or not set), acknowledgment, and model count

#### Scenario: No secret entry field
- **WHEN** the user opens the add-provider form
- **THEN** there is no field that accepts an API key value
