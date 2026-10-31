"""`app.core.agent_catalog` and `GET /api/agents/catalog` (add-agent-playground)."""

from app.core import agent_catalog
from tests.fakes import FakeOllama
from tests.helpers import new_client


def test_catalog_lists_the_three_reference_flavors():
    agent_catalog.load_catalog.cache_clear()
    catalog = agent_catalog.load_catalog()
    assert set(catalog) == {"chatbot", "reasoning", "router"}
    assert catalog["chatbot"].kind == "chatbot"
    assert catalog["chatbot"].task_slots == ["default"]
    assert catalog["reasoning"].task_slots == ["classification", "reasoning", "generation"]
    assert catalog["router"].task_slots == ["routing", "classification"]
    for flavor in catalog.values():
        assert set(flavor.accepts) == {"system_prompt", "skill", "task"}


def test_catalog_endpoint_returns_the_three_flavors(settings, file_session_factory):
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.get("/api/agents/catalog")
        assert r.status_code == 200
        ids = {entry["id"] for entry in r.json()}
        assert ids == {"chatbot", "reasoning", "router"}


def test_catalog_route_does_not_shadow_agent_id_lookup(settings, file_session_factory):
    """'/catalog' must be registered ahead of '/{agent_id}' or this 404s as an unknown agent id."""
    with new_client(settings, file_session_factory, FakeOllama()) as c:
        r = c.get("/api/agents/999999")
        assert r.status_code == 404
        r = c.get("/api/agents/catalog")
        assert r.status_code == 200
