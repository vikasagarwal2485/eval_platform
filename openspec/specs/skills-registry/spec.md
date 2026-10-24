# skills-registry Specification

## Purpose

Lets the user author or upload named, Markdown-instruction "skills" that a benchmark run can later
attach to every model it evaluates, so models can be compared with and without the same guidance.

## Requirements

### Requirement: Register a skill by writing it directly
The system SHALL let the user create a skill by giving it a unique name, a short description, and
Markdown-formatted instructions. A skill SHALL NOT carry executable code, a tool/function schema,
or anything the system itself ever runs - its content is text injected into a model's prompt, never
invoked as code.

#### Scenario: Create a skill
- **WHEN** the user creates a skill named `step-by-step` with a description and Markdown instructions
- **THEN** the skill appears in the skills list with its name, description, and instructions stored

#### Scenario: Duplicate name rejected
- **WHEN** the user creates a skill whose name matches an existing skill
- **THEN** the system rejects it with a validation error and creates nothing

#### Scenario: Empty instructions rejected
- **WHEN** the user submits a skill with empty instructions
- **THEN** the system rejects it with a validation error identifying the offending field

### Requirement: Upload a skill from a file
The system SHALL let the user upload a skill from a Markdown (`.md`) file on their own machine, in
addition to writing one directly in the UI, parsing the same name/description/instructions shape
from the file's content.

#### Scenario: Upload a well-formed file
- **WHEN** the user uploads a `.md` file containing a skill name, description and instructions
- **THEN** the system creates the skill with that content, identically to one authored directly in the UI

#### Scenario: Upload a file with no instructions body
- **WHEN** the user uploads a file that parses to empty instructions
- **THEN** the system rejects the upload with the same validation error direct authoring would give,
  and creates nothing

#### Scenario: Upload an oversized or non-Markdown file
- **WHEN** the user selects a file that is not Markdown/plain text, or exceeds the documented size
  limit
- **THEN** the system rejects the upload before storing anything and explains why

### Requirement: List, view and edit a registered skill
The system SHALL let the user list all registered skills, view one's full name, description and
instructions, and edit any of those fields on an existing skill.

#### Scenario: Edit instructions
- **WHEN** the user edits a skill's instructions and saves
- **THEN** the skill's stored instructions are updated, and any run already using it keeps the
  version of the instructions it was run with (see `evaluation-runs`: a run's own configuration is
  immutable once it completes)

### Requirement: Remove a skill
The system SHALL let the user delete a registered skill. Deleting a skill SHALL NOT alter any
existing run's own stored configuration or results - a run that used a since-deleted skill keeps
showing the skill content it actually used at the time.

#### Scenario: Delete an unused skill
- **WHEN** the user deletes a skill that no run has ever used
- **THEN** the skill is removed from the registry and no longer offered for new runs

#### Scenario: Delete a skill a past run used
- **WHEN** the user deletes a skill that a completed run attached
- **THEN** the skill is removed from the registry for future use, and that run's own record keeps
  the exact skill content it was executed with, unaffected by the deletion
