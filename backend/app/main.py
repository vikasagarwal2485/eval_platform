"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import app.models  # noqa: F401  (register tables)
from app import repo
from app.api import agents, export, health, ingest, providers, runs, suites
from app.config import Settings, load_settings
from app.core.eval_worker import EvaluationWorker
from app.core.events import EventHub, agent_channel
from app.core.model_discovery import ModelDiscovery
from app.core.runner import Runner
from app.core.suite_io import seed_starter_suite
from app.db import make_engine, make_session_factory
from app.migrate import upgrade_to_head
from app.ollama.client import HttpOllamaClient, OllamaClient
from app.providers.backend import ModelRouter
from app.providers.factories import make_factories


def create_app(
    settings: Settings | None = None,
    ollama: OllamaClient | None = None,
    session_factory=None,
    provider_transport=None,
) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await app.state.runner.start()
        await app.state.eval_worker.start()
        yield
        await app.state.eval_worker.stop()
        await app.state.runner.stop()
        await app.state.router.aclose()  # closes enterprise backends and the Ollama client

    app = FastAPI(title="LLM Eval Platform", lifespan=lifespan)
    app.state.settings = settings
    app.state.ollama = ollama or HttpOllamaClient(settings.ollama_base_url, settings.request_timeout_s)
    app.state.discovery = ModelDiscovery(app.state.ollama)
    if session_factory is None:
        upgrade_to_head(settings.db_url)
        engine = make_engine(settings.db_url)
        session_factory = make_session_factory(engine)
    app.state.session_factory = session_factory

    app.state.hub = EventHub()
    app.state.router = ModelRouter(
        app.state.ollama, session_factory, factories=make_factories(settings, provider_transport)
    )
    app.state.runner = Runner(session_factory, app.state.router, app.state.discovery, app.state.hub, settings)

    async def _publish_eval_event(agent_id: int, type_: str, data: dict) -> None:
        app.state.hub.publish(agent_channel(agent_id), type_, data)

    app.state.eval_worker = EvaluationWorker(
        session_factory,
        app.state.router,
        app.state.discovery,
        is_measuring=app.state.runner.is_measuring,
        on_event=_publish_eval_event,
    )

    with session_factory() as session:
        seed_starter_suite(session)
        session.commit()

    @app.exception_handler(repo.NotFound)
    async def _not_found(_: Request, exc: repo.NotFound):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(repo.Conflict)
    async def _conflict(_: Request, exc: repo.Conflict):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    app.include_router(health.router)
    app.include_router(suites.router)
    app.include_router(providers.router)
    app.include_router(export.router)  # before runs: /runs/compare must not match /runs/{id}
    app.include_router(runs.router)
    app.include_router(ingest.router)
    app.include_router(agents.router)
    _mount_frontend(app, settings)
    return app


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    """Serve the built SPA (if present) so one process/URL serves both UI and API."""
    dist = settings.frontend_dist.resolve()
    if not (dist / "index.html").exists():
        return
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and dist in candidate.parents:  # never serve outside dist/
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")  # client-side routes


def app_factory() -> FastAPI:  # uvicorn --factory app.main:app_factory
    return create_app()
