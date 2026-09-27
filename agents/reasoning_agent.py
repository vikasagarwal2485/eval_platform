"""Reference multi-step reasoning agent (task 7.1, spec `reference-agents`).

Answers one problem per turn through three LLM calls - plan, solve, verify/format the final answer - so one turn
has multiple spans and can involve more than one model. Streams every call into the eval platform via the agent
SDK. With `--suite`, replays a suite file's reasoning cases and sends each case's expected answer as the turn's
reference, so the platform's deterministic reference-based correctness check runs alongside the evaluator's score.

Usage:
    python -m agents.reasoning_agent --platform-url http://localhost:8000 --token <ingest-token> \
        --problem "A train travels 60 miles in 40 minutes. What is its speed in mph?"
    python -m agents.reasoning_agent --platform-url ... --token ... --suite path/to/suite.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_agent_sdk import AgentClient  # noqa: E402

PLAN_PROMPT = "Break the following problem into a short numbered plan. Do not solve it yet.\n\nProblem: {problem}"
SOLVE_PROMPT = "Problem: {problem}\n\nPlan:\n{plan}\n\nFollow the plan and work through the problem step by step."
VERIFY_PROMPT = (
    "Problem: {problem}\n\nWorking:\n{solution}\n\n"
    "Check the working for mistakes, then restate the result as: Final answer: <answer>"
)


def call_ollama(ollama_url: str, model: str, prompt: str, *, timeout: float = 120.0) -> tuple[str, dict]:
    started = time.monotonic()
    resp = httpx.post(
        f"{ollama_url.rstrip('/')}/api/chat",
        json={"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("message", {}).get("content", ""), {
        "latency_ms": (time.monotonic() - started) * 1000,
        "prompt_tokens": data.get("prompt_eval_count"),
        "completion_tokens": data.get("eval_count"),
    }


def _span(t, model: str, output: str, usage: dict) -> None:
    t.llm_call(
        model=model, output=output,
        prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"),
    )


def solve_one(
    client: AgentClient, session_id: str, model: str, ollama_url: str, problem: str, *, reference: str | None = None
) -> str:
    """Plan -> solve -> verify, each its own LLM span under one turn."""
    with client.turn(session_id, input=problem, reference=reference) as t:
        plan, plan_usage = call_ollama(ollama_url, model, PLAN_PROMPT.format(problem=problem))
        _span(t, model, plan, plan_usage)

        solution, solve_usage = call_ollama(ollama_url, model, SOLVE_PROMPT.format(problem=problem, plan=plan))
        _span(t, model, solution, solve_usage)

        final, verify_usage = call_ollama(ollama_url, model, VERIFY_PROMPT.format(problem=problem, solution=solution))
        _span(t, model, final, verify_usage)

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


def run_once(client: AgentClient, model: str, ollama_url: str, problem: str) -> None:
    session_id = uuid.uuid4().hex
    final = solve_one(client, session_id, model, ollama_url, problem)
    print(final)


def run_suite(client: AgentClient, model: str, ollama_url: str, suite_path: Path) -> None:
    cases = _load_reasoning_cases(suite_path)
    if not cases:
        print(f"No reasoning cases found in {suite_path}")
        return
    session_id = uuid.uuid4().hex
    for case in cases:
        final = solve_one(client, session_id, model, ollama_url, case["prompt"], reference=case.get("expected"))
        title = case.get("title") or case["prompt"][:60]
        print(f"[{title}] -> {final.strip()[:120]}")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Reference multi-step reasoning agent for the eval platform")
    p.add_argument("--model", default="qwen3:8b")
    p.add_argument("--ollama-url", default="http://localhost:11434")
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
            run_suite(client, args.model, args.ollama_url, args.suite)
        else:
            run_once(client, args.model, args.ollama_url, args.problem)
    finally:
        client.close()


if __name__ == "__main__":
    main()
