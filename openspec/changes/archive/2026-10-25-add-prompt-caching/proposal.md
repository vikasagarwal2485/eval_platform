# Proposal

## Why

Skills (`add-run-skills`) inject the same, often-long instructions into every request a run sends
for a given model, and the existing run-vs-run comparison already tries to explain why latency/
tokens-per-sec moved between two runs (cold-start share, model digest, attached skills, generation
settings). A live check
against this platform's own data (run `eval-7-skill-quality`, a skill-equipped run, 6 cases, 2
models) shows Ollama is *already* reusing the cached prompt prefix from the second case onward for
the same model - `prompt_eval_ms` drops 2-3x case-to-case while `prompt_tokens` barely moves. That
speed is currently being left on the table for the first case (warm-up doesn't include the skill
prefix, so it isn't pre-cached), and the equivalent provider-side signal for enterprise models
(OpenAI/Azure OpenAI report `cached_tokens` in their usage payload; this platform already reads and
discards it) is never captured or surfaced - so a user comparing two runs sees a latency change
with no way to tell whether caching explains it. Finally, the same prefix-stability discipline that
makes Ollama's caching work (skill/instructions text as a stable leading block, varying content
last) is relevant to anyone building a live agent against this platform's conventions, and nothing
documents it today.

## What Changes

- The Runner's per-model warm-up request (when warm-up is enabled and the model supports it) now
  includes the run's attached skill(s) instructions, the same way every measured request already
  does - so the one-time cost of processing that prefix is absorbed into the already-excluded
  warm-up phase instead of landing on the first measured case.
- Enterprise request metrics (OpenAI, Azure OpenAI) capture the provider-reported cached-prompt-
  token count instead of discarding it, and expose it alongside the existing prompt/output token
  counts already recorded per result.
- The existing run-vs-run comparison's performance-difference explanation gains a new reason: when
  one run's measured cached-token share differs meaningfully from the other's, that is surfaced as
  a plausible cause of a latency/tokens-per-sec change, the same way a cold-start or digest
  difference already is.
- A new guidance document (not a runtime feature) explains the prefix-caching pattern for anyone
  building or operating a live agent against this platform's conventions: keep stable instructions
  as a leading, byte-identical system block; for Anthropic, that requires explicit `cache_control`
  breakpoints (not automatic, unlike Ollama/OpenAI/Azure); never rely on a *full-response* cache for
  anything whose timing is being measured, since that would silently fabricate a result instead of
  skipping real, equivalent work.
- Anthropic prompt caching itself (content-block `system` + `cache_control`) is explicitly out of
  scope for this change - it needs new request-shape plumbing, not a visibility fix, and is a
  natural follow-on rather than part of this one.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `performance-metrics`: "Per-request metrics" gains a scenario recording cached-prompt-token
  counts for enterprise requests when the provider reports them.
- `evaluation-runs`: "A run can attach one or more skills to every model it evaluates" gains a
  scenario covering the warm-up request also carrying the attached skill(s)' instructions.
- `results-dashboard`: "Run history and comparison across runs" gains a scenario where a cached-
  token-share difference between the two runs is surfaced as a possible reason for a performance
  difference, alongside the reasons already shown there.

## Impact

- Backend: `app/core/runner.py` (`_warmup`), `app/providers/openai.py` (cached-token capture),
  `app/core/metrics.py` (`compute_cloud_metrics`), `app/core/summary.py` (`_performance_notes`).
- Frontend: `src/components/ComparePanel.tsx` (one more possible note string; no new UI shape),
  `src/components/CaseDrilldown.tsx` (cached-token figure alongside existing per-result metrics) if
  warranted once the backend field exists.
- Docs: a new guidance file (location decided in design.md) for live-agent builders; no runtime
  code path reads it.
- No new config, no DB schema change expected (metrics already live in a free-form JSON column).
- Explicitly out of scope: Anthropic `cache_control` support; any change to the Runner's `repeats`
  semantics or a full-response cache of any kind on the measured request path.
