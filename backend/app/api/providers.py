"""Enterprise provider registry API (design D10). Providers hold the *name* of the environment variable with
their key, never the key: no request field accepts one and no response contains one."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app import repo
from app.api.deps import get_session
from app.models import Provider, RegisteredModel
from app.providers.backend import ProviderConfig
from app.providers.errors import ProviderAuthError, ProviderError, ProviderRateLimited, ProviderUnavailable
from app.providers.refs import MAX_MODEL_ID, format_ref, valid_provider_name
from app.providers.secrets import valid_env_name

router = APIRouter(prefix="/api")

ACK_TEXT = (
    "Evaluations send prompts and model outputs to this provider (including other models' answers when it is used "
    "as a judge). Acknowledge that to register it."
)


# ---------------------------------------------------------------- schemas
def _check_env(v: str) -> str:
    ok, reason = valid_env_name(v.strip())
    if not ok:
        raise ValueError(reason)
    return v.strip()


def _check_url(v: str | None) -> str | None:
    if v is None or v == "":
        return None
    u = urlparse(v.strip())
    if u.scheme not in ("http", "https") or not u.netloc:
        raise ValueError("the base URL must start with http:// or https://")
    return v.strip().rstrip("/")


class ProviderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # e.g. an `api_key` field is rejected, not ignored

    kind: Literal["openai", "anthropic"]
    name: str
    key_env: str
    base_url: str | None = None
    acknowledge_data_sharing: bool = False

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not valid_provider_name(v):
            raise ValueError("use 1-40 lowercase letters, digits, '-' or '_' (starting with a letter or digit)")
        return v

    @field_validator("key_env")
    @classmethod
    def _key_env(cls, v: str) -> str:
        return _check_env(v)

    @field_validator("base_url")
    @classmethod
    def _base(cls, v: str | None) -> str | None:
        return _check_url(v)


class ProviderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key_env: str | None = None
    base_url: str | None = None  # empty string clears it

    @field_validator("key_env")
    @classmethod
    def _key_env(cls, v: str | None) -> str | None:
        return None if v is None else _check_env(v)

    @field_validator("base_url")
    @classmethod
    def _base(cls, v: str | None) -> str | None:
        return _check_url(v)


class ModelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1, max_length=MAX_MODEL_ID)
    display_name: str = ""
    reasoning: bool = False
    enabled: bool = True

    @field_validator("model_id")
    @classmethod
    def _id(cls, v: str) -> str:
        if v != v.strip():
            raise ValueError("the model id must not have leading or trailing spaces")
        return v


class ModelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    reasoning: bool | None = None
    display_name: str | None = None


# ---------------------------------------------------------------- serialisation (never includes a key)
def _model_out(p: Provider, m: RegisteredModel) -> dict:
    return {
        "id": m.id,
        "model_id": m.model_id,
        "ref": format_ref(p.name, m.model_id),
        "display_name": m.display_name or m.model_id,
        "enabled": m.enabled,
        "reasoning": m.reasoning,
    }


def _provider_out(request: Request, p: Provider) -> dict:
    return {
        "id": p.id,
        "kind": p.kind,
        "name": p.name,
        "key_env": p.key_env,
        "base_url": p.base_url,
        "key_available": request.app.state.router.keys.available(p.key_env),
        "data_sharing_acknowledged_at": p.ack_at.isoformat() if p.ack_at else None,
        "created_at": p.created_at.isoformat(),
        "models": [_model_out(p, m) for m in p.models],
    }


# ---------------------------------------------------------------- providers
@router.get("/providers")
def list_providers(request: Request, session: Session = Depends(get_session)):
    return [_provider_out(request, p) for p in repo.list_providers(session)]


@router.post("/providers", status_code=201)
def create_provider(body: ProviderIn, request: Request, session: Session = Depends(get_session)):
    if not body.acknowledge_data_sharing:
        raise HTTPException(
            422, detail={"code": "acknowledgment_required", "message": ACK_TEXT, "field": "acknowledge_data_sharing"}
        )
    p = repo.create_provider(
        session, kind=body.kind, name=body.name, key_env=body.key_env, base_url=body.base_url, ack_at=datetime.now(UTC)
    )
    return _provider_out(request, p)


@router.get("/providers/{provider_id}")
def get_provider(provider_id: int, request: Request, session: Session = Depends(get_session)):
    return _provider_out(request, repo.get_provider(session, provider_id))


@router.patch("/providers/{provider_id}")
def update_provider(provider_id: int, body: ProviderUpdate, request: Request, session: Session = Depends(get_session)):
    fields = body.model_fields_set
    p = repo.update_provider(
        session,
        provider_id,
        key_env=body.key_env,
        base_url=body.base_url,
        clear_base_url="base_url" in fields and body.base_url is None,
    )
    return _provider_out(request, p)


@router.delete("/providers/{provider_id}", status_code=204)
def delete_provider(provider_id: int, session: Session = Depends(get_session)):
    repo.delete_provider(session, provider_id)  # 409 while a queued or running run uses it
    return Response(status_code=204)


# ---------------------------------------------------------------- registered models
@router.post("/providers/{provider_id}/models", status_code=201)
def add_model(provider_id: int, body: ModelIn, session: Session = Depends(get_session)):
    p = repo.get_provider(session, provider_id)
    m = repo.add_registered_model(
        session, p.id, body.model_id, display_name=body.display_name, enabled=body.enabled, reasoning=body.reasoning
    )
    return _model_out(p, m)


def _owned(session: Session, provider_id: int, model_pk: int) -> tuple[Provider, RegisteredModel]:
    p, m = repo.get_provider(session, provider_id), repo.get_registered_model(session, model_pk)
    if m.provider_id != p.id:
        raise repo.NotFound(f"model {model_pk} not found under provider {provider_id}")
    return p, m


@router.patch("/providers/{provider_id}/models/{model_pk}")
def update_model(provider_id: int, model_pk: int, body: ModelUpdate, session: Session = Depends(get_session)):
    p, m = _owned(session, provider_id, model_pk)
    m = repo.update_registered_model(
        session, m.id, enabled=body.enabled, reasoning=body.reasoning, display_name=body.display_name
    )
    return _model_out(p, m)


@router.delete("/providers/{provider_id}/models/{model_pk}", status_code=204)
def delete_model(provider_id: int, model_pk: int, session: Session = Depends(get_session)):
    _, m = _owned(session, provider_id, model_pk)
    repo.delete_registered_model(session, m.id)
    return Response(status_code=204)


# ---------------------------------------------------------------- connectivity and discovery
def _backend(request: Request, p: Provider):
    return request.app.state.router.backend_for(ProviderConfig(p.kind, p.name, p.key_env, p.base_url))


def _clean(request: Request, text: str) -> str:
    return request.app.state.router.redactor.redact(text)


def _key_missing(p: Provider) -> dict:
    return {
        "code": "key_not_set",
        "message": f"API key not set: environment variable {p.key_env} is empty. Export it and restart the application.",
    }


@router.post("/providers/{provider_id}/test")
async def test_provider(provider_id: int, request: Request, session: Session = Depends(get_session)):
    """One lightweight authenticated request; the outcome never contains the key."""
    p = repo.get_provider(session, provider_id)
    base = p.base_url or _backend(request, p).default_base_url
    if not request.app.state.router.keys.available(p.key_env):
        return {"status": "key_not_set", "message": _key_missing(p)["message"], "base_url": base}
    try:
        await _backend(request, p).ping()
    except ProviderAuthError as exc:
        msg = f"{_clean(request, str(exc))}. Check the value of {p.key_env}."
        return {"status": "authentication_failed", "message": msg, "base_url": base}
    except ProviderRateLimited as exc:
        return {"status": "rate_limited", "message": _clean(request, str(exc)), "base_url": base}
    except ProviderUnavailable as exc:
        return {"status": "unreachable", "message": _clean(request, str(exc)), "base_url": base}
    except ProviderError as exc:
        return {"status": "error", "message": _clean(request, str(exc)), "base_url": base}
    return {"status": "working", "message": "The provider accepted the key.", "base_url": base}


@router.get("/providers/{provider_id}/available-models")
async def available_models(provider_id: int, request: Request, session: Session = Depends(get_session)):
    """The provider's own model list, with the ones already registered marked. Failing never blocks adding by id."""
    p = repo.get_provider(session, provider_id)
    if not request.app.state.router.keys.available(p.key_env):
        return JSONResponse(status_code=409, content={"detail": _key_missing(p)})
    have = {m.model_id for m in p.models}
    try:
        ids = await _backend(request, p).list_models()
    except ProviderAuthError as exc:
        return _upstream(request, 502, "authentication_failed", f"{exc}. Check the value of {p.key_env}.")
    except ProviderRateLimited as exc:
        return _upstream(request, 502, "rate_limited", str(exc))
    except ProviderUnavailable as exc:
        return _upstream(request, 502, "unreachable", str(exc))
    except ProviderError as exc:
        return _upstream(request, 502, "provider_error", str(exc))
    return {"models": [{"id": i, "already_added": i in have} for i in ids]}


def _upstream(request: Request, status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": {"code": code, "message": _clean(request, message)}})
