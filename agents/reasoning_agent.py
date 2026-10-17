"""Reference multi-step reasoning agent (task 7.1, spec `reference-agents`).

Answers one problem per turn through three LLM calls - plan, solve, verify/format the final answer - so one turn
has multiple spans and can involve more than one model. Streams every call into the eval platform via the agent
SDK. With `--suite`, replays a suite file's reasoning cases and sends each case's expected answer as the turn's
reference, so the platform's deterministic reference-based correctness check runs alongside the evaluator's score.

By default (no `--model`), plan/verify calls route through the shared LLM gateway
(`openspec/changes/add-litellm-gateway-infra`) to the `reasoning-agent__reasoning` model group and the solve call
to `reasoning-agent__generation` - each task's call uses whatever model that group is configured for, which can
differ per call within one turn. Passing `--model` overrides all three calls to one literal model string and
skips the gateway, for simple local testing (matching the agent's pre-task-routing behavior).

`--reasoning-model-group`/`--generation-model-group` override those two defaults (TEMPORARY stopgap - see
`add-gateway-model-sync`'s design.md "Non-Goals": this agent does not yet discover its own group names from the
platform at runtime, so if the agent you registered isn't literally named "reasoning-agent", its
`declared_models`-synced groups are named `<your-agent-slug>__reasoning`/`<your-agent-slug>__generation`, not
these defaults, and you must pass them explicitly).

`--reasoning-fallback-group`/`--generation-fallback-group` (`add-declared-model-fallback`) each name a gateway
group to fall back to if that call's primary group is unreachable - unset by default (no fallback passed).
Each is sent as that request's own `fallbacks` field, the only mechanism verified to work against the gateway;
a fallback configured only via the gateway's `/config/update` is NOT reliably applied (see gateway/README.md).

Usage:
    python -m agents.reasoning_agent --platform-url http://localhost:8000 --token <ingest-token> \
        --problem "A train travels 60 miles in 40 minutes. What is its speed in mph?"
    python -m agents.reasoning_agent --platform-url ... --token ... --suite path/to/suite.yaml
    # local testing without the gateway:
    python -m agents.reasoning_agent --platform-url ... --token ... --model ollama_chat/qwen3:8b --problem "..."
    # an agent registered under a name other than "reasoning-agent", with its groups synced dynamically:
    python -m agents.reasoning_agent --platform-url ... --token ... --gateway-key ... \
        --reasoning-model-group my-reasoner__reasoning --generation-model-group my-reasoner__generation \
        --problem "..."
    # with a configured fallback (e.g. an Azure primary backstopped by a local Ollama model):
    python -m agents.reasoning_agent --platform-url ... --token ... --gateway-key ... \
        --reasoning-fallback-group my-reasoner__reasoning__fallback \
        --generation-fallback-group my-reasoner__generation__fallback \
        --problem "..."
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import uuid
import warnings
from pathlib import Path

import litellm
import openai

# Quiets LiteLLM's own internal noise for an error it then recovers from via a configured fallback
# (`add-declared-model-fallback`) - verified live: without this, EVERY failed attempt in a fallback chain
# (including the primary's own failure, even when a later fallback succeeds) prints a "Give Feedback / Get
# Help" banner (gated by `litellm.suppress_debug_info`) plus a full traceback (`fallback_utils.py` logs each
# failed attempt via `verbose_logger.exception(...)`, which always includes the traceback at ERROR level -
# raising the "LiteLLM" logger above ERROR silences it). Neither flag hides a call that fails outright with no
# working fallback - this agent's own `run_once`/`run_suite` already print a clean one-line error for that case
# (see their `except openai.OpenAIError` handlers), so nothing about a genuine failure becomes invisible.
litellm.suppress_debug_info = True
logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)

# A second, unrelated source of noise, also only visible once a call actually fails over (verified live):
# litellm's sync `completion()` wrapper runs each call in its own, short-lived event loop, so its global
# background logging worker (unrelated to this agent - we configure no success/failure callbacks) gets
# orphaned on the previous, now-closed loop every time a later call spins up a new one. Python's own asyncio
# then logs "Task was destroyed but it is pending!" (via the stdlib's "asyncio" logger - same fix as above)
# and raises a "coroutine was never awaited" RuntimeWarning when that orphaned task is later garbage
# collected. Purely cosmetic noise about litellm's internal bookkeeping, not about anything this agent did.
logging.getLogger("asyncio").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore", message=r"coroutine .* was never awaited", category=RuntimeWarning)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_agent_sdk import AgentClient  # noqa: E402

PLAN_PROMPT = "Break the following problem into a short numbered plan. Do not solve it yet.\n\nProblem: {problem}"
SOLVE_PROMPT = "Problem: {problem}\n\nPlan:\n{plan}\n\nFollow the plan and work through the problem step by step."
VERIFY_PROMPT = (
    "Problem: {problem}\n\nWorking:\n{solution}\n\n"
    "Check the working for mistakes, then restate the result as: Final answer: <answer>"
)

# The gateway's Router model groups this agent uses by default (`add-litellm-gateway-infra`'s config.yaml).
# Hardcoded the same way `--ollama-url`'s old default was: a known-good value for the common case, overridable.
REASONING_MODEL_GROUP = "reasoning-agent__reasoning"
GENERATION_MODEL_GROUP = "reasoning-agent__generation"


def _concrete_model(resp, requested_model: str) -> str:
    """The real deployment that answered a gateway-routed call, not the group alias. `resp.model` on a LiteLLM
    response is the alias (`reasoning-agent__reasoning`), not the concrete model (e.g. `ollama_chat/qwen3:8b`) -
    verified directly against a running gateway while implementing `add-litellm-gateway-infra`; the concrete
    model is only exposed via the proxied `x-litellm-model-name` response header. Falls back to the requested
    model string when that header isn't present (e.g. not going through the gateway at all), so a span is never
    left without a model - a required field for the turn to ever be eligible for evaluation (spec
    `trace-ingestion`)."""
    hidden = getattr(resp, "_hidden_params", None) or {}
    headers = hidden.get("additional_headers") or {}
    return headers.get("llm_provider-x-litellm-model-name") or requested_model


def call_llm(
    gateway_url: str | None,
    gateway_key: str | None,
    model: str,
    prompt: str,
    *,
    timeout: float = 120.0,
    fallback_group: str | None = None,
) -> tuple[str, dict]:
    """One completion call, through the gateway when `gateway_url` is set (the normal, task-routed path) or
    directly otherwise (local testing). Returns `(content, usage)`; `usage["model"]` carries the concrete model
    that actually answered (see `_concrete_model`), not necessarily `model` itself.

    `fallback_group` (`add-declared-model-fallback`) names a gateway model group for LiteLLM to retry against if
    `model` is unreachable - passed as the request's own `fallbacks` field, the only mechanism verified to work
    live against the gateway (a fallback configured gateway-wide via `/config/update` does NOT reliably apply -
    see design.md). Ignored when `gateway_url` is unset (no gateway involved, nothing to fall back to).

    The fallback entry needs the same `openai/` provider-hint prefix the primary `model` gets below - verified
    live while implementing this: the SDK's own client-side fallback retry (`completion_with_fallbacks`) calls
    `completion()` again with whatever string is in `fallbacks`, unprefixed, which fails with `LLM Provider NOT
    provided` exactly like an unprefixed primary model would (this is a *client-side* SDK mechanism, distinct
    from - and with different prefix requirements than - sending `fallbacks` directly to the gateway's own REST
    `/chat/completions` endpoint, which was verified separately and does not need this prefix)."""
    started = time.monotonic()
    call_model = model
    kwargs: dict = {"model": model, "messages": [{"role": "user", "content": prompt}], "timeout": timeout}
    if gateway_url:
        # The SDK needs an explicit provider hint to treat an arbitrary `api_base` as an OpenAI-compatible
        # endpoint - a bare group name fails with `BadRequestError: LLM Provider NOT provided` (verified
        # directly while implementing add-litellm-gateway-infra).
        call_model = f"openai/{model}"
        kwargs["model"] = call_model
        kwargs["api_base"] = gateway_url
        if gateway_key:
            kwargs["api_key"] = gateway_key
        if fallback_group:
            kwargs["fallbacks"] = [f"openai/{fallback_group}"]
    resp = litellm.completion(**kwargs)
    usage = resp.usage
    return resp.choices[0].message.content or "", {
        "latency_ms": (time.monotonic() - started) * 1000,
        "prompt_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
        "completion_tokens": getattr(usage, "completion_tokens", None) if usage else None,
        "model": _concrete_model(resp, model),
    }


def _span(t, requested_model: str, output: str, usage: dict) -> None:
    t.llm_call(
        model=usage.get("model") or requested_model, output=output,
        prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"),
    )


def solve_one(
    client: AgentClient,
    session_id: str,
    model: str | None,
    gateway_url: str | None,
    gateway_key: str | None,
    problem: str,
    *,
    reference: str | None = None,
    reasoning_group: str = REASONING_MODEL_GROUP,
    generation_group: str = GENERATION_MODEL_GROUP,
    reasoning_fallback_group: str | None = None,
    generation_fallback_group: str | None = None,
) -> str:
    """Plan -> solve -> verify, each its own LLM span under one turn. `model=None` (the default) routes plan and
    verify to `reasoning_group` and solve to `generation_group` through the gateway (these default to
    `REASONING_MODEL_GROUP`/`GENERATION_MODEL_GROUP` - override them to match an agent registered under a name
    other than "reasoning-agent", see the module docstring); an explicit `model` overrides all three calls to
    that one literal string and skips the gateway (and ignores both fallback groups - there is no gateway
    involved to fall back through).

    `reasoning_fallback_group`/`generation_fallback_group` (`add-declared-model-fallback`) are each passed on
    the matching calls' underlying request as the gateway group to retry against if the primary group is
    unreachable - `None` (the default) passes no fallback, exactly as before this parameter existed."""
    reasoning_model = model or reasoning_group
    generation_model = model or generation_group
    effective_gateway_url = None if model else gateway_url
    reasoning_fallback = None if model else reasoning_fallback_group
    generation_fallback = None if model else generation_fallback_group

    with client.turn(session_id, input=problem, reference=reference) as t:
        plan, plan_usage = call_llm(
            effective_gateway_url, gateway_key, reasoning_model, PLAN_PROMPT.format(problem=problem),
            fallback_group=reasoning_fallback,
        )
        _span(t, reasoning_model, plan, plan_usage)

        solution, solve_usage = call_llm(
            effective_gateway_url, gateway_key, generation_model,
            SOLVE_PROMPT.format(problem=problem, plan=plan),
            fallback_group=generation_fallback,
        )
        _span(t, generation_model, solution, solve_usage)

        final, verify_usage = call_llm(
            effective_gateway_url, gateway_key, reasoning_model,
            VERIFY_PROMPT.format(problem=problem, solution=solution),
            fallback_group=reasoning_fallback,
        )
        _span(t, reasoning_model, final, verify_usage)

        t.finish(final)
    return final


def _load_reasoning_cases(path: Path) -> list[dict]:
    """Reasoning cases from a suite file (the platform's export/import format: `{cases: [{category, prompt,
    expected, ...}]}`). Supports .json always; .yaml/.yml needs PyYAML installed."""
    text = path.read_text()
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:
            raise SystemExit("reading a .yaml suite needs PyYAML installed (pip install pyyaml)") from exc
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    return [c for c in data.get("cases", []) if c.get("category") == "reasoning"]


def run_once(
    client: AgentClient,
    model: str | None,
    gateway_url: str | None,
    gateway_key: str | None,
    problem: str,
    *,
    reasoning_group: str = REASONING_MODEL_GROUP,
    generation_group: str = GENERATION_MODEL_GROUP,
    reasoning_fallback_group: str | None = None,
    generation_fallback_group: str | None = None,
) -> None:
    session_id = uuid.uuid4().hex
    try:
        final = solve_one(
            client, session_id, model, gateway_url, gateway_key, problem,
            reasoning_group=reasoning_group, generation_group=generation_group,
            reasoning_fallback_group=reasoning_fallback_group, generation_fallback_group=generation_fallback_group,
        )
    except openai.OpenAIError as exc:
        # Covers every exception litellm raises (connection, auth, rate-limit, bad-request, ...) - all of
        # litellm's mapped exceptions subclass `openai.OpenAIError`, verified directly against a running
        # gateway while implementing add-litellm-gateway-infra. A gateway or provider failure fails visibly;
        # it is never silently retried against a direct provider call, bypassing the gateway.
        raise SystemExit(f"error calling the LLM for this problem: {exc}") from exc
    print(final)


def run_suite(
    client: AgentClient,
    model: str | None,
    gateway_url: str | None,
    gateway_key: str | None,
    suite_path: Path,
    *,
    reasoning_group: str = REASONING_MODEL_GROUP,
    generation_group: str = GENERATION_MODEL_GROUP,
    reasoning_fallback_group: str | None = None,
    generation_fallback_group: str | None = None,
) -> None:
    cases = _load_reasoning_cases(suite_path)
    if not cases:
        print(f"No reasoning cases found in {suite_path}")
        return
    session_id = uuid.uuid4().hex
    for case in cases:
        title = case.get("title") or case["prompt"][:60]
        try:
            final = solve_one(
                client, session_id, model, gateway_url, gateway_key, case["prompt"],
                reference=case.get("expected"), reasoning_group=reasoning_group, generation_group=generation_group,
                reasoning_fallback_group=reasoning_fallback_group, generation_fallback_group=generation_fallback_group,
            )
        except openai.OpenAIError as exc:
            # The turn is still recorded (as an error, via Turn.__exit__) - only replaying the rest of the suite
            # must survive this one case's failure, not stop at it.
            print(f"[{title}] -> error calling the LLM: {exc}")
            continue
        print(f"[{title}] -> {final.strip()[:120]}")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Reference multi-step reasoning agent for the eval platform")
    p.add_argument(
        "--model", default=None,
        help="Override all three calls (plan/solve/verify) to this one literal model string and skip the "
        "gateway (local testing). Omit to use the gateway's task-scoped model groups (the normal mode).",
    )
    p.add_argument(
        "--gateway-url", default="http://localhost:4000",
        help="Base URL of the shared LLM gateway (see openspec/changes/add-litellm-gateway-infra). Ignored when "
        "--model is set.",
    )
    p.add_argument(
        "--gateway-key", default=None,
        help="This agent's gateway virtual key (see gateway/README.md - 'Virtual keys'). Ignored when --model "
        "is set.",
    )
    p.add_argument(
        "--reasoning-model-group", default=REASONING_MODEL_GROUP,
        help="Gateway model group for plan/verify calls (default: %(default)s - matches an agent registered "
        "under the name 'reasoning-agent'; override to match your agent's actual registered name - TEMPORARY "
        "stopgap, see the module docstring). Ignored when --model is set.",
    )
    p.add_argument(
        "--generation-model-group", default=GENERATION_MODEL_GROUP,
        help="Gateway model group for the solve call (default: %(default)s - see --reasoning-model-group). "
        "Ignored when --model is set.",
    )
    p.add_argument(
        "--reasoning-fallback-group", default=None,
        help="Gateway model group to fall back to (add-declared-model-fallback) if the plan/verify calls' "
        "primary group is unreachable - passed as that request's own 'fallbacks' field, the only mechanism "
        "verified to work (see gateway/README.md). Unset by default (no fallback). Ignored when --model is set.",
    )
    p.add_argument(
        "--generation-fallback-group", default=None,
        help="Gateway model group to fall back to if the solve call's primary group is unreachable (see "
        "--reasoning-fallback-group). Unset by default. Ignored when --model is set.",
    )
    p.add_argument("--platform-url", required=True)
    p.add_argument("--token", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--problem", help="A single problem to solve")
    g.add_argument("--suite", type=Path, help="A suite file (.json/.yaml) whose reasoning cases to replay")
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    client = AgentClient(args.platform_url, args.token)
    try:
        if args.suite:
            run_suite(
                client, args.model, args.gateway_url, args.gateway_key, args.suite,
                reasoning_group=args.reasoning_model_group, generation_group=args.generation_model_group,
                reasoning_fallback_group=args.reasoning_fallback_group,
                generation_fallback_group=args.generation_fallback_group,
            )
        else:
            run_once(
                client, args.model, args.gateway_url, args.gateway_key, args.problem,
                reasoning_group=args.reasoning_model_group, generation_group=args.generation_model_group,
                reasoning_fallback_group=args.reasoning_fallback_group,
                generation_fallback_group=args.generation_fallback_group,
            )
    finally:
        client.close()


if __name__ == "__main__":
    main()
