# Spec Delta

## ADDED Requirements

### Requirement: A skill is attachable to a single live agent invocation
The system SHALL let a skill's current instructions be fetched and attached to a single live
agent invocation (`agent-playground`), not only to every model a benchmark run evaluates. This
SHALL use the same stored skill content a benchmark run would attach, and SHALL NOT create or
modify any run, suite, or case record.

#### Scenario: A skill's instructions are fetched for one invocation
- **WHEN** a skill is selected for a single live agent invocation
- **THEN** that skill's current name, description and instructions are fetched, exactly the
  content a benchmark run attaching the same skill would receive

#### Scenario: Multiple skills are composed in selection order
- **WHEN** more than one skill is selected for the same invocation
- **THEN** their instructions are available for composition in the order they were selected

#### Scenario: Attaching a skill to one invocation creates no run artifact
- **WHEN** a skill is attached to a single live agent invocation
- **THEN** no benchmark run, suite, or case record is created or altered as a result

#### Scenario: A deleted skill cannot be newly attached
- **WHEN** a user attempts to attach a skill that has since been deleted
- **THEN** the attempt is rejected, naming that the skill no longer exists, consistent with a
  deleted skill no longer being offered for new use
