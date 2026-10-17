# Tasks

## 1. Schema and migration

- [x] 1.1 Add `Agent.declared_models: Mapped[dict[str, str]]` (JSON, default `{}`) in
      `backend/app/models.py`, keeping `declared_model` for now, and verify the model imports and
      a fresh `alembic upgrade head` succeeds
- [x] 1.2 Write the Alembic migration backfilling `declared_models = {"default": declared_model}`
      for every existing row, and verify against a seeded test DB that every row's
      `declared_models` matches its prior `declared_model` after upgrade
- [x] 1.3 Verify `alembic downgrade -1` cleanly reverses the migration against the same seeded DB

## 2. Schemas and validation

- [x] 2.1 Change `AgentCreate`/`AgentSettingsUpdate` (`backend/app/schemas.py`) to
      `declared_models: dict[str, str]`, validate each value with `parse_ref()`, and verify a unit
      test rejects a malformed model reference in any entry, naming which key failed
- [x] 2.2 Verify a unit test rejects registration with an empty `declared_models` map
      ("At least one declared model is required")

## 3. Self-evaluator check

- [x] 3.1 Generalize `_check_no_self_evaluator` in `backend/app/repo.py` to loop over
      `declared_models.values()` and verify a unit test: an evaluator matching any one of several
      declared models is rejected, naming the conflicting model
- [x] 3.2 Verify a unit test: an evaluator matching none of the declared models is accepted
      ("An evaluator distinct from every declared model is accepted")
- [x] 3.3 Verify a unit test specifically for a two-model agent where the evaluator matches only
      the second declared model, not the first ("A multi-model agent is checked against all of
      its declared models, not just one")

## 4. API and persistence

- [x] 4.1 Update `create_agent`/settings-update functions in `repo.py` and `_agent_out()` in
      `backend/app/api/agents.py` to read/write `declared_models`, and verify an integration test
      round-trips a multi-entry map through create → read → update
- [x] 4.2 Drop the now-unused `declared_model` column in a follow-up migration once 4.1 is
      verified, and verify `alembic upgrade head` still succeeds on a DB carrying the backfilled
      `declared_models` data

## 5. Frontend

- [x] 5.1 Update the agent registration form to accept one model field per declared task type
      (starting with one row, add/remove rows) and verify a component test submits a multi-entry
      map
- [x] 5.2 Update the agent settings/detail view to display all declared models, not just one, and
      verify a component test renders a two-entry `declared_models` map correctly

## 6. Documentation and verification

- [x] 6.1 Update `agents/README.md` and any registration examples/scripts from `declared_model` to
      `declared_models`, and verify by following the doc to register a test agent with two
      declared models
- [x] 6.2 Verify the full `agent-registry` spec delta end to end: register a multi-model agent,
      attempt to save an evaluator matching the second model (rejected), save an evaluator
      matching neither (accepted), confirming no regression in the existing single-model
      ("default") registration path
