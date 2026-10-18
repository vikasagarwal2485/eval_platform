from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app import repo
from app.ollama.client import OllamaError, OllamaUnreachable
from app.providers.backend import provider_availability
from app.providers.refs import format_ref
from app.schemas import ModelInfo

router = APIRouter(prefix="/api")

NOT_REGISTERED_REASON = (
    "not registered under a provider - add it on the Models page to use it in a run or declare it for an agent"
)


def _providers_status(request: Request) -> list[dict]:
    keys = request.app.state.router.keys
    with request.app.state.session_factory() as s:
        return [
            {
                "name": p.name,
                "kind": p.kind,
                "key_env": p.key_env,
                "key_available": provider_availability(p, keys)[0],
            }
            for p in repo.list_providers(s)
        ]


def _disabled_or(ok: bool, reason: str | None, m) -> tuple[bool, str | None]:
    """A model disabled on the Models page is unavailable for that reason alone, regardless of whether its
    provider is otherwise fine - takes priority so the real blocker is always the one shown."""
    if not m.enabled:
        return False, "disabled on the Models page - enable it there to use it"
    return ok, reason


def _capabilities(m) -> list[str]:
    caps = ["completion"]
    if m.reasoning:
        caps.append("thinking")
    if m.classification:
        caps.append("classification")
    return caps


def cloud_models(request: Request) -> list[ModelInfo]:
    """Every registered enterprise model, each marked available or not - a key that's present but actually
    failing (per the provider's last "Test connection" result - `add-provider-availability-gating`), or the
    model itself disabled on the Models page, is caught here too, not just an empty env var. A disabled model
    is still listed (never silently dropped - `add-model-classification-tag`), just shown unavailable with the
    reason, the same way a failed-key model already was. Excludes models registered under an `ollama`-kind
    provider (`add-ollama-provider-kind`) - those are local, not cloud; see `_registered_ollama_models`."""
    keys = request.app.state.router.keys
    out: list[ModelInfo] = []
    with request.app.state.session_factory() as s:
        for m in repo.list_registered_models(s):
            p = m.provider
            if p.kind == "ollama":
                continue
            ok, reason = _disabled_or(*provider_availability(p, keys), m)
            out.append(
                ModelInfo(
                    name=format_ref(p.name, m.model_id),
                    digest="",
                    source="cloud",
                    provider=p.name,
                    provider_kind=p.kind,
                    display_name=m.display_name or m.model_id,
                    reasoning=m.reasoning,
                    classification=m.classification,
                    capabilities=_capabilities(m),
                    thinking=m.reasoning,
                    available=ok,
                    unavailable_reason=reason,
                )
            )
    return out


def _registered_ollama_models(request: Request, discovered: dict[str, ModelInfo] | None) -> list[ModelInfo]:
    """Models registered one-by-one under an `ollama`-kind provider (`add-ollama-provider-kind`), the same way an
    enterprise model is - but availability depends on the provider's own last "Test connection" result and
    whether this specific model is still actually pulled, never an API key (there is none). Tagged
    `source="local"`, not `"cloud"`, and exempt from the data-sharing acknowledgment everywhere else in the
    platform - nothing about this model call ever leaves the machine. `discovered` (name -> its live `ModelInfo`
    from Ollama's own discovery) is `None` when Ollama itself could not be reached at all; when a model is
    currently pulled, its real parameter size/quantization/family/capabilities are copied from there rather than
    left blank, so a registered entry looks exactly as informative as the bare name it replaces."""
    keys = request.app.state.router.keys
    out: list[ModelInfo] = []
    with request.app.state.session_factory() as s:
        for m in repo.list_registered_models(s):
            p = m.provider
            if p.kind != "ollama":
                continue
            ok, reason = provider_availability(p, keys)
            live = discovered.get(m.model_id) if discovered is not None else None
            if ok and discovered is not None and live is None:
                ok, reason = False, f"model '{m.model_id}' is not currently pulled in Ollama"
            elif ok and discovered is None:
                ok, reason = False, "Ollama unreachable"
            ok, reason = _disabled_or(ok, reason, m)
            out.append(
                ModelInfo(
                    name=format_ref(p.name, m.model_id),
                    digest=live.digest if live else "",
                    size_bytes=live.size_bytes if live else None,
                    parameter_size=live.parameter_size if live else None,
                    quantization=live.quantization if live else None,
                    family=live.family if live else None,
                    capabilities=live.capabilities if live else _capabilities(m),
                    source="local",
                    provider=p.name,
                    provider_kind=p.kind,
                    display_name=m.display_name or m.model_id,
                    reasoning=m.reasoning,
                    classification=m.classification,
                    thinking=live.thinking if live else m.reasoning,
                    available=ok,
                    unavailable_reason=reason,
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


def _unregistered(request: Request, local: list[ModelInfo]) -> list[ModelInfo]:
    """The subset of discovered local models that aren't registered under any `ollama`-kind provider
    (`add-ollama-model-registration-required`): shown, not hidden - removing a model someone knows is pulled
    would just be confusing - but marked unavailable, since registered models are now the only ones selectable
    anywhere a model is picked for an evaluation run or an agent. A model that IS registered is represented by
    its registered (`@provider/model`) entry instead; this list excludes it rather than showing both."""
    with request.app.state.session_factory() as s:
        registered_ids = repo.registered_ollama_model_ids(s)
    return [
        m.model_copy(update={"available": False, "unavailable_reason": NOT_REGISTERED_REASON})
        for m in local
        if m.name not in registered_ids
    ]


@router.get("/models", response_model=list[ModelInfo])
async def list_models(request: Request, refresh: bool = False):
    """Enabled enterprise models, models registered under an `ollama`-kind provider, and any other installed
    Ollama model (shown disabled - see `_unregistered`). Enterprise models stay listed when Ollama is down;
    with nothing registered the old behaviour (503) is kept."""
    cloud = cloud_models(request)
    try:
        local = await request.app.state.discovery.list_models(refresh=refresh)
    except OllamaUnreachable as exc:
        combined = cloud + _registered_ollama_models(request, None)
        if combined:
            return sorted(combined, key=lambda m: m.name)
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ollama_unreachable",
                "message": str(exc),
                "base_url": request.app.state.settings.ollama_base_url,
            },
        ) from None
    ollama_registered = _registered_ollama_models(request, {m.name: m for m in local})
    unregistered = _unregistered(request, local)
    return sorted(unregistered + cloud + ollama_registered, key=lambda m: m.name)
