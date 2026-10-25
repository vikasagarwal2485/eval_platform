# Prompt caching for agents

"Prompt caching" means a provider reuses work it already did on an earlier request instead of
reprocessing the same prompt tokens again. It's a real speed/cost win, but the mechanism - and
what you have to do to get it - differs per provider. This page is about **your own agent's calls
to its model(s)**: nothing here is wired into this platform's runtime; it's the pattern the
benchmark Runner itself already follows for the same reason (see the worked example below), laid
out so you can apply it to your own agent's calls too.

## The three mechanisms

| Provider | How it works | What you do |
|---|---|---|
| **Ollama** (local) | Automatic. A loaded model keeps a cache of the last prompt it processed; a new request that shares a literal *prefix* with it only re-evaluates the new part. | Nothing to configure - just (1) send requests to the same model back-to-back, without loading a different model in between, and (2) keep the shared prefix byte-identical across calls. |
| **OpenAI / Azure OpenAI** | Also automatic, for prompts over roughly 1024 tokens with a recently-seen shared prefix. | Nothing to configure. The usage response reports `prompt_tokens_details.cached_tokens` when it happens - read it if you want to know whether it did. |
| **Anthropic** | **Opt-in only.** Nothing is cached unless you mark a breakpoint. | Send `system` (and/or long, stable message blocks) as a content-block array with a `cache_control: {"type": "ephemeral"}` entry on the block you want cached. The response then reports `cache_read_input_tokens` / `cache_creation_input_tokens`. |

For Ollama and OpenAI/Azure, caching already happens if you do nothing extra - the only lever is
not accidentally defeating it (see below). For Anthropic, caching happens *only* if you ask.

## The one pattern that makes all three work: stable prefix first, variable content last

Every one of these mechanisms rewards the same shape: put whatever is going to be **identical
across many of your calls** first, and whatever **changes every call** last. This platform's own
Runner already does exactly this for every request it sends - the worked example, so you don't have
to take it on faith:

```python
# backend/app/core/templates.py
def apply_skills(system_prompt, skills):
    if not skills:
        return system_prompt
    blocks = [f"# Skill: {s['name']}\n\n{s['instructions']}" for s in skills]  # stable, same every case
    if system_prompt:
        blocks.append(system_prompt)                                          # the case's own, smaller, system text
    return "\n\n---\n\n".join(blocks)
```

The skill instructions - often the largest, always-identical part of the prompt for a given run -
go **first**, as a leading system block. The thing that's different on every call (the case's own
prompt, sent separately as the user message) goes last and is never part of the cached prefix. A
live check against this platform's own data confirms the payoff: a run with a skill attached and
six cases, same model, shows the second case's `prompt_eval_ms` drop 2-3x versus the first -
despite an almost-identical `prompt_tokens` count - because Ollama is reusing the cached prefix
from the first request onward.

**Apply this to your own agent** by asking: what in this call's prompt is the same across many
calls (a system preamble, task instructions, a tool-use policy, retrieved context that doesn't
change turn-to-turn), and what's genuinely new (the user's latest message)? Put the former first,
as its own stable block, the latter last.

- **A one-shot call with everything inlined into a single user message** (as this repo's own
  `reasoning_agent.py` currently does for its classify/plan/solve/verify calls) has nothing for a
  cache to grab onto - there's no stable leading block to reuse, since the "instructions" and the
  "problem" are concatenated into one string that's different every time. Splitting the static
  instructions into their own leading system message, with the problem as the user turn, is what
  turns "no caching possible" into "caching possible."
- **A genuinely multi-turn conversation** (this repo's `chatbot.py` is one) is the canonical case:
  the whole history except the newest turn is a long, growing, otherwise-identical prefix every
  round. For Anthropic specifically, that's exactly where a `cache_control` breakpoint belongs -
  on the last message *before* the newest user turn, so everything up to it is reused next round.

## The trap: a full-response cache is not the same thing, and can lie to you

Everything above is about **skipping redundant processing of the same tokens** - the actual work
still happens for whatever's new. A full-response cache (returning a cached *answer* for an
identical request, skipping the model call entirely) is a different mechanism with a different
risk: if you are measuring anything about your agent's timing - latency, tokens/sec, how a change
affects either - a full-response cache sitting in front of a repeated call will make that
measurement meaningless, because the second (and any later) "request" never actually ran. This
platform's own `RunConfig.repeats` exists specifically to average out timing *noise* across
repeated identical requests; a full-response cache on that same path would silently turn "the
measurement, repeated" into "the measurement, faked after the first time." If your agent's own
benchmarking replays the same prompt more than once on purpose, make sure nothing between your
code and the provider - a gateway's own response cache included - is doing this for you unasked.

## What this platform does and doesn't do today

- The benchmark Runner already benefits from Ollama's automatic caching (via the ordering and
  prefix-stability described above) and now also warms the skill prefix *before* the first
  measured case, not just during it.
- OpenAI/Azure's `cached_tokens` figure, when reported, is captured and shown per result and used
  to explain a run-vs-run latency/tokens-per-sec difference - this platform reports it, it doesn't
  request it; nothing changes what the provider decides to cache.
- Anthropic `cache_control` is not implemented anywhere in this platform yet. If you want it for
  your own agent's Anthropic calls, build it directly against your own request shape per the table
  above - it isn't something a gateway config alone turns on for you unasked, since it requires
  marking *which* content is cacheable, which only your own code knows.
