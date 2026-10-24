# Design

## Context

The benchmark Runner (`backend/app/core/runner.py`) executes sequentially, model-grouped: for each
selected model, for each case, for each repeat, it calls `build_prompt(category, prompt, config)`
then `build_messages(system_prompt, sent_prompt)` (`app/core/templates.py`) to produce the message
list it sends via `OllamaClient.chat_stream()`/the enterprise `ProviderBackend.chat_stream()`.
Neither code path has any concept of tools, function schemas, or multi-turn conversations today -
`chat_stream` takes `messages` and streams back `message.content`/`message.thinking` only.

`RunConfig` (`app/schemas.py`) is a flat Pydantic model of per-run settings (`temperature`, `seed`,
`judge_model`, etc.) persisted verbatim into `Run.config` (a plain `JSON` column -
`app/models.py:130`). This is the same place `judge_model`/`judge_reasoning` already live, so a new
"skills" setting fits this exact shape.

The `Suite` registry (`model.py:89`, `app/api/suites.py`) is the closest existing precedent for a
named, user-authored, CRUD-able entity with an import path: `POST /suites/import` takes raw file
content as a string and parses it; the frontend's importer reads a pasted/typed block, not an
actual file picker. Model/suite immutability-at-run-time is already an established principle:
`test-suites`' "Editing a suite does not alter past runs" and `evaluation-runs`' `ModelSnapshot`
both capture a copy of mutable registry state at the moment a run starts, rather than a live
foreign key to it.

## Goals / Non-Goals

**Goals:**
- Let a user author or upload a named, Markdown-instruction skill, and attach one or more to a
  run so every model's prompt in that run includes them.
- Keep the change additive and small: no change to the Runner's execution loop, retry logic,
  cancellation, live progress, or scoring - a skill-equipped run is executed exactly like any other
  run, just with a longer prompt.
- Make a skill-equipped run fully reproducible and comparable, consistent with how the platform
  already treats runs: editing or deleting a skill later never changes what a past run shows it
  used (same principle `test-suites` already applies to suites/cases).

**Non-Goals:**
- Executable or tool-backed skills (MCP-style function calling, code execution). A skill is text
  injected into a prompt; the model is never given a callable tool and the system never runs
  anything from a skill's content. (If this is wanted later, it is a materially different, larger
  change - see Risks.)
- Per-case or per-model skill attachment, or multiple skill *sets* compared within one run. A
  run's attached skills apply to every model and every case in that run, uniformly - the same
  granularity `judge_model`/`think`/etc. already have.
- Any new scoring dimension (e.g. "did the model follow the skill"). Quality is judged exactly as
  it already is today; a skill-equipped run and a bare run are simply two runs, compared with the
  existing run-vs-run dashboard.
- Skill content linting/validation beyond "non-empty, is text". The platform does not evaluate
  whether a skill's instructions are good prompt engineering.

## Decisions

**1. A new `Skill` table/registry, modeled directly on `Suite`.** Columns: `id`, `name` (unique),
`description`, `instructions` (the Markdown body), `created_at`. No `is_builtin`-equivalent is
needed (no starter skill ships with the platform). CRUD mirrors `suites.py` exactly: `GET/POST
/api/skills`, `GET/PATCH/DELETE /api/skills/{id}`, `POST /api/skills/import`.

