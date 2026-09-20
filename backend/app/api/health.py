from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.ollama.client import OllamaError, OllamaUnreachable
from app.schemas import ModelInfo

router = APIRouter(prefix="/api")


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
        "config": settings.public(),
    }


@router.get("/models", response_model=list[ModelInfo])
async def list_models(request: Request, refresh: bool = False):
    try:
        return await request.app.state.discovery.list_models(refresh=refresh)
    except OllamaUnreachable as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ollama_unreachable",
                "message": str(exc),
                "base_url": request.app.state.settings.ollama_base_url,
            },
        ) from None
