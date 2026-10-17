# Spec Delta

## MODIFIED Requirements

### Requirement: No silent deployment substitution
When the gateway cannot reach the provider deployment configured for a model group, it SHALL
return an error to the caller rather than silently substituting a different deployment, unless the
caller's request explicitly names a fallback model group to use for that call.

#### Scenario: An unreachable deployment surfaces as an error
- **WHEN** the provider deployment configured for a model group is unreachable and the request
  does not name a fallback group
- **THEN** the gateway returns an error to the caller rather than routing the request to an
  unrelated deployment

#### Scenario: A configured fallback is used and is visible to the caller
- **WHEN** the primary deployment for a model group is unreachable and the caller's request names
  a fallback model group
- **THEN** the gateway routes the request to the fallback group's deployment and the response
  identifies which deployment actually produced it

#### Scenario: A fallback is per-request, not gateway-wide
- **WHEN** a fallback is set only through the gateway's general configuration-update mechanism and
  not named on the individual request
- **THEN** the gateway is not guaranteed to apply it, so a caller that needs a fallback MUST name
  it on each request rather than relying on a gateway-wide default
