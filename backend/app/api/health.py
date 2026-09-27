from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app import repo
from app.ollama.client import OllamaError, OllamaUnreachable
from app.providers.refs import format_ref
from app.schemas import ModelInfo

router = APIRouter(prefix="/api")


def _providers_status(request: Request) -> list[dict]:
    keys = request.app.state.router.keys
    with request.app.state.session_factory() as s:
        return [
            {"name": p.name, "kind": p.kind, "key_env": p.key_env, "key_available": keys.available(p.key_env)}
            for p in repo.list_providers(s)
        ]


def cloud_models(request: Request) -> list[ModelInfo]:
    """Enabled enterprise models from the registry, each marked available or not (key present)."""
    keys = request.app.state.router.keys
    out: list[ModelInfo] = []
    with request.app.state.session_factory() as s:
        for m in repo.list_registered_models(s, enabled_only=True):
            p = m.provider
            ok = keys.available(p.key_env)
            out.append(
                ModelInfo(
                    name=format_ref(p.name, m.model_id),
                    digest="",
                    source="cloud",
                    provider=p.name,
                    provider_kind=p.kind,
                    display_name=m.display_name or m.model_id,
                    reasoning=m.reasoning,
                    capabilities=["completion"] + (["thinking"] if m.reasoning else []),
                    thinking=m.reasoning,
                    available=ok,
                    unavailable_reason=None if ok else f"API key not set: environment variable {p.key_env} is empty",
                )
            )
    return out


@router.get("/health")
async def health(request: Request):
    settings = request.app.state.settings
    ollama = request.app.state.ollama
    info: dict = {"reachable": False, "base_url": settings.ollama_base_url, "version": None, "error": None}
    try:
        info["version"] = await ollama.version()
        info["reachable"] = True
    except OllamaError as exc:
        info["error"] = str(exc)
    return {
        "status": "ok" if info["reachable"] else "ollama_unreachable",
        "ollama": info,
        "providers": _providers_status(request),
        "config": settings.public(),
    }


@router.get("/models", response_model=list[ModelInfo])
async def list_models(request: Request, refresh: bool = False):
    """Installed Ollama models plus enabled enterprise models. Enterprise models stay listed when Ollama is down;
    with nothing registered the old behaviour (503) is kept."""
    cloud = cloud_models(request)
    try:
        local = await request.app.state.discovery.list_models(refresh=refresh)
    except OllamaUnreachable as exc:
        if cloud:
            return sorted(cloud, key=lambda m: m.name)
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ollama_unreachable",
                "message": str(exc),
                "base_url": request.app.state.settings.ollama_base_url,
            },
        ) from None
    return list(local) + sorted(cloud, key=lambda m: m.name)
