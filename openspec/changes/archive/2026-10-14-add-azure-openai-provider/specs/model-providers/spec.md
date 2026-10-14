# Spec Delta

## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Register a provider by API-key environment variable
The system SHALL let the user register an enterprise provider by choosing its kind (`openai`, `anthropic`, or `azure-openai`), a unique name, and the **name of the environment variable that holds its API key**. It MAY accept an optional base URL for gateways and OpenAI-compatible endpoints. The system SHALL NOT accept, store or display the API key itself.

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
The system SHALL let the user test a provider, performing a lightweight authenticated request, and SHALL report the outcome as one of: working, key not set, authentication failed, rate limited, or unreachable, without revealing the key. For an `azure-openai` provider, which has no provider-wide endpoint to call, the test SHALL instead be run against one of its registered deployments, and SHALL report that a deployment must be registered first if none exists.

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
