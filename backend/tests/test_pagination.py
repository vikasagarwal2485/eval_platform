"""`add-uplift-frontend-ux` tasks 2.1-2.6: `limit`/`offset`/`X-Total-Count` pagination added to
`GET /runs`, `GET /agents`, `GET /skills`, `GET /suites` (design.md D1 - a header carries the
total, the body stays the bare array every existing caller already expects).

Repo-level tests exercise the slicing/counting logic directly against >50 rows (fast, no HTTP/
Ollama needed); API-level tests exercise the header and the unchanged body shape against a
handful of real rows through each actual endpoint."""

from __future__ import annotations

from app import repo
from app.models import Agent, Run
from app.schemas import SkillIn, SuiteIn
from tests.fakes import FakeOllama
from tests.helpers import REA, make_responder, new_client, start_run, two_models, wait_for


# ------------------------------------------------------------------ 2.1/2.3-2.5 repo-level slicing/counting
def _make_runs(session, n: int) -> None:
    for i in range(n):
        session.add(Run(name=f"r{i}"))
    session.flush()


def _make_agents(session, n: int) -> None:
    for i in range(n):
        session.add(
            Agent(
                name=f"agent-{i}",
                kind="chatbot",
                declared_models={"default": "qwen3:8b"},
                status="active",
                token_hash=f"h{i}",
                token_prefix=f"p{i}",
                eval_config={},
                provider_acks={},
            )
        )
    session.flush()


def _make_skills(session, n: int) -> None:
    for i in range(n):
        repo.create_skill(session, SkillIn(name=f"skill-{i}", description="d", instructions="go"))


def _make_suites(session, n: int) -> None:
    for i in range(n):
        repo.create_suite(session, SuiteIn(name=f"suite-{i}", cases=[]))


def test_list_runs_defaults_to_at_most_50_and_an_explicit_slice_works(session):
    _make_runs(session, 55)
    assert len(repo.list_runs(session)) == 50
    page_2 = repo.list_runs(session, limit=50, offset=50)
    assert len(page_2) == 5
    assert repo.count_runs(session) == 55
    narrow = repo.list_runs(session, limit=10, offset=20)
    assert len(narrow) == 10


def test_list_agents_defaults_to_at_most_50_and_an_explicit_slice_works(session):
    _make_agents(session, 55)
    assert len(repo.list_agents(session)) == 50
    assert len(repo.list_agents(session, limit=50, offset=50)) == 5
    assert repo.count_agents(session) == 55


def test_list_skills_defaults_to_at_most_50_and_an_explicit_slice_works(session):
    _make_skills(session, 55)
    assert len(repo.list_skills(session)) == 50
    assert len(repo.list_skills(session, limit=50, offset=50)) == 5
    assert repo.count_skills(session) == 55


def test_list_suites_defaults_to_at_most_50_and_an_explicit_slice_works(session):
    _make_suites(session, 55)
    assert len(repo.list_suites(session)) == 50
    assert len(repo.list_suites(session, limit=50, offset=50)) == 5
    assert repo.count_suites(session) == 55


# ------------------------------------------------------------------ 2.2/2.6 API-level header + unchanged body shape
def test_get_runs_reports_x_total_count_and_keeps_a_bare_array_body(settings, file_session_factory):
    fake = FakeOllama(two_models(), make_responder())
    with new_client(settings, file_session_factory, fake) as c:
        a = start_run(c, ["a:1"], [REA])
        wait_for(c, a["id"])
        b = start_run(c, ["a:1"], [REA])
        wait_for(c, b["id"])

        resp = c.get("/api/runs")
        assert resp.headers["x-total-count"] == "2"
        assert isinstance(resp.json(), list) and len(resp.json()) == 2  # bare array, not wrapped

        sliced = c.get("/api/runs", params={"limit": 1, "offset": 0})
        assert sliced.headers["x-total-count"] == "2"  # total is independent of the requested slice
        assert len(sliced.json()) == 1


def test_get_agents_reports_x_total_count_and_keeps_a_bare_array_body(settings, file_session_factory):
    from tests.test_agents_api import _create_agent

    with new_client(settings, file_session_factory, FakeOllama()) as c:
        _create_agent(c, name="bot-1")
        _create_agent(c, name="bot-2")

        resp = c.get("/api/agents")
        assert resp.headers["x-total-count"] == "2"
        assert isinstance(resp.json(), list) and len(resp.json()) == 2


def test_get_skills_reports_x_total_count_and_keeps_a_bare_array_body(settings, session_factory):
    with new_client(settings, session_factory, FakeOllama()) as c:
        c.post("/api/skills", json={"name": "s1", "description": "d", "instructions": "go"})
        c.post("/api/skills", json={"name": "s2", "description": "d", "instructions": "go"})

        resp = c.get("/api/skills")
        assert resp.headers["x-total-count"] == "2"
        assert isinstance(resp.json(), list) and len(resp.json()) == 2


def test_get_suites_reports_x_total_count_and_keeps_a_bare_array_body(settings, session_factory):
    with new_client(settings, session_factory, FakeOllama()) as c:
        c.post("/api/suites", json={"name": "suite-1", "cases": []})
        c.post("/api/suites", json={"name": "suite-2", "cases": []})

        resp = c.get("/api/suites")
        # the built-in suite(s) already shipped (if any) are included in the total, just like
        # the list itself already includes them today - count against what the list reports.
        assert resp.headers["x-total-count"] == str(len(resp.json()))
