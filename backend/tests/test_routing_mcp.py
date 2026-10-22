"""`add-classifier-router-agent` tasks 1.2/2.1/2.2: the routing-mapping MCP server's resolution logic,
tested directly (no stdio transport needed - `resolve()` is pure, `resolve_route`'s MCP wiring is a thin
shell over it)."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agents"))

from routing_mcp.server import ROUTES_PATH, load_routes, resolve  # noqa: E402


def test_routes_yaml_parses_and_has_the_expected_shape():
    routes = load_routes()
    assert routes["rules"][0] == {
        "task": "spam",
        "label": "spam",
        "action": "short_circuit",
        "response": "This message looks like spam and was not forwarded to any agent.",
    }
    assert routes["rules"][1] == {
        "task": "ag_news",
        "label": "*",
        "action": "handoff",
        "target_agent": "reasoning-agent",
    }
    assert routes["default"] == {"action": "error"}


def test_a_known_label_resolves_to_its_configured_action():
    routes = load_routes()
    result = resolve({"spam": {"label": "spam", "confidence": 0.9}}, routes)
    assert result == {"action": "short_circuit", "response": routes["rules"][0]["response"]}


def test_a_wildcard_rule_matches_any_label_for_its_task():
    routes = load_routes()
    for label in ("Business", "Sci/Tech", "Sports", "World"):
        result = resolve({"ag_news": {"label": label, "confidence": 0.5}}, routes)
        assert result == {"action": "handoff", "target_agent": "reasoning-agent"}


def test_first_match_wins_when_more_than_one_rule_could_apply():
    routes = load_routes()
    # spam's rule comes first in routes.yaml, so it wins even though ag_news also has a result
    result = resolve(
        {"ag_news": {"label": "Business"}, "spam": {"label": "spam"}},
        routes,
    )
    assert result["action"] == "short_circuit"


def test_an_unmapped_result_falls_through_to_default_not_a_guess():
    routes = load_routes()
    result = resolve({"some_other_task": {"label": "whatever"}}, routes)
    assert result == {"action": "error"}


def test_a_non_matching_label_under_a_known_task_falls_through_to_default():
    routes = load_routes()
    # "ham" isn't configured as its own rule (only the wildcard "*" is, under ag_news) - spam itself has no
    # wildcard, so an unconfigured spam label falls to default rather than silently matching
    result = resolve({"spam": {"label": "ham"}}, routes)
    assert result == {"action": "error"}


def test_the_mapping_is_reloadable_without_touching_server_py(tmp_path, monkeypatch):
    """task 2.2: editing routes.yaml and reloading (no server.py/agent code change) picks up a brand-new
    rule immediately - `load_routes()` never caches."""
    custom = tmp_path / "routes.yaml"
    custom.write_text(
        yaml.safe_dump(
            {
                "rules": [{"task": "new_task", "label": "new_label", "action": "handoff", "target_agent": "x"}],
                "default": {"action": "error"},
            }
        )
    )
    routes = load_routes(custom)
    result = resolve({"new_task": {"label": "new_label"}}, routes)
    assert result == {"action": "handoff", "target_agent": "x"}

    # the real routes.yaml is untouched and still behaves as before
    assert ROUTES_PATH.exists()
    real_routes = load_routes()
    assert resolve({"new_task": {"label": "new_label"}}, real_routes) == {"action": "error"}
