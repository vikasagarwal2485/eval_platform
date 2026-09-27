"""Reference chatbot agent (task 7.1, spec `reference-agents`).

A minimal REPL chatbot over a local Ollama model. Each user message is one turn with exactly one LLM span,
streamed into the eval platform through the agent SDK. It exists to demonstrate and test the ingest-to-evaluation
loop end to end - register it as an agent, point an evaluator at a *different* model, and its turns show up
evaluated with no self-judged score (spec `reference-agents`, scenario "End-to-end demonstration").

Usage:
    python -m agents.chatbot --platform-url http://localhost:8000 --token <ingest-token> --model qwen3:8b
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_agent_sdk import AgentClient  # noqa: E402

DEFAULT_SYSTEM_PROMPT = "You are a helpful, concise assistant."


def call_ollama(ollama_url: str, model: str, messages: list[dict], *, timeout: float = 120.0) -> tuple[str, dict]:
    """One non-streaming chat call. Returns (content, usage) where usage holds token counts Ollama reports."""
    started = time.monotonic()
    body = {"model": model, "messages": messages, "stream": False}
    resp = httpx.post(f"{ollama_url.rstrip('/')}/api/chat", json=body, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return data.get("message", {}).get("content", ""), {
        "latency_ms": (time.monotonic() - started) * 1000,
        "prompt_tokens": data.get("prompt_eval_count"),
        "completion_tokens": data.get("eval_count"),
    }


def answer(
    client: AgentClient, session_id: str, model: str, ollama_url: str, system_prompt: str,
    history: list[dict], user_message: str,
) -> str:
    messages = ([{"role": "system", "content": system_prompt}] if system_prompt else []) + history + [
        {"role": "user", "content": user_message}
    ]
    with client.turn(session_id, input=user_message) as t:
        content, usage = call_ollama(ollama_url, model, messages)
        t.llm_call(
            model=model,
            messages=messages,
            output=content,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )
        t.finish(content)
    return content


def run_repl(client: AgentClient, model: str, ollama_url: str, system_prompt: str) -> None:
    session_id = uuid.uuid4().hex
    history: list[dict] = []
    print(f"Chatbot ready (model={model}). Type 'quit' to exit.")
    while True:
        try:
            user_message = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_message or user_message.lower() in ("quit", "exit"):
            break
        try:
            content = answer(client, session_id, model, ollama_url, system_prompt, history, user_message)
        except httpx.HTTPError as exc:
            # The turn is still recorded (as an error, via Turn.__exit__) so it shows up on the platform - only
            # the local REPL loop must survive this and keep taking input, rather than crashing the whole agent.
            print(f"[error calling {model} at {ollama_url}: {exc}]")
            continue
        history += [{"role": "user", "content": user_message}, {"role": "assistant", "content": content}]
        print(f"Bot: {content}")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Reference chatbot agent for the eval platform")
    p.add_argument("--model", default="qwen3:8b", help="Ollama model the agent uses to answer")
    p.add_argument("--ollama-url", default="http://localhost:11434")
    p.add_argument("--platform-url", required=True, help="Base URL of the eval platform")
    p.add_argument("--token", required=True, help="This agent's ingest token")
    p.add_argument("--system-prompt", default=DEFAULT_SYSTEM_PROMPT)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    client = AgentClient(args.platform_url, args.token)
    try:
        run_repl(client, args.model, args.ollama_url, args.system_prompt)
    finally:
        client.close()


if __name__ == "__main__":
    main()
