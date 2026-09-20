"""10.1: one process serves the SPA and the API on a single URL."""

import dataclasses

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.fakes import FakeOllama


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><title>LLM Eval Platform</title><div id=root></div>")
    (d / "assets" / "app.js").write_text("console.log('spa')")
    (d / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("TOP SECRET")
    return d


@pytest.fixture
def client(settings, file_session_factory, dist):
    s = dataclasses.replace(settings, frontend_dist=dist)
    with TestClient(create_app(s, ollama=FakeOllama(), session_factory=file_session_factory)) as c:
        yield c


def test_root_serves_index(client):
    r = client.get("/")
    assert r.status_code == 200 and "LLM Eval Platform" in r.text and r.headers["content-type"].startswith("text/html")


def test_client_side_routes_fall_back_to_index(client):
    for path in ("/runs/12", "/runs/12/live", "/suites", "/history"):
        assert "id=root" in client.get(path).text, path


def test_assets_and_root_files_are_served(client):
    assert client.get("/assets/app.js").text == "console.log('spa')"
    assert client.get("/favicon.svg").text == "<svg/>"


def test_api_routes_take_precedence_and_unknown_api_paths_404_as_json(client):
    assert client.get("/api/health").json()["ollama"]["reachable"] is True
    r = client.get("/api/definitely-not-a-route")
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")
    assert client.get("/api").status_code == 404


@pytest.mark.parametrize(
    "path", ["/../secret.txt", "/%2e%2e/secret.txt", "/..%2fsecret.txt", "/assets/../../secret.txt"]
)
def test_cannot_read_files_outside_dist(client, path):
    r = client.get(path)
    assert "TOP SECRET" not in r.text


def test_no_frontend_build_means_api_only(settings, file_session_factory, tmp_path):
    s = dataclasses.replace(settings, frontend_dist=tmp_path / "missing")
    with TestClient(create_app(s, ollama=FakeOllama(), session_factory=file_session_factory)) as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/").status_code == 404
