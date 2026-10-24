import pytest
from fastapi.testclient import TestClient

from app.core.skill_io import MAX_BYTES
from app.main import create_app
from tests.fakes import FakeOllama


@pytest.fixture
def client(settings, session_factory):
    with TestClient(create_app(settings, ollama=FakeOllama(), session_factory=session_factory)) as c:
        yield c


def user_skill(client, name="step-by-step", description="d", instructions="Think step by step."):
    r = client.post("/api/skills", json={"name": name, "description": description, "instructions": instructions})
    assert r.status_code == 201, r.text
    return r.json()


def test_create_list_get(client):
    s = user_skill(client)
    assert s["name"] == "step-by-step" and s["instructions"] == "Think step by step."
    assert [x["name"] for x in client.get("/api/skills").json()] == ["step-by-step"]
    got = client.get(f"/api/skills/{s['id']}").json()
    assert {k: v for k, v in got.items() if k != "created_at"} == {k: v for k, v in s.items() if k != "created_at"}


def test_update_skill(client):
    s = user_skill(client)
    r = client.patch(f"/api/skills/{s['id']}", json={"description": "new desc", "instructions": "New text."})
    assert r.status_code == 200
    assert r.json()["description"] == "new desc" and r.json()["instructions"] == "New text."
    assert r.json()["name"] == s["name"]  # unchanged field preserved


def test_delete_skill(client):
    s = user_skill(client)
    assert client.delete(f"/api/skills/{s['id']}").status_code == 204
    assert client.get(f"/api/skills/{s['id']}").status_code == 404


def test_duplicate_name_conflict(client):
    user_skill(client, "dup")
    assert client.post("/api/skills", json={"name": "dup", "instructions": "x"}).status_code == 409


def test_rename_conflict(client):
    user_skill(client, "a")
    b = user_skill(client, "b")
    assert client.patch(f"/api/skills/{b['id']}", json={"name": "a"}).status_code == 409


def test_empty_instructions_rejected(client):
    r = client.post("/api/skills", json={"name": "x", "instructions": ""})
    assert r.status_code == 422


def test_get_and_delete_unknown_are_404(client):
    assert client.get("/api/skills/9999").status_code == 404
    assert client.delete("/api/skills/9999").status_code == 404


# ------------------------------------------------------------------ import
def test_import_well_formed(client):
    content = "# My Skill\n\nA short description.\n\nStep 1. Do the thing.\n\nStep 2. Check it."
    r = client.post("/api/skills/import", json={"content": content, "filename": "my-skill.md"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "My Skill"
    assert body["description"] == "A short description."
    assert body["instructions"] == "Step 1. Do the thing.\n\nStep 2. Check it."


def test_import_no_instructions_body_rejected_like_direct_authoring(client):
    before = len(client.get("/api/skills").json())
    r = client.post("/api/skills/import", json={"content": "Name only"})
    assert r.status_code == 422
    assert r.json()["detail"]["errors"][0]["field"] == "instructions"
    assert len(client.get("/api/skills").json()) == before


def test_import_oversized_rejected(client):
    content = "name\n\ndesc\n\n" + ("x" * (MAX_BYTES + 1))
    r = client.post("/api/skills/import", json={"content": content})
    assert r.status_code == 422
    assert "size limit" in r.json()["detail"]["errors"][0]["message"]


def test_import_non_markdown_filename_rejected(client):
    content = "name\n\ndesc\n\ninstructions body"
    r = client.post("/api/skills/import", json={"content": content, "filename": "notes.txt"})
    assert r.status_code == 422
    assert "Markdown" in r.json()["detail"]["errors"][0]["message"]


def test_import_name_conflict(client):
    user_skill(client, "same")
    content = "same\n\ndesc\n\ninstructions body"
    assert client.post("/api/skills/import", json={"content": content}).status_code == 409
