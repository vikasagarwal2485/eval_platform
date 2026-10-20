"""Enterprise provider registry API (design D10). Providers hold the *name* of the environment variable with
their key, never the key: no request field accepts one and no response contains one."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app import repo
from app.api.deps import get_session
from app.models import Provider, RegisteredModel
from app.providers.backend import ProviderConfig, provider_availability
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


def _check_api_version(v: str | None) -> str | None:
    if v is None or v == "":
        return None
    v = v.strip()
    if not v or len(v) > 50:
        raise ValueError("the API version must be 1-50 characters")
    return v


def _check_reasoning_effort(v: str | None) -> str | None:
    if v is None or v == "":
        return None
    v = v.strip()
    if not v or len(v) > 20:
        raise ValueError("the reasoning effort must be 1-20 characters")
    return v


class ProviderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # e.g. an `api_key` field is rejected, not ignored

    kind: Literal["openai", "anthropic", "azure-openai", "ollama", "custom"]
    name: str
    key_env: str | None = None  # not applicable to `ollama`/`custom` - neither has a key at all
    base_url: str | None = None  # for `ollama`/`custom`, this is that server's own address
    api_version: str | None = None  # required for azure-openai; unused by other kinds
    # Only meaningful for `kind == "custom"` - the path "Test connection" calls (never a chat completion);
    # a documented default applies when unset (`add-custom-model-provider-kind`).
    health_check_path: str | None = None
    acknowledge_data_sharing: bool = False  # not required for `ollama`/`custom` - nothing leaves the machine

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not valid_provider_name(v):
            raise ValueError("use 1-40 lowercase letters, digits, '-' or '_' (starting with a letter or digit)")
        return v

    @field_validator("key_env")
    @classmethod
    def _key_env(cls, v: str | None) -> str | None:
        return None if v is None else _check_env(v)

    @field_validator("base_url")
    @classmethod
    def _base(cls, v: str | None) -> str | None:
        return _check_url(v)

    @field_validator("api_version")
    @classmethod
    def _version(cls, v: str | None) -> str | None:
        return _check_api_version(v)

    @field_validator("health_check_path")
    @classmethod
    def _health_path(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        v = v.strip()
        if not v.startswith("/"):
            raise ValueError("the health-check path must start with '/'")
        return v

    @model_validator(mode="after")
    def _azure_requires_endpoint(self) -> ProviderIn:
        if self.kind == "azure-openai":
            missing = [name for name, v in (("base_url", self.base_url), ("api_version", self.api_version)) if not v]
            if missing:
                raise ValueError(
                    "azure-openai requires "
                    + " and ".join(missing)
                    + " (the Azure resource endpoint and its API version)"
                )
        return self

    @model_validator(mode="after")
    def _custom_requires_base_url(self) -> ProviderIn:
        if self.kind == "custom" and not self.base_url:
            raise ValueError("custom requires a base URL - it has no shared default endpoint")
        return self

    @model_validator(mode="after")
    def _non_ollama_requires_key_env(self) -> ProviderIn:
        if self.kind not in ("ollama", "custom") and not self.key_env:
            raise ValueError("key_env is required for every provider kind except 'ollama' and 'custom'")
        return self


class ProviderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key_env: str | None = None
    base_url: str | None = None  # empty string clears it
    api_version: str | None = None  # empty string clears it
    health_check_path: str | None = None  # empty string clears it; only meaningful for `kind == "custom"`

    @field_validator("key_env")
    @classmethod
    def _key_env(cls, v: str | None) -> str | None:
        return None if v is None else _check_env(v)

    @field_validator("base_url")
    @classmethod
    def _base(cls, v: str | None) -> str | None:
        return _check_url(v)

    @field_validator("api_version")
    @classmethod
    def _version(cls, v: str | None) -> str | None:
        return _check_api_version(v)

    @field_validator("health_check_path")
    @classmethod
    def _health_path(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        v = v.strip()
        if not v.startswith("/"):
            raise ValueError("the health-check path must start with '/'")
        return v


class ModelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1, max_length=MAX_MODEL_ID)
    display_name: str = ""
    reasoning: bool = False
    reasoning_effort: str | None = None  # only meaningful when reasoning is True
    classification: bool = False
    enabled: bool = True

    @field_validator("model_id")
    @classmethod
    def _id(cls, v: str) -> str:
        if v != v.strip():
            raise ValueError("the model id must not have leading or trailing spaces")
        return v

    @field_validator("reasoning_effort")
    @classmethod
    def _effort(cls, v: str | None) -> str | None:
        return _check_reasoning_effort(v)


class ModelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    reasoning: bool | None = None
    classification: bool | None = None
    display_name: str | None = None
    reasoning_effort: str | None = None  # empty string clears it

    @field_validator("reasoning_effort")
    @classmethod
    def _effort(cls, v: str | None) -> str | None:
        return _check_reasoning_effort(v)


# ---------------------------------------------------------------- serialisation (never includes a key)
def _model_out(p: Provider, m: RegisteredModel) -> dict:
    return {
        "id": m.id,
        "model_id": m.model_id,
        "ref": format_ref(p.name, m.model_id),
        "display_name": m.display_name or m.model_id,
        "enabled": m.enabled,
        "reasoning": m.reasoning,
        "reasoning_effort": m.reasoning_effort,
        "classification": m.classification,
    }


def _provider_out(request: Request, p: Provider) -> dict:
    # `key_available` now means "actually usable", not just "a key is present" (`add-provider-availability-gating`)
    # - it folds in the last "Test connection" outcome, if one was ever run, so a present-but-wrong key (or an
    # unreachable Ollama server) stops showing as ready the moment it's been caught once.
    available, reason = provider_availability(p, request.app.state.router.keys)
    return {
        "id": p.id,
        "kind": p.kind,
        "name": p.name,
        "key_env": p.key_env,
        "base_url": p.base_url,
        "api_version": p.api_version,
        "health_check_path": p.health_check_path,
        "key_available": available,
        "unavailable_reason": reason,
        "last_test_status": p.last_test_status,
        "last_test_message": p.last_test_message,
        "last_test_at": p.last_test_at.isoformat() if p.last_test_at else None,
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
    # `ollama`/`custom` send nothing to anyone - the data-sharing acknowledgment this gate exists for simply
    # does not apply to either (see ProviderIn's docstring field comments).
    if body.kind not in ("ollama", "custom") and not body.acknowledge_data_sharing:
        raise HTTPException(
            422, detail={"code": "acknowledgment_required", "message": ACK_TEXT, "field": "acknowledge_data_sharing"}
        )
    p = repo.create_provider(
        session,
        kind=body.kind,
        name=body.name,
        key_env=body.key_env,
        base_url=body.base_url,
        api_version=body.api_version,
        health_check_path=body.health_check_path,
        # Neither `ollama` nor `custom` is ever asked to acknowledge data sharing, so neither has anything to
        # timestamp here either.
        ack_at=None if body.kind in ("ollama", "custom") else datetime.now(UTC),
    )
    return _provider_out(request, p)


@router.get("/providers/{provider_id}")
def get_provider(provider_id: int, request: Request, session: Session = Depends(get_session)):
    return _provider_out(request, repo.get_provider(session, provider_id))


@router.patch("/providers/{provider_id}")
def update_provider(provider_id: int, body: ProviderUpdate, request: Request, session: Session = Depends(get_session)):
    fields = body.model_fields_set
    current = repo.get_provider(session, provider_id)
    clear_base_url = "base_url" in fields and body.base_url is None
    clear_api_version = "api_version" in fields and body.api_version is None
    if current.kind == "azure-openai" and (clear_base_url or clear_api_version):
        raise HTTPException(
            422,
            detail={
                "code": "azure_requires_endpoint",
                "message": "azure-openai requires a base URL and an API version; they cannot be cleared.",
            },
        )
    clear_health_check_path = "health_check_path" in fields and body.health_check_path is None
    p = repo.update_provider(
        session,
        provider_id,
        key_env=body.key_env,
        base_url=body.base_url,
        clear_base_url=clear_base_url,
        api_version=body.api_version,
        clear_api_version=clear_api_version,
        health_check_path=body.health_check_path,
        clear_health_check_path=clear_health_check_path,
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
        session,
        p.id,
        body.model_id,
        display_name=body.display_name,
        enabled=body.enabled,
        reasoning=body.reasoning,
        reasoning_effort=body.reasoning_effort,
        classification=body.classification,
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
    fields = body.model_fields_set
    m = repo.update_registered_model(
        session,
        m.id,
        enabled=body.enabled,
        reasoning=body.reasoning,
        classification=body.classification,
        display_name=body.display_name,
        reasoning_effort=body.reasoning_effort,
        clear_reasoning_effort="reasoning_effort" in fields and body.reasoning_effort is None,
    )
    return _model_out(p, m)


@router.delete("/providers/{provider_id}/models/{model_pk}", status_code=204)
def delete_model(provider_id: int, model_pk: int, session: Session = Depends(get_session)):
    _, m = _owned(session, provider_id, model_pk)
    repo.delete_registered_model(session, m.id)
    return Response(status_code=204)


# ---------------------------------------------------------------- connectivity and discovery
def _backend(request: Request, p: Provider):
    return request.app.state.router.backend_for(ProviderConfig(p.kind, p.name, p.key_env, p.base_url, p.api_version))


def _clean(request: Request, text: str) -> str:
    return request.app.state.router.redactor.redact(text)


def _key_missing(p: Provider) -> dict:
    return {
        "code": "key_not_set",
        "message": f"API key not set: environment variable {p.key_env} is empty. Export it and restart the application.",
    }


def _first_enabled_deployment(p: Provider) -> RegisteredModel | None:
    return next((m for m in p.models if m.enabled), None)


async def _run_custom_health_check(request: Request, base: str, path: str | None) -> dict:
    """A `custom` provider has no chat-completions surface to ping (`add-custom-model-provider-kind`) - this is
    a plain, unauthenticated GET at a configurable health-check path (`/health` when unset), never a chat call.
    A 2xx response is "working"; a connection failure or timeout is "unreachable"; anything else is a generic
    "error" naming the status code, since a non-2xx response isn't one of the provider-specific failure shapes
    (auth/rate-limit) every other kind's `ping()` can distinguish - a custom service has no agreed-upon shape for
    those at all. Uses the same injected transport every other provider kind's test calls already use, when one
    is configured (tests only; `None` in production means a real connection)."""
    url = base + (path or "/health")
    transport = request.app.state.provider_transport
    try:
        async with httpx.AsyncClient(timeout=10.0, transport=transport) as c:
            resp = await c.get(url)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        return {"status": "unreachable", "message": f"could not reach {url}: {exc}", "base_url": base}
    if resp.is_success:
        return {"status": "working", "message": f"{url} responded successfully.", "base_url": base}
    return {"status": "error", "message": f"{url} responded with status {resp.status_code}.", "base_url": base}


async def _run_connection_test(request: Request, p: Provider, base: str) -> dict:
    """The actual test, isolated from persistence so `test_provider` can store whatever this returns
    (`add-provider-availability-gating`) regardless of which branch produced it."""
    if p.kind == "custom":
        return await _run_custom_health_check(request, base, p.health_check_path)
    if p.kind != "ollama" and not request.app.state.router.keys.available(p.key_env):
        return {"status": "key_not_set", "message": _key_missing(p)["message"], "base_url": base}
    deployment, deployment_reasoning = None, False
    if p.kind == "azure-openai":
        # there is no provider-wide endpoint to ping; a deployment must exist to test against one (design D8)
        model = _first_enabled_deployment(p)
        if model is None:
            return {
                "status": "no_deployments",
                "message": "Register a deployment first, then test the connection against it.",
                "base_url": base,
            }
        deployment, deployment_reasoning = model.model_id, model.reasoning
    try:
        await _backend(request, p).ping(model=deployment, reasoning=deployment_reasoning)
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


@router.post("/providers/{provider_id}/test")
async def test_provider(provider_id: int, request: Request, session: Session = Depends(get_session)):
    """One lightweight authenticated request; the outcome never contains the key. `ollama` has no key to check -
    this just pings the server itself. The outcome is persisted (`add-provider-availability-gating`) so
    `provider_availability` can later decide whether to offer this provider's models anywhere, without
    re-pinging it on every page load - testing again is how a stale result gets refreshed."""
    p = repo.get_provider(session, provider_id)
    base = p.base_url or _backend(request, p).default_base_url
    result = await _run_connection_test(request, p, base)
    repo.record_provider_test_result(session, p.id, status=result["status"], message=result["message"])
    return result


@router.get("/providers/{provider_id}/available-models")
async def available_models(provider_id: int, request: Request, session: Session = Depends(get_session)):
    """The provider's own model list, with the ones already registered marked. Failing never blocks adding by
    id. `ollama` has no key to check - this lists whatever is currently pulled on that server."""
    p = repo.get_provider(session, provider_id)
    if p.kind not in ("ollama", "custom") and not request.app.state.router.keys.available(p.key_env):
        return JSONResponse(status_code=409, content={"detail": _key_missing(p)})
    if p.kind == "azure-openai":
        # no inference-plane endpoint lists deployments (design D9); never attempt a call that always fails
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "not_supported",
                    "message": "Azure OpenAI deployments cannot be auto-discovered; add a deployment by name.",
                }
            },
        )
    if p.kind == "custom":
        # a custom service has no agreed-upon listing endpoint shape (`add-custom-model-provider-kind`); never
        # attempt a call that assumes one
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "not_supported",
                    "message": "A custom provider's models cannot be auto-discovered; add a model id by hand.",
                }
            },
        )
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