**2. Upload is a real file picker, not a paste box.** The proposal's "upload from the user's own
machine" is taken literally: the frontend's skill-creation form includes an `<input type="file"
accept=".md,text/markdown">` that reads the file client-side (`FileReader`) and submits its text
content to the same import endpoint `Suite`'s import already uses a paste box for - so both
authoring paths (write directly, or pick a file) land on one endpoint and one parsing rule.
*Alternative considered*: a paste-box only, matching `Suite`'s current importer exactly - rejected
because the proposal explicitly asked for uploading a file from disk, not just pasting its
contents.

**3. Uploaded/pasted content parses as: first line (or a `# Name` heading) -> `name`, next block ->
`description`, remainder -> `instructions`** - a deliberately simple, documented convention (not
YAML frontmatter, not a schema to validate against) consistent with "skills are plain Markdown,
not a structured format the system parses deeply." A size limit (e.g. a few hundred KB) and a
content-type/extension check (`.md` or `text/*`) reject anything else before storage - this is the
system's only validation surface, since instructions are never executed. *Alternative considered*:
YAML frontmatter (`name:`/`description:` keys, closer to how Claude's own Skill format works) -
deferred; it adds a parsing dependency and a stricter contract for a first phase whose only goal is
"get text into a prompt," and can be layered on later without breaking the simple convention (a
file without frontmatter still parses under the simple rule).

**4. `RunConfig` gains `skill_ids: list[int] = []`.** Validated at run-start the same way model
selection already is: an unknown id refuses the run and names it (mirrors evaluation-runs' existing
"Unavailable model selected" scenario).

**5. Skill content is snapshotted into `Run.config` at run-start, not referenced live.** When a run
starts, each attached skill's current `name`+`instructions` is copied into
`config["skills"]: [{"id", "name", "instructions"}, ...]` alongside the existing flat settings -
the same immutability principle `test-suites`/`ModelSnapshot` already use. No new column: `Run.config`
is already a free-form JSON blob holding exactly this kind of per-run settings snapshot.

**6. Skill instructions are prepended to the case's own system prompt, not appended to the user
message.** The Runner's call to `build_messages(system_prompt, sent_prompt)` changes to
`build_messages(apply_skills(system_prompt, run.config_skills), sent_prompt)`, where `apply_skills`
joins each attached skill's instructions (in attachment order) with a clear delimiter, followed by
the case's own `system_prompt` if it has one. `build_messages`'s own signature is unchanged - this
is a new, small helper composing what gets passed into it, not a change to message-building itself.
*Alternative considered*: append to the user-role `sent_prompt` instead - rejected; skills are
framing/instructions, which is what the system role already exists for, and keeping them there
means a skill never collides with `sent_prompt`'s own category-suffix template logic.

**7. No new column on `Result` for the effective prompt.** `Result.sent_prompt` keeps meaning
exactly what it already means (the case's own prompt + category suffix); the skill content a run
used is fully reconstructable from `Run.config["skills"]` (identical for every request in that run)
plus the already-recorded `RunCase.system_prompt`. Reproducibility doesn't need a third, redundant
copy of the same text on every single result row.

## Risks / Trade-offs

- [A large or low-quality skill could noticeably inflate every request's prompt tokens and latency
  in a run, which could read as a measurement artifact rather than the intended comparison] ->
  this is the explicit point of the feature (showing the cost of equipping a model with guidance),
  but the Skills page should show instruction length/approximate token count up front so the user
  isn't surprised by it after a long run.
- [Tier A (prompt-only) may feel like it understates what "skills" usually means once tool-backed
  skills (Tier B) are considered] -> explicitly scoped out this phase (see Non-Goals); Tier B would
  need the Runner to support mid-stream tool calls, a real execution/sandboxing story, and new
  performance-metrics attribution for multi-round-trip requests - a substantially larger, separate
  change, not a natural follow-on PR to this one.
- [A skill upload is still user-supplied text rendered back into the UI (name, description,
  instructions)] -> treated like every other user-authored text in this platform (suite
  prompts, case text) - rendered as plain text/Markdown, never executed or interpreted as markup
  that could inject scripts; no new trust boundary beyond what already exists for suite content.

## Migration Plan

Additive only: a new table, a new API surface, a new optional `RunConfig` field (defaults to
`[]`, so every existing run and every existing API caller is unaffected), and a new frontend page
plus one new control on the existing Run Evaluation setup page. No existing data migrates; no
existing behavior changes when no skill is attached - the default, unchanged path for every run
that doesn't use this feature. Rollback is removing the new table/endpoints/UI; nothing else
depends on them.
