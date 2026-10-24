# Tasks

## 1. Data model

- [x] 1.1 Add a `Skill` model (`id`, `name` unique, `description`, `instructions`, `created_at`),
      mirroring `Suite`'s shape; write Alembic migration `0012` and verify
      `test_migration_matches_models`/`test_alembic_upgrade_head_creates_all_tables` pass

## 2. Backend: skills registry API

- [x] 2.1 Add repo functions (`create_skill`, `list_skills`, `get_skill`, `update_skill`,
      `delete_skill`) mirroring the equivalent `Suite` repo functions; verify unit tests for
      create/list/update/delete and the unique-name constraint
- [x] 2.2 Add `GET/POST /api/skills`, `GET/PATCH/DELETE /api/skills/{id}` mirroring
      `app/api/suites.py`'s shape (`SkillIn`/`SkillUpdate`/`SkillOut` schemas); verify tests for
      each endpoint, including the duplicate-name and empty-instructions rejections from the spec
- [x] 2.3 Add `POST /api/skills/import` parsing raw text content into name/description/instructions
      per design.md Decision 3 (first line or `# Name` heading -> name, next block -> description,
      remainder -> instructions); verify tests for a well-formed import, one with no instructions
      body (rejected the same way empty instructions already are), and one exceeding the documented
      size limit

## 3. Backend: attaching skills to a run

- [x] 3.1 Add `skill_ids: list[int] = []` to `RunConfig`; verify a run created with no skill ids
      behaves identically to today (existing run tests keep passing unmodified)
- [x] 3.2 Validate attached skill ids at run start the same way model selection is already
      validated - an unknown id refuses the run and names it; verify a test mirroring the existing
      "Unavailable model selected" scenario
- [x] 3.3 At run start, snapshot each attached skill's current `name`/`instructions` into
      `Run.config["skills"]` (design.md Decision 5); verify a test that edits or deletes a skill
      after a run completes and confirms the run's own stored config is unaffected
- [x] 3.4 Implement `apply_skills(system_prompt, skills) -> str` (design.md Decision 6: joins
      attached skills' instructions in attachment order, then the case's own system prompt if any)
      and wire it into the Runner's call to `build_messages`; verify tests for: no skills (prompt
      unchanged), one skill, multiple skills (both present, in order), and a skill combined with a
      case that already has its own system prompt (both present, skill(s) first)
- [x] 3.5 Verify every request in a skill-equipped run includes the attached skill(s)' instructions
      - a test running a multi-model, multi-case run with one attached skill asserts every sent
      message's system content contains it

## 4. Frontend: Skills page

- [x] 4.1 Add `useSkills`/`useSkillMutations` hooks and API types mirroring `useSuites`/
      `useSuiteMutations`
- [x] 4.2 Add a Skills page: list registered skills, a form to create one directly (name,
      description, Markdown instructions textarea), edit and delete actions - mirroring
      `SuitesPage.tsx`'s structure; verify component tests for list/create/edit/delete
- [x] 4.3 Add a real file-picker upload control (`<input type="file" accept=".md,text/markdown">`,
      read client-side via `FileReader`, submitted to the import endpoint) alongside direct
      authoring, per design.md Decision 2; verify a component test simulates selecting a file and
      confirms its content is submitted
- [x] 4.4 Add "Skills" to the main navigation. Decision made: nested under Run Evaluation setup's
      sub-tabs (Setup/Suites/Skills/History), not a new top-level item - consistent with the
      Suites/History precedent, since Skills is a registry that feeds into Run setup the same way
      Suites does.

## 5. Frontend: attaching skills in Run Evaluation setup

- [x] 5.1 Add a skill-selection control to `RunSetupPage.tsx` (multi-select from registered
      skills), alongside the existing judge-mode control, submitting `skill_ids` with the run
      creation request; verify a component test selects one or more skills and confirms they're
      included in the submitted run config
- [x] 5.2 Show which skills (if any) a completed/historical run used, reading from that run's own
      stored `config["skills"]` snapshot (not a live lookup against the registry), in the results/
      history view; verify a test with a since-deleted skill still shows the run's own snapshot

## 6. End-to-end verification against the spec

- [x] 6.1 Register a skill, start a run with it attached against a small suite and two local
      models, and verify live: the run completes normally, its stored config shows the skill
      snapshot, and its results show the usual quality/latency/tokens-per-sec metrics with no
      schema or behavior change beyond the longer prompt
- [x] 6.2 Run the same suite and models again with no skill attached, and verify the existing
      run-vs-run comparison dashboard shows both runs side by side with no new UI needed beyond
      what already exists for comparing any two runs
- [x] 6.3 Delete the skill used in 6.1's run and confirm that run's detail view is unaffected
      (still shows the skill's name and the instructions it used), while a new run can no longer
      select it
