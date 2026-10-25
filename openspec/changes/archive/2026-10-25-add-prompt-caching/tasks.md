# Tasks

## 1. Backend: warm-up carries the skill prefix

- [x] 1.1 Thread the run's attached-skill snapshot into `Runner._warmup()` (mirroring how
      `_generate()` already receives it) and build its messages via
      `apply_skills(None, skills)` instead of a bare `None` system prompt; verify tests for a
      skill-equipped run (the warm-up request's system content contains the skill instructions)
      and a run with no skills attached (warm-up request is byte-for-byte unchanged from today)
- [x] 1.2 Verify the existing warm-up-disabled and non-warm-up-capable-model paths are unaffected
      (no new call shape when warm-up doesn't run at all)

## 2. Backend: capture and surface enterprise cached-token counts

- [x] 2.1 In `app/providers/openai.py`, read `usage.prompt_tokens_details.cached_tokens` and add
      it to the existing `provider={...}` dict passed to `final_chunk()`; verify a test with a
      usage payload that includes `cached_tokens` and one without (absent, not zero)
- [x] 2.2 In `app/core/metrics.py`'s `compute_cloud_metrics()`, copy `provider.get("cached_tokens")`
      into the returned metrics dict as `"cached_tokens"`, alongside `"prompt_tokens"`; verify a
      test asserting the field's presence/absence matches the provider payload
- [x] 2.3 Verify `app/providers/anthropic.py` and the local Ollama path are unaffected (no
      `cached_tokens` key ever appears for them) - this change does not request or fabricate
      Anthropic caching

## 3. Backend: explain cached-share differences when comparing runs

- [x] 3.1 In `app/core/summary.py`'s `_performance_notes()`, compute each side's median
      `cached_tokens / prompt_tokens` share for the model being compared (when both figures are
      present on that side) and append a note naming a meaningful difference (propose: a 20
      percentage-point threshold, matching the existing cold-start-share threshold); verify tests
      for: a difference large enough to note, a difference too small to note, and one or both
      sides missing cached-token data entirely (no note, never a fabricated 0%)
- [x] 3.2 Verify the existing four note types (cold-start share, digest, skill attachment,
      generation settings) are unaffected and can co-occur with the new one in the same list

## 4. Frontend: surface the new field where tokens are already shown

- [x] 4.1 Add the cached-token count to the per-result metrics line in
      `src/components/CaseDrilldown.tsx`, next to the existing prompt/output token figures, shown
      only when present; verify a component test for a result with `metrics.cached_tokens` set and
      one without
- [x] 4.2 Verify the new comparison note (task 3.1) renders through the existing `performance_notes`
      "Why?" disclosure in `src/components/ComparePanel.tsx` with no component change needed beyond
      what that disclosure already does for the other four note types - add a test case if the
      existing ones don't already exercise a fifth, unrecognized-shape note string

## 5. Documentation: live-agent prompt-caching guidance

- [x] 5.1 Write `agents/CACHING.md`: the three-provider mechanism table (Ollama automatic/
      prefix-KV, OpenAI-Azure automatic/observe-only, Anthropic opt-in via `cache_control`), the
      "stable instructions first, variable content last" pattern worked through using this
      platform's own `apply_skills()` as the concrete example, and the `repeats`-style
      full-response-cache trap named explicitly as a correctness warning, not a footnote; verify
      the file renders as valid Markdown and is linked from `agents/README.md`
- [x] 5.2 Add one short pointer line to `agents/README.md`'s existing index linking to
      `agents/CACHING.md`; verify the link resolves and no existing content in the README is
      duplicated rather than linked

## 6. End-to-end verification against the spec

- [x] 6.1 Live: start a skill-equipped run against two or more local cases with warm-up enabled,
      and verify the warm-up request (not just the first measured case) includes the skill
      instructions
- [ ] 6.2 Live (if an OpenAI or Azure OpenAI key is available): run a small suite against an
      enterprise model twice in quick succession with a long enough shared prompt, and verify at
      least one result records a non-absent `cached_tokens` figure
- [ ] 6.3 Live: compare two runs set up to differ meaningfully in cached-token share for the same
      model, and verify the comparison names that as a reason for the performance difference
