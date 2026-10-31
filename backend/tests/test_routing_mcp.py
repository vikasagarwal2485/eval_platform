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
    """`add-chatbot-handoff`: the reference `routes.yaml` now demonstrates all three branches -
    spam short-circuits, the ag_news topics Sports/World hand off to a chatbot target (specific
    rules, matched before the trailing wildcard), and every other ag_news topic keeps the original
    behavior via the wildcard, handing off to a reasoning target."""
    routes = load_routes()
    assert routes["rules"][0] == {
        "task": "spam",
        "label": "spam",
        "min_confidence": 0.8,
        "action": "short_circuit",
        "response": "This message looks like spam and was not forwarded to any agent.",
    }
    assert routes["rules"][1] == {
        "task": "ag_news",
        "label": "Sports",
        "action": "handoff",
        "target_kind": "chatbot",
        "target_agent": "chatbot-agent",
    }
    assert routes["rules"][2] == {
        "task": "ag_news",
        "label": "World",
        "action": "handoff",
        "target_kind": "chatbot",
        "target_agent": "chatbot-agent",
    }
    assert routes["rules"][3] == {
        "task": "ag_news",
        "label": "*",
        "action": "handoff",
        "target_kind": "reasoning",
        "target_agent": "reasoning-agent",
    }
    assert routes["default"] == {"action": "error"}


def test_a_known_label_resolves_to_its_configured_action():
    routes = load_routes()
    result = resolve({"spam": {"label": "spam", "confidence": 0.9}}, routes)
    assert result == {"action": "short_circuit", "response": routes["rules"][0]["response"]}


# ------------------------------------------------------------------ min_confidence (found via live testing)
def test_a_label_match_below_min_confidence_is_not_treated_as_a_match():
    """Live finding: a `spam` label at only barely-above-0.5 confidence must not short-circuit an
    otherwise confidently-classified-by-topic problem - it falls through to the ag_news rule
    instead, exactly as if the spam rule weren't there for this result."""
    routes = load_routes()
    result = resolve(
        {
            "ag_news": {"label": "Business", "confidence": 0.79},
            "spam": {"label": "spam", "confidence": 0.54},
        },
        routes,
    )
    assert result == {"action": "handoff", "target_kind": "reasoning", "target_agent": "reasoning-agent"}


def test_a_label_match_at_or_above_min_confidence_still_matches():
    routes = load_routes()
    result = resolve(
        {"ag_news": {"label": "Business", "confidence": 0.79}, "spam": {"label": "spam", "confidence": 0.95}},
        routes,
    )
    assert result["action"] == "short_circuit"


def test_a_missing_confidence_on_a_gated_rule_is_treated_as_not_meeting_the_threshold():
    """Never guesses a confidence that wasn't actually reported - a gated rule with no `confidence`
    at all on the task result fails the gate, the same as an explicitly low one."""
    routes = load_routes()
    result = resolve(
        {"ag_news": {"label": "Business", "confidence": 0.79}, "spam": {"label": "spam"}},
        routes,
    )
    assert result["action"] == "handoff"


def test_an_ungated_rule_matches_on_label_alone():
    """A rule with no `min_confidence` (every ag_news rule here) is unaffected - this is the
    pre-existing behavior for every rule written before this field existed."""
    routes = load_routes()
    result = resolve({"ag_news": {"label": "Sports"}}, routes)  # no confidence at all
    assert result == {"action": "handoff", "target_kind": "chatbot", "target_agent": "chatbot-agent"}


def test_specific_rules_match_before_the_trailing_wildcard():
    """Sports/World each have their own rule, listed before the wildcard - first-match-wins means
    they resolve to the chatbot target, never falling through to the wildcard's reasoning target."""
    routes = load_routes()
    for label in ("Sports", "World"):
        result = resolve({"ag_news": {"label": label, "confidence": 0.5}}, routes)
        assert result == {"action": "handoff", "target_kind": "chatbot", "target_agent": "chatbot-agent"}


def test_a_wildcard_rule_matches_any_other_label_for_its_task():
    routes = load_routes()
    for label in ("Business", "Sci-Tech"):
        result = resolve({"ag_news": {"label": label, "confidence": 0.5}}, routes)
        assert result == {"action": "handoff", "target_kind": "reasoning", "target_agent": "reasoning-agent"}


def test_first_match_wins_when_more_than_one_rule_could_apply():
    routes = load_routes()
    # spam's rule comes first in routes.yaml, so it wins even though ag_news also has a result -
    # given a confidently-spam result (comfortably above the spam rule's own min_confidence)
    result = resolve(
        {"ag_news": {"label": "Business"}, "spam": {"label": "spam", "confidence": 0.95}},
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
