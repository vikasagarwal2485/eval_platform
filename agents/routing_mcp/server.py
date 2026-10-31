"""Routing-mapping MCP server (tasks 1.2/2.1, design.md Decisions 6-7, spec `reference-agents`'s "A
routing-mapping tool resolves classification results to a target action").

Resolves the context-classifier service's per-task result to a concrete downstream action
(`short_circuit` or `handoff`) using an ordered, hand-edited rule list in `routes.yaml` - first match wins,
an unmatched result falls through to `routes.yaml`'s `default` (always an `error` action in practice), never
guessing a route. A rule MAY also require a minimum `confidence` for its own task's result (`min_confidence`,
`add-agent-playground` - found via live testing) - a label match alone isn't enough: the classifier's `spam`
detector can report `label: "spam"` at a confidence barely above its 0.5 binary decision boundary (e.g. 0.54)
for an entirely ordinary, confidently-classified-by-topic problem (`ag_news` at 0.79+), and the unconditional
`spam` rule used to short-circuit on that label alone, discarding the problem with no chance to answer it. A
rule whose label matches but whose confidence doesn't meet its own `min_confidence` is treated as *not*
matching - resolution keeps looking at the remaining rules, exactly as if that rule weren't there for this
result; a rule without `min_confidence` is ungated, matching on label alone as before. The mapping can be
extended by editing `routes.yaml` alone, with no change here or in the orchestrator agent's own code
(`routes.yaml` is read fresh on every call, never cached).

Runs as a standalone MCP server over stdio, spawned as a subprocess by `classifier_router_agent.py`
(design.md Decision 6: a real, separate-process MCP server, not a long-running network service or a plain
in-process tool).

Usage (spawned automatically by the router agent; rarely run by hand):
    python -m routing_mcp.server
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from mcp.server.mcpserver import MCPServer

ROUTES_PATH = Path(__file__).resolve().parent / "routes.yaml"


def load_routes(path: Path = ROUTES_PATH) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f)


def resolve(classification: dict[str, dict], routes: dict[str, Any]) -> dict[str, Any]:
    """First-match-wins resolution (design.md Decision 7). `classification` is the context-classifier
    service's `/classify` response's `results` object (`{task: {"label": ..., "confidence": ..., ...}}`).
    Returns the matching rule's action dict (with `task`/`label`/`min_confidence` stripped - those were only
    for matching), or a copy of `routes["default"]` when nothing matches - never guesses.

    A rule's own `min_confidence` (optional) gates its label match on that task's reported `confidence` -
    a label match below it is treated as no match at all, and resolution keeps checking the remaining rules
    (found via live testing: without this, an ordinary, confidently-classified-by-topic problem could still
    be short-circuited as spam on a barely-above-0.5 `spam` confidence alone)."""
    for rule in routes.get("rules", []):
        task_result = classification.get(rule["task"])
        if task_result is None:
            continue
        label = task_result.get("label")
        if rule["label"] != "*" and rule["label"] != label:
            continue
        min_confidence = rule.get("min_confidence")
        if min_confidence is not None and task_result.get("confidence", 0) < min_confidence:
            continue
        return {k: v for k, v in rule.items() if k not in ("task", "label", "min_confidence")}
    return dict(routes.get("default", {"action": "error"}))


server = MCPServer("routing-mcp")


@server.tool()
def resolve_route(classification: dict[str, dict]) -> dict:
    """Resolve a context-classifier result (the `/classify` response's `results` object) to a concrete
    downstream action - `{"action": "short_circuit", "response": "..."}` or `{"action": "handoff",
    "target_agent": "...", "target_kind": "reasoning" | "chatbot"}` (`target_kind` is optional and defaults
    to `"reasoning"` when a rule omits it, `add-chatbot-handoff`) - using the rules in `routes.yaml`, each
    optionally gated by its own `min_confidence` (see `resolve()`). Returns `{"action": "error"}` when no
    rule matches; never guesses a route."""
    return resolve(classification, load_routes())


def main() -> None:
    server.run()  # defaults to stdio transport


if __name__ == "__main__":
    main()
