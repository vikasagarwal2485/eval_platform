# agent-playground Specification

## Purpose

Lets a user run one of the platform's real, registered agent scripts directly from the browser -
choosing a system prompt, attached skills, and a one-shot task - and watch the resulting
conversation stream live, with no terminal, hand-copied credential, or manual CLI invocation.

## Requirements

### Requirement: An agent flavor catalog describes runnable agent scripts
The system SHALL ship a static catalog of runnable agent flavors (at minimum `chatbot`,
`reasoning`, `router`), each naming its entrypoint command, the task-scoped model-group slots it
declares (matching `agent-registry`'s declared-models shape for that kind), and that it accepts
`--system-prompt`, `--skill` (repeatable) and `--task` flags. The catalog SHALL be read-only
reference data, distinct from any registered `Agent` row - many agents may be registered against
the same flavor.

#### Scenario: The three reference flavors are catalogued
- **WHEN** the agent catalog is read
- **THEN** it lists `chatbot`, `reasoning`, and `router`, each with its entrypoint command and the
  task-scoped model-group slots that kind's registration requires

#### Scenario: A catalog entry's task slots match its kind's declared-models shape
- **WHEN** a user registers an agent of a cataloged flavor
- **THEN** the declared-models keys offered for that registration are exactly the task slots the
  catalog names for that flavor's kind

#### Scenario: The catalog is not a substitute for registration
- **WHEN** the catalog lists a flavor
- **THEN** no agent exists for it until a user registers one against that flavor; the catalog entry
  itself is never shown as a runnable agent

### Requirement: An agent can be marked playground-eligible at registration
The system SHALL let the user mark a registered agent as playground-eligible, selecting the
catalog flavor its script was registered as. Marking an agent playground-eligible SHALL require
that its `kind` matches the selected flavor's kind, and SHALL be reversible (a user MAY later
unmark it).

#### Scenario: Eligibility requires a matching flavor
- **WHEN** the user marks an agent playground-eligible and selects a catalog flavor
- **THEN** the request is rejected unless that flavor's kind matches the agent's own `kind`

#### Scenario: A non-eligible agent is registered exactly as before this change
- **WHEN** the user registers or already has an agent and never marks it playground-eligible
- **THEN** its registration, credential handling, and behavior are unaffected by this capability

#### Scenario: Unmarking eligibility leaves the registration itself intact
- **WHEN** the user unmarks a previously playground-eligible agent
- **THEN** the agent's name, kind, declared models and history are unchanged, and it can no longer
  be spawned from the playground until re-marked eligible

### Requirement: A playground-eligible agent's spawn credentials are stored reversibly
For a playground-eligible agent only, the system SHALL store a usable copy of its platform ingest
token and a gateway virtual key scoped to its own synced model groups, encrypted at rest - a
deliberate, scoped exception to the hash-only, shown-once convention every other credential in the
platform follows (`agent-registry`'s ingest-token handling, `Provider.key_env`). Neither credential
SHALL be returned in plaintext by any read API; both SHALL be usable only by the spawn mechanism
itself, and SHALL be rotatable on demand.

#### Scenario: Marking an agent eligible captures its spawn credentials
- **WHEN** the user marks an agent playground-eligible
- **THEN** the platform retains a reversibly-stored copy of its ingest token and mints and stores a
  gateway virtual key scoped to its currently-synced model groups

#### Scenario: Stored credentials never appear in a read response
- **WHEN** a playground-eligible agent's registration is read back through any API
- **THEN** the response shows only the ingest token's existing display prefix and whether a
  gateway key is configured, never either credential's usable value

#### Scenario: A non-eligible agent retains today's hash-only behavior
- **WHEN** an agent is not playground-eligible
- **THEN** the platform never stores a reversible copy of its ingest token, exactly as before this
  change

#### Scenario: Credentials can be rotated on demand
- **WHEN** the user requests rotation of a playground-eligible agent's spawn credentials
- **THEN** a new ingest token and a newly-minted gateway virtual key replace the stored ones, and
  the previous ingest token is invalidated the same way any other rotation invalidates it

#### Scenario: A changed declared model re-mints the stored gateway key
- **WHEN** a playground-eligible agent's declared models change in a way that changes its synced
  gateway model groups
- **THEN** the stored gateway virtual key is re-minted to cover the updated groups before the next
  spawn is accepted

### Requirement: Spawning runs the agent's actual catalog script as a one-shot process
The system SHALL let the user spawn a playground-eligible agent by supplying a system prompt, zero
or more attached skills, and a task. Spawning SHALL launch that agent's real catalog entrypoint as
a subprocess - never a reimplementation of its logic - wired with its stored declared models,
fallback groups, decrypted spawn credentials, and the supplied prompt/skills/task. The process
SHALL run the one task, emit its turn through the existing ingest path exactly as a terminal-run
instance of the same script would, and exit.

#### Scenario: Spawning launches the real script
- **WHEN** the user spawns a playground-eligible agent with a system prompt and a task
- **THEN** the platform launches that agent's cataloged entrypoint command as a subprocess with the
  supplied prompt and task, not a separate reimplementation of the flavor's behavior

#### Scenario: A spawned turn is indistinguishable from a terminal-run one
- **WHEN** a spawned agent's turn completes
- **THEN** it appears in that agent's conversation history and evaluation pipeline identically to a
  turn produced by manually running the same script from a terminal

#### Scenario: Only a playground-eligible agent can be spawned
- **WHEN** the user attempts to spawn an agent that is not playground-eligible
- **THEN** the request is rejected, naming that the agent is not playground-eligible

#### Scenario: A second spawn is rejected while one is already running
- **WHEN** the user requests a spawn for an agent that already has a spawn in progress
- **THEN** the new request is rejected, naming that the agent is currently busy, rather than
  starting a second concurrent process for the same agent

#### Scenario: A spawn failure is surfaced, not silently swallowed
- **WHEN** the spawned process fails to start, crashes, or exits without emitting a turn
- **THEN** the user is shown that the spawn failed and why, rather than the UI waiting indefinitely
  or reporting success

### Requirement: A spawn's attached skills are composed into its submitted system prompt
When the user selects one or more skills for a spawn, the system SHALL fetch each selected skill's
current instructions (`skills-registry`) and prepend them, in the order selected, to the
user-supplied system prompt before the spawn is launched.

#### Scenario: Selected skills precede the custom system prompt
- **WHEN** the user selects skills A and B, in that order, and supplies a custom system prompt
- **THEN** the spawned process's effective system prompt is skill A's instructions, then skill B's,
  then the user's own prompt text, in that order

#### Scenario: No skill selected leaves the prompt unchanged
- **WHEN** the user spawns an agent with no skills selected
- **THEN** the spawned process's system prompt is exactly the user-supplied text, with nothing
  prepended

### Requirement: A spawn's progress streams live to the UI
The system SHALL let the user watch a spawn's turn stream live, reusing the platform's existing
per-agent live-event feed, from the moment the process starts until its turn completes or it fails.

#### Scenario: The user watches their own spawn complete
- **WHEN** the user spawns an agent and keeps the playground page open
- **THEN** the turn's start, any intermediate progress the existing live feed already reports, and
  its completion are shown in the page's live-conversation panel without a manual refresh

#### Scenario: Closing and reopening the page still shows the result
- **WHEN** the user navigates away before a spawn finishes and returns to the agent afterward
- **THEN** the completed turn appears in that agent's ordinary conversation history, the same way
  any other live turn would
