# Spec Delta

## ADDED Requirements

### Requirement: A playground-eligible agent's gateway virtual key is minted and kept in sync
When an agent is marked playground-eligible (`agent-playground`), the system SHALL mint a gateway
virtual key scoped to exactly that agent's own currently-synced model groups (primary and
fallback), store it for later spawn use, and re-mint it whenever those synced groups change, so
the stored key never grants access to a group the agent no longer declares, nor lacks access to
one it just gained.

#### Scenario: Marking an agent eligible mints its first key
- **WHEN** an agent with already-synced model groups is marked playground-eligible
- **THEN** the system mints a gateway virtual key allow-listing exactly that agent's current
  primary and fallback groups and stores it

#### Scenario: A changed declared model re-mints the key before next use
- **WHEN** a playground-eligible agent's declared models change, adding, removing or altering a
  task's gateway group
- **THEN** the system re-mints the stored virtual key to allow-list the updated set of groups,
  discarding the previous key's value

#### Scenario: A non-eligible agent never gets a key minted
- **WHEN** an agent is not playground-eligible
- **THEN** the system never calls the gateway's key-minting endpoint on its behalf, and an operator
  wishing to run it manually continues to mint and manage its virtual key by hand, exactly as
  before this change

#### Scenario: A minting failure is reported, not silently swallowed
- **WHEN** the gateway is unreachable or rejects a key-minting attempt for a playground-eligible
  agent
- **THEN** the triggering request (marking eligible, or the declared-model change) still succeeds,
  and the response reports that key minting did not succeed, mirroring how a model-group sync
  failure is already reported without blocking the request

#### Scenario: Explicit rotation re-mints and discards the previous key
- **WHEN** the user explicitly requests credential rotation for a playground-eligible agent
- **THEN** the system mints a new virtual key scoped to its current groups and discards the
  previous key's value, the same way an ingest-token rotation invalidates the previous token
