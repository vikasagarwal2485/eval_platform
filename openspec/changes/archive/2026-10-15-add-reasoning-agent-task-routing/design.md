# Design

## Context

See `proposal.md` - Why. `add-litellm-gateway-infra` ships the gateway and the two model groups
this change consumes; nothing in that change calls them yet. `reasoning_agent.py`'s `solve_one()`
already has three separate, named calls (`call_ollama()` for plan/solve/verify) - this change
only changes which function they call through and what `model` string they pass, not the overall
turn/span structure (unchanged per the `reference-agents` spec's existing "Reasoning turn has
multiple spans" scenario).

## Goals / Non-Goals

**Goals:**
- Route the reasoning agent's plan/verify calls to `reasoning-agent__reasoning` and its solve call
  to `reasoning-agent__generation`, through the gateway.
- Preserve every existing observable behavior: turn/span structure, suite-replay mode, the
  "print and keep going" error-robustness behavior added for the live-agent-evaluation work.

**Non-Goals:**
- `agents/chatbot.py` is not touched. It issues one call per turn; there is no second task to
  route to, so there is nothing for this change to do there (open question from the companion
  proposal doc, resolved: chatbot.py keeps its direct, single-model path unless/until it grows a
  second call).
- No `Agent` registry schema change (`add-agent-multi-model-registry`) - this change hardcodes the
  two group names in the agent's own CLI defaults, the same way `--ollama-url` is hardcoded today.
- No change to the gateway's config (`add-litellm-gateway-infra` already ships the groups this
  change needs).

## Decisions

**`call_llm()` replaces `call_ollama()` as a straight swap, keeping the same `(content, usage)`
return shape.** Minimizes the diff and keeps `solve_one()`'s structure unchanged; only the
function body and the `model` values passed in change.

**The model group name is a CLI default, not a new flag.** `--model` keeps its existing meaning
(it becomes the literal LiteLLM model string passed through, e.g. a group name or, for local
testing without the gateway, a direct `ollama_chat/...` string) and a new `--gateway-url` replaces
`--ollama-url` as the `api_base` passed to `completion()`. Running without the gateway (pointing
`--model` directly at a provider string and omitting `--gateway-url`) remains possible for local
development, matching the simpler single-model flow in the companion proposal doc's "Using
LiteLLM in the reference agents" section - this change does not require the gateway to be running
for the agent to run at all, only for it to run in task-routed mode.

**On a gateway failure, fail the call - do not fall back to calling a provider directly.** A
silent fallback would defeat the purpose of routing through the gateway (credentials would need
to exist in the agent process after all) and would hide a real operational problem. This matches
the existing "print an error and keep taking input" robustness behavior: the call fails, it's
reported, the REPL/suite loop continues to the next input.

**Calling the proxy through the SDK requires an `openai/` prefix on the group name.**
Verified directly against a running gateway while implementing `add-litellm-gateway-infra`:
`litellm.completion(model="reasoning-agent__reasoning", api_base=<proxy>, ...)` fails with
`BadRequestError: LLM Provider NOT provided` - the SDK does not infer "this `api_base` is a
LiteLLM Proxy" on its own. The call must be `litellm.completion(model="openai/reasoning-agent__reasoning",
api_base=<proxy>, api_key=<virtual key>, ...)` - the proxy is an OpenAI-compatible endpoint from
the SDK's point of view, and `custom_llm_provider` (encoded via the `openai/` prefix) is what
tells it so. `call_llm()`'s `model_group` argument must be prefixed with `openai/` before being
passed to `completion()`.

**Span `model` is read from a response header, not `resp.model`.** Also verified directly:
`resp.model` on the SDK's return value is still the **alias** (`reasoning-agent__reasoning`), not
the concrete deployment - this corrects the original assumption in this decision. The concrete
model the gateway actually used (e.g. `ollama_chat/qwen3:8b`) is exposed only via
`resp._hidden_params["additional_headers"]["llm_provider-x-litellm-model-name"]` (the proxy's
`x-litellm-model-name` response header, passed through with an `llm_provider-` prefix by the
SDK's generic-provider handling). `call_llm()` must read the span's recorded model from that
header, falling back to the alias only if the header is ever absent (log a warning in that case -
it would mean the eligibility check below is keying off an alias, silently). This still matters
for the reason originally stated: spans must keep recording a real model identity because
`plan_turn_evaluators`/`same_model`/`same_family` key off it for the never-self-judge invariant -
a group alias would break that check silently, and the header is genuinely how to avoid that, not
`resp.model`.

## Risks / Trade-offs

[This agent now has a hard dependency on the gateway being up to run in its normal, task-routed
configuration] → documented above as the deliberate choice (fail visibly, no silent direct-call
fallback); operators running the suite unattended should confirm gateway health first, per
`add-litellm-gateway-infra`'s health-check task.

[Two model groups for one agent is a small surface, but it's still one more moving config piece
to keep in sync with the agent's actual behavior] → `add-agent-multi-model-registry` is where this
gets a structural fix (the registry becomes the source of truth); this change accepts the
temporary hand-kept coupling to ship the user-visible result sooner, as laid out in the companion
proposal doc's phased plan.

## Migration Plan

No data migration. Deploy order: `add-litellm-gateway-infra` first (groups and virtual key must
exist), then this change. Rollback: revert `reasoning_agent.py` to its pre-change `call_ollama()`
path; no persisted state depends on the routing change.
