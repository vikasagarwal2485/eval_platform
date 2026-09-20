import json

import pytest
import yaml
from fastapi.testclient import TestClient

from app.main import create_app
from tests.fakes import FakeOllama

CLS = dict(category="classification", prompt="great!", labels=["positive", "negative"], expected="positive")
REA = dict(category="reasoning", prompt="2+2?", expected="4", comparison="numeric")
GEN = dict(category="generation", prompt="haiku", rubric=[{"name": "form"}], constraints={"max_words": 30})


@pytest.fixture
def client(settings, session_factory):
    with TestClient(create_app(settings, ollama=FakeOllama(), session_factory=session_factory)) as c:
        yield c


def user_suite(client, name="mine", cases=(CLS, REA, GEN)):
    r = client.post("/api/suites", json={"name": name, "cases": list(cases)})
    assert r.status_code == 201, r.text
    return r.json()


def test_create_mixed_suite_and_get(client):
    s = user_suite(client)
    assert s["counts_by_category"] == {"classification": 1, "reasoning": 1, "generation": 1}
    got = client.get(f"/api/suites/{s['id']}").json()
    assert [c["category"] for c in got["cases"]] == ["classification", "reasoning", "generation"]
    assert got["cases"][2]["constraints"]["max_words"] == 30


def test_edit_case_and_suite(client):
    s = user_suite(client)
    cid = s["cases"][0]["id"]
    r = client.put(f"/api/cases/{cid}", json={**CLS, "prompt": "awful", "expected": "negative"})
    assert r.status_code == 200 and r.json()["prompt"] == "awful"
    r = client.patch(f"/api/suites/{s['id']}", json={"name": "renamed"})
    assert r.json()["name"] == "renamed"


def test_add_and_delete_case(client):
    s = user_suite(client, cases=[CLS])
    r = client.post(f"/api/suites/{s['id']}/cases", json=REA)
    assert r.status_code == 201
    assert client.delete(f"/api/cases/{r.json()['id']}").status_code == 204
    assert client.get(f"/api/suites/{s['id']}").json()["case_count"] == 1


def test_validation_errors_are_422(client):
    r = client.post("/api/suites", json={"name": "x", "cases": [{**CLS, "expected": "neutral"}]})
    assert r.status_code == 422
    r = client.post("/api/suites", json={"name": "x", "cases": [{**CLS, "prompt": ""}]})
    assert r.status_code == 422
    r = client.post("/api/suites", json={"name": "x", "cases": [{**CLS, "category": "nope"}]})
    assert r.status_code == 422


def test_duplicate_conflict_and_not_found(client):
    user_suite(client, "dup")
    assert client.post("/api/suites", json={"name": "dup"}).status_code == 409
    assert client.get("/api/suites/9999").status_code == 404
    s = client.get("/api/suites").json()
    mine = next(x for x in s if x["name"] == "dup")
    r = client.post(f"/api/suites/{mine['id']}/duplicate")
    assert r.status_code == 201 and r.json()["name"] == "dup (copy)"


def test_delete_suite(client):
    s = user_suite(client)
    assert client.delete(f"/api/suites/{s['id']}").status_code == 204
    assert client.get(f"/api/suites/{s['id']}").status_code == 404


# ------------------------------------------------------------------ starter suite
def test_fresh_db_contains_starter_suite(client):
    suites = client.get("/api/suites").json()
    starter = next(s for s in suites if s["is_builtin"])
    assert starter["counts_by_category"]["classification"] >= 5
    assert starter["counts_by_category"]["reasoning"] >= 5
    assert starter["counts_by_category"]["generation"] >= 3
    detail = client.get(f"/api/suites/{starter['id']}").json()
    for c in detail["cases"]:
        if c["category"] != "generation":
            assert c["expected"]
        else:
            assert c["rubric"]


def test_starter_seed_is_idempotent(settings, session_factory):
    for _ in range(2):
        with TestClient(create_app(settings, ollama=FakeOllama(), session_factory=session_factory)) as c:
            assert sum(s["is_builtin"] for s in c.get("/api/suites").json()) == 1


def test_builtin_suite_is_read_only_but_duplicable(client):
    starter = next(s for s in client.get("/api/suites").json() if s["is_builtin"])
    assert client.delete(f"/api/suites/{starter['id']}").status_code == 409
    assert client.patch(f"/api/suites/{starter['id']}", json={"name": "x"}).status_code == 409
    assert client.post(f"/api/suites/{starter['id']}/cases", json=CLS).status_code == 409
    dup = client.post(f"/api/suites/{starter['id']}/duplicate").json()
    assert not dup["is_builtin"]
    assert client.post(f"/api/suites/{dup['id']}/cases", json=CLS).status_code == 201


# ------------------------------------------------------------------ import / export
@pytest.mark.parametrize("fmt", ["json", "yaml"])
def test_export_import_roundtrip(client, fmt):
    s = user_suite(client, "rt")
    r = client.get(f"/api/suites/{s['id']}/export?format={fmt}")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    parsed = json.loads(r.text) if fmt == "json" else yaml.safe_load(r.text)
    assert parsed["name"] == "rt" and len(parsed["cases"]) == 3

    imp = client.post("/api/suites/import", json={"content": r.text, "name": "rt-imported"})
    assert imp.status_code == 201, imp.text
    strip = lambda cases: [{k: v for k, v in c.items() if k not in ("id", "suite_id", "position")} for c in cases]
    assert strip(imp.json()["cases"]) == strip(client.get(f"/api/suites/{s['id']}").json()["cases"])


def test_import_name_conflict(client):
    s = user_suite(client, "same")
    text = client.get(f"/api/suites/{s['id']}/export").text
    assert client.post("/api/suites/import", json={"content": text}).status_code == 409


def test_malformed_import_creates_nothing_and_reports_fields(client):
    before = len(client.get("/api/suites").json())
    bad = {"name": "bad", "cases": [CLS, {**REA, "prompt": ""}, {**CLS, "expected": "neutral"}]}
    r = client.post("/api/suites/import", json={"content": json.dumps(bad)})
    assert r.status_code == 422
    fields = {e["field"] for e in r.json()["detail"]["errors"]}
    assert "cases[1].prompt" in fields and "cases[2]" in fields
    assert len(client.get("/api/suites").json()) == before


def test_import_syntax_error_reports_position(client):
    r = client.post("/api/suites/import", json={"content": "name: x\ncases: [\n  - a: : b"})
    assert r.status_code == 422
    assert "line" in r.json()["detail"]["errors"][0]["message"]


# ------------------------------------------------------------------ ad-hoc
def test_adhoc_without_expected_answer_is_valid_and_saveable(client):
    r = client.post(
        "/api/suites/save-adhoc",
        json={"case": {"category": "generation", "prompt": "Write a limerick"}, "new_suite_name": "adhoc"},
    )
    assert r.status_code == 201 and r.json()["expected"] is None


def test_adhoc_with_expected_answer_saved_to_existing_suite(client):
    s = user_suite(client, "target", cases=[])
    r = client.post("/api/suites/save-adhoc", json={"case": CLS, "suite_id": s["id"]})
    assert r.status_code == 201 and r.json()["expected"] == "positive"
    assert client.get(f"/api/suites/{s['id']}").json()["case_count"] == 1


def test_adhoc_save_requires_target_and_valid_case(client):
    assert client.post("/api/suites/save-adhoc", json={"case": CLS}).status_code == 422
    r = client.post("/api/suites/save-adhoc", json={"case": {**CLS, "expected": "zzz"}, "new_suite_name": "n"})
    assert r.status_code == 422
