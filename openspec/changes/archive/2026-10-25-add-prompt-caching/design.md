# Design

## Context

Three independent prompt-caching mechanisms exist across the providers this platform talks to, and
none of them is something this change "adds" in the sense of new infrastructure - the opportunity
is narrower and more surgical:

- **Ollama (local)**: automatic, server-side, no API flag. A loaded model's llama.cpp-based runner
  keeps a per-slot KV-cache of the last prompt it processed; a new request that shares a literal
  prefix with the cached one only re-evaluates the new suffix. This requires no code change to
  benefit from - it just requires (a) the same model to stay loaded across requests, and (b) the
  shared prefix to be byte-identical. Both are already true for a skill-equipped run: `runner.py`
  already executes model-grouped and sequentially (`app/core/runner.py`'s "for model -> for case ->
  for repeat" loop), and `apply_skills()` (`app/core/templates.py`) already places the skill
  instructions as a stable leading block, with the case's own (varying) content after it. A live
  check against this platform's own data confirms the effect is already happening: run
  `eval-7-skill-quality` (skill-equipped, 6 cases, 2 models) shows `prompt_eval_ms` dropping 2-3x
  from the first case to later ones for the same model, while `prompt_tokens` barely moves - the
  signature of a cache hit reported as pure time savings. The one concrete gap: `_warmup()`
  (`app/core/runner.py`) sends `build_messages(None, WARMUP_PROMPT)` - no skill prefix - so warm-up
  pre-loads the model's weights (`is_cold`) but does not pre-warm the prompt cache. The first
  *measured* case then silently absorbs that one-time cost.

- **OpenAI / Azure OpenAI**: also automatic, no API flag, for prompts over roughly 1024 tokens with
  a recently-seen shared prefix. The provider's usage payload already reports
  `prompt_tokens_details.cached_tokens` when it happens. `app/providers/openai.py`'s `_read()`
  currently reads `usage.get("prompt_tokens")` and `usage.get("completion_tokens_details")` but
  never looks at `prompt_tokens_details.cached_tokens` - the signal is on the wire today and
  discarded. Same situation, worse, on the Anthropic path (`app/providers/anthropic.py`): it reads
  and *sums* `cache_creation_input_tokens` + `cache_read_input_tokens` into one `in_tokens` total,
  destroying the distinction - but Anthropic caching can't be happening at all regardless, since
  `build_body()` sends `system` as a plain string, not the content-block array `cache_control`
  requires. Fixing Anthropic properly means changing the request shape, not just reading a field -
  out of scope here (see proposal.md).

- **The run-vs-run comparison** (`app/core/summary.py`'s `compare_runs`/`_performance_notes`)
  already explains a latency/tokens-per-sec difference with whatever signals it has: cold-start
  share, model digest, attached-skill difference, generation-setting difference
  (`num_ctx`/`max_output_tokens`/`think`). Once a cached-token count exists per result, it is a
  same-shaped addition to that same list of reasons - not a new mechanism.

- **Live agents**: `agents/*.py` (the reference agents) and any real deployed agent reach providers
  either directly (local/`custom`-kind) or through the separate `agent-llm-gateway` (LiteLLM, a
  third-party proxy configured in `gateway/config.yaml`, not code in this repo). This platform
  never constructs or sends a live agent's prompts - `reasoning_agent.py`'s four calls
  (classify/plan/solve/verify) are each a single bare user message today, nothing for a cache
  breakpoint to attach to; `chatbot.py` is a genuinely growing multi-turn conversation, the
  canonical caching case. Because this is the user's own code, not this platform's, the only thing
  this change can do here is document the pattern - not implement caching into a process this
  platform doesn't run.

## Goals / Non-Goals

**Goals:**
- Stop losing the first measured case's worth of Ollama cache benefit to an under-scoped warm-up
  request, for a skill-equipped run.
- Make OpenAI/Azure's already-automatic caching visible instead of silently discarded, so a
  cached-token count exists per enterprise result the same way prompt/output token counts already
  do.
- Extend the existing comparison-reasons mechanism with one more reason, using the same shape as
  the reasons already there - no new UI concept.
- Write down, once, the prefix-caching discipline a live-agent builder needs, grounded in exactly
  what this platform already does for its own runs (`apply_skills()`'s own ordering is the worked
  example).

**Non-Goals:**
- Anthropic `cache_control` support (needs a request-shape change, not a visibility fix - a
  separate, larger follow-on).
- Any new metric, column, or chart beyond what already exists for the other performance-note
  reasons and the other per-result metrics (prompt/output tokens). Cached tokens is one more figure
  next to those, not a new dashboard section.
- Any change to `RunConfig.repeats`'s semantics, or any full-response cache on the Runner's
  measured request path. `repeats` exists specifically to average out timing noise (`ConfigPanel`'s
  own text: "Repeats reduce timing noise"); a full-response cache would make repeat #2+ return
  near-instantly from cache, fabricating the exact measurement the feature exists to produce. This
  is a correctness boundary, not a style preference - it is the reason the guidance doc calls this
  out explicitly for live-agent builders too.
- Implementing anything inside `agents/*.py` or the LiteLLM gateway config. The guidance doc is
  documentation; it is not wired into any runtime code path, by design, because this platform does
  not control a live agent's own process.

## Decisions

**1. Thread the run's skill snapshot into `_warmup()`, mirroring how `_generate()` already gets
it.** `_execute_eval` already has `run` in scope at the warm-up call site; pass
`run.config.get("skills")` through to `_warmup(run_id, snap, cfg, skills)`, which builds
`build_messages(apply_skills(None, skills), WARMUP_PROMPT)` instead of
`build_messages(None, WARMUP_PROMPT)`. No new function: `apply_skills()` and `build_messages()`
already exist and already handle the "no skills" case as a no-op (returns the input unchanged), so
a run with nothing attached is byte-for-byte unaffected. *Alternative considered*: a separate
pre-warm step that sends the skill prefix without sending the warm-up prompt at all - rejected,
because it would need its own request (another chat call) where folding the prefix into the
existing warm-up request costs nothing extra.

**2. Capture `cached_tokens` through the existing `provider` passthrough dict, not a new
parameter.** `final_chunk()` (`app/providers/cloud.py`) already accepts a free-form `provider: dict`
that `compute_cloud_metrics()` reads selectively (`reasoning_tokens`, `retry_wait_ms`,
`model_version`, etc. all travel this way already). Add `"cached_tokens":
details.get("cached_tokens")` to `openai.py`'s existing `provider={...}` literal (reading
`usage.get("prompt_tokens_details", {}).get("cached_tokens")`), and have
`compute_cloud_metrics()` copy `provider.get("cached_tokens")` into its own returned dict next to
`"prompt_tokens"`. No change to `final_chunk()`'s signature. *Alternative considered*: a new typed
column on `Result` (mirroring `output_tokens`) - rejected for the same reason `prompt_tokens`
itself was never promoted to a typed column: it isn't used for sorting/aggregation, only for
explaining one request at a time and feeding the comparison's reason-list, so the existing
`metrics` JSON blob is the right level, consistent with precedent.

**3. `_performance_notes()` gains one more heuristic, same shape as the existing four.** Compute a
per-run, per-model "cached share" (`cached_tokens / prompt_tokens`, using the *median* result the
same way other per-model performance figures are already summarized) for each side being compared;
if the two shares differ by a threshold (proposed: 20 percentage points, matching the existing
cold-start-share threshold already used for that reason), append a note naming it. Absent data on
either side (local models, or a provider that never reported `cached_tokens`) means no note for
that pair - never a fabricated "0% cached" claim. *Alternative considered*: expose raw
`cached_tokens` counts as a new leaderboard/comparison column instead of (or in addition to) a
note - deferred; a note is additive and low-risk, a new persistent column is a bigger, separate
decision (and most of the time a cache share is only interesting *because* a latency delta needs
explaining, which is exactly what a note already does for the other three reasons).

**4. The guidance document lives at `agents/CACHING.md`.** It sits next to the reference agents it
illustrates (`agents/README.md` already exists as their index) rather than under `openspec/` or a
generic top-level `docs/`, because its audience is "someone about to write or operate an agent
against this platform," the same audience `agents/README.md` already serves. It is prose, not
spec: no runtime code reads it, and it is explicitly cross-referenced from `agents/README.md`'s
existing index rather than duplicating the index's own content. *Alternative considered*: a new
`## Prompt caching` section inside `agents/README.md` directly - rejected only because the README
is already long and this is substantial enough (three providers, the `repeats`-style trap, worked
examples from `apply_skills()`) to read better as its own linked page.

## Risks / Trade-offs

- [The 20-point cached-share threshold in Decision 3 is a guess, not derived from data] -> it
  mirrors the existing cold-start-share threshold's own role (a coarse "worth mentioning" cutoff,
  not a precise statistical claim); tasks.md includes a test asserting the note appears/doesn't
  appear at the threshold's boundary, so the exact number stays easy to revisit later without
  touching the mechanism.
- [Surfacing `cached_tokens` might read as "the platform supports prompt caching" when really only
  OpenAI/Azure's own automatic behavior is being observed] -> the proposal and the guidance doc both
  say this explicitly: nothing is requested or configured for OpenAI/Azure, only reported; Anthropic
  is called out by name as the one provider where this is currently a true no-op (no caching is
  happening, and this change does not make it start).
- [A live-agent builder reads the new doc and reaches for a full-response cache for "better latency
  numbers" during their own benchmarking] -> the doc states the `repeats`/timing-fabrication trap
  as its own named warning, not a footnote, precisely because it's the one way "caching" quietly
  becomes "lying about measurements."

## Migration Plan

Additive only. No schema change (metrics already live in `Result.metrics`, a free-form JSON
column); no new config; no new RunConfig field. A run that attaches no skill, or uses only local
models, or compares two runs with no cache signal on either side, is byte-for-byte unaffected -
every new scenario in the spec deltas has a matching "unchanged when absent" scenario. Rollback is
reverting the warm-up/metrics/notes code and deleting the doc; nothing else depends on them.
