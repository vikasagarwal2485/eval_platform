"""Keeps the shared LLM gateway's per-agent model groups in sync with the `Agent` registry's
`declared_models` (design `add-gateway-model-sync`), instead of requiring them to be hand-authored
in the gateway's own `config.yaml`.

A sync attempt never raises and never blocks the agent create/update it's attached to - not every
agent depends on the gateway (`chatbot.py` still calls Ollama directly), so the gateway being
unreachable, unconfigured, or rejecting a request must never stop a registry write from
succeeding. Every outcome - per task type - is reported back as a `SyncResult` for the caller to
fold into its response; nothing here is persisted.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Agent, Provider
from app.providers.refs import is_cloud_ref, parse_ref
from app.schemas import declared_model_fallback_ref, declared_model_ref

logger = logging.getLogger(__name__)

# platform `Provider.kind` -> LiteLLM provider prefix. Verified against a running gateway while
# researching this change: LiteLLM's Azure integration uses `azure/`, not `azure-openai/` (the
# platform's own `kind` string) - openai and anthropic match directly. `ollama` (`add-ollama-provider-kind`)
# uses the same `ollama_chat` prefix the bare-local-ref branch below already uses - a registered Ollama
# model is exactly as local as an unregistered one, just reached via a different Ollama server/base_url.
_LITELLM_PROVIDER_PREFIX = {
    "openai": "openai",
    "anthropic": "anthropic",
    "azure-openai": "azure",
    "ollama": "ollama_chat",
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class SyncResult:
    status: str  # "ok" | "error" | "skipped" | "not_gateway_routed"
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status}
        if self.detail:
            out["detail"] = self.detail
        return out


def agent_slug(name: str) -> str:
    """`<agent-slug>` half of a gateway group name (`add-litellm-gateway-infra`'s
    `<agent-slug>__<task-type>` convention) - a conservative kebab-case fold of the agent's
    registered name, never empty."""
    slug = _SLUG_RE.sub("-", name.lower()).strip("-")
    return slug or "agent"


def model_group_name(slug: str, task_type: str) -> str:
    return f"{slug}__{task_type}"


def fallback_group_name(slug: str, task_type: str) -> str:
    """The gateway group name for a declared model's optional fallback (`add-declared-model-fallback`) - a
    second, fully separate group alongside `model_group_name`'s primary one, named so a caller's per-request
    `fallbacks: [...]` can address it directly (design.md - 'Decisions': a real second group, not a second
    deployment load-balanced under the primary group's own name)."""
    return f"{model_group_name(slug, task_type)}__fallback"


def to_litellm_params(session: Session, ref: str, params: dict[str, Any] | None, settings: Settings) -> dict[str, Any]:
    """Translates one platform model reference (`refs.py`'s bare-name or `@provider/model` format) into the
    `litellm_params` object the gateway's `/model/new`/`/model/update` expects. Never resolves a provider's
    actual key - only the name of the environment variable holding it, exactly as `KeyProvider` already does
    for the platform's own `ModelRouter`. Raises `ValueError` (caught by the caller, turned into an "error"
    `SyncResult`) if the reference names a provider that isn't registered, or a provider kind this platform
    doesn't know how to translate yet."""
    if not is_cloud_ref(ref):
        litellm_params: dict[str, Any] = {"model": f"ollama_chat/{ref}", "api_base": settings.ollama_base_url}
    else:
        model_ref = parse_ref(ref)
        provider = session.scalar(select(Provider).where(Provider.name == model_ref.provider))
        if provider is None:
            raise ValueError(f"no registered provider named '{model_ref.provider}'")
        prefix = _LITELLM_PROVIDER_PREFIX.get(provider.kind)
        if prefix is None:
            raise ValueError(f"no known LiteLLM provider prefix for provider kind '{provider.kind}'")
        litellm_params = {"model": f"{prefix}/{model_ref.model}"}
        if provider.kind == "ollama":
            # no key at all - and unlike the other kinds, this one needs an api_base even when the operator
            # left the provider's own base_url unset, since there's no LiteLLM-side default for ollama_chat
            # the way there is for openai/anthropic/azure's real cloud endpoints.
            litellm_params["api_base"] = provider.base_url or settings.ollama_base_url
        else:
            litellm_params["api_key"] = f"os.environ/{provider.key_env}"
            if provider.base_url:
                litellm_params["api_base"] = provider.base_url
        if provider.api_version:
            litellm_params["api_version"] = provider.api_version
    if params:
        litellm_params.update(params)
    return litellm_params


def custom_kind_endpoint(session: Session, ref: str) -> dict[str, str] | None:
    """`ref`'s connection info if it resolves to a registered `custom`-kind provider
    (`add-custom-model-provider-kind`) - a model with no gateway deployment to create, ever. `None` for every
    other case (a bare/local ref, an unregistered provider, or any other kind), leaving those entirely to
    `to_litellm_params`'s existing resolution and error handling, unchanged. Also reused by `GET
    /api/ingest/v1/whoami` (`app/api/ingest.py`) to decide, per declared task, whether to expose this
    connection info instead of a gateway group name - not private to this module."""
    if not is_cloud_ref(ref):
        return None
    try:
        model_ref = parse_ref(ref)
    except ValueError:
        return None
    provider = session.scalar(select(Provider).where(Provider.name == model_ref.provider))
    if provider is None or provider.kind != "custom":
        return None
    return {"base_url": provider.base_url or "", "model_id": model_ref.model}


def _existing_model_id(client: httpx.Client, group_name: str) -> tuple[str | None, bool]:
    """`(model_id, is_db_backed)` for `group_name` if the gateway already has a deployment under that name,
    else `(None, False)`. A statically configured (`config.yaml`) entry is reported as not db-backed, so the
    caller can refuse to overwrite it rather than silently fighting the static config on every sync."""
    resp = client.get("/model/info")
    resp.raise_for_status()
    for entry in resp.json().get("data", []):
        if entry.get("model_name") == group_name:
            info = entry.get("model_info") or {}
            return info.get("id"), bool(info.get("db_model"))
    return None, False


def _upsert_group(client: httpx.Client, group_name: str, litellm_params: dict[str, Any]) -> SyncResult:
    try:
        model_id, db_backed = _existing_model_id(client, group_name)
        if model_id is not None and not db_backed:
            return SyncResult(
                "error",
                f"'{group_name}' is statically configured in the gateway's own config.yaml - sync "
                "refuses to override it; remove it from config.yaml to let the registry manage it",
            )
        if model_id is None:
            resp = client.post("/model/new", json={"model_name": group_name, "litellm_params": litellm_params})
        else:
            resp = client.post(
                "/model/update",
                json={"model_name": group_name, "litellm_params": litellm_params, "model_info": {"id": model_id}},
            )
        resp.raise_for_status()
        return SyncResult("ok")
    except httpx.HTTPError as exc:
        return SyncResult("error", f"gateway request failed: {exc}")


def _delete_group(client: httpx.Client, group_name: str) -> SyncResult:
    try:
        model_id, db_backed = _existing_model_id(client, group_name)
        if model_id is None:
            return SyncResult("ok")  # already gone - nothing to do
        if not db_backed:
            return SyncResult("error", f"'{group_name}' is statically configured; sync will not remove it")
        resp = client.post("/model/delete", json={"id": model_id})
        resp.raise_for_status()
        return SyncResult("ok")
    except httpx.HTTPError as exc:
        return SyncResult("error", f"gateway request failed: {exc}")


def agent_gateway_group_names(session: Session, agent: Agent) -> list[str]:
    """Every gateway model group `agent` currently has (or would have) a deployment for - primary
    plus fallback, for every declared task type that resolves to a gateway-routable provider
    (skipping `custom`-kind tasks, which have no gateway group at all). Used to scope a minted
    virtual key to exactly this set (`add-agent-playground`, design.md: "scoped to exactly that
    agent's own currently-synced model groups")."""
    slug = agent_slug(agent.name)
    names: list[str] = []
    for task_type, entry in (agent.declared_models or {}).items():
        ref = declared_model_ref(entry)
        if custom_kind_endpoint(session, ref) is not None:
            continue
        names.append(model_group_name(slug, task_type))
        if declared_model_fallback_ref(entry) is not None:
            names.append(fallback_group_name(slug, task_type))
    return names


@dataclass(frozen=True)
class MintResult:
    status: str  # "ok" | "error" | "skipped"
    key: str | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status}
        if self.detail:
            out["detail"] = self.detail
        return out


def _delete_existing_key_by_alias(gateway_url: str, admin_key: str, alias: str, timeout: float) -> None:
    """Best-effort: clears any previously-minted key under `alias` before a (re-)mint - litellm's
    `/key/generate` rejects a `key_alias` that's already in use ("Unique key aliases across all keys
    are required"), which every re-mint after the first would otherwise hit (found live: re-enabling
    playground, or a declared-model change, for an agent that already had a key minted). Swallows any
    failure (including "no such alias", which `/key/delete` itself treats as a no-op, not an error) -
    this is purely clearing the way for the generate call below, whose own result is what actually
    matters; never raises, mirroring every other call in this module."""
    try:
        httpx.post(
            f"{gateway_url.rstrip('/')}/key/delete",
            json={"key_aliases": [alias]},
            headers={"Authorization": f"Bearer {admin_key}"},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        logger.warning("could not pre-delete gateway key alias %r before re-minting: %s", alias, exc)


def mint_virtual_key(session: Session, agent: Agent, settings: Settings) -> MintResult:
    """Mints a gateway virtual key scoped to `agent`'s current gateway-routable groups
    (`agent_gateway_group_names`) - the automation `gateway/README.md` previously documented as a
    manual `curl .../key/generate` an operator ran by hand (`add-agent-playground`). `"skipped"`
    (not an error) when the gateway isn't configured, mirroring `sync_agent_model_groups`'s own
    convention; never raises.

    Every call site names this "re-minting" (enable, rotate, a declared-model change), implying a
    previous key under this agent's alias is replaced - but a bare `/key/generate` doesn't replace
    anything by itself, and litellm enforces globally unique `key_alias` values, so the *second* call
    for the same agent name always failed with a 400 until this pre-delete was added."""
    if not settings.gateway_url:
        return MintResult("skipped", detail="no gateway configured (EVAL_GATEWAY_URL unset)")
    admin_key = os.environ.get("EVAL_GATEWAY_ADMIN_KEY")
    if not admin_key:
        return MintResult("skipped", detail="no gateway admin credential configured")

    alias = agent_slug(agent.name)
    _delete_existing_key_by_alias(settings.gateway_url, admin_key, alias, settings.gateway_sync_timeout_s)

    groups = agent_gateway_group_names(session, agent)
    try:
        resp = httpx.post(
            f"{settings.gateway_url.rstrip('/')}/key/generate",
            json={"models": groups, "key_alias": alias},
            headers={"Authorization": f"Bearer {admin_key}"},
            timeout=settings.gateway_sync_timeout_s,
        )
        resp.raise_for_status()
        key = resp.json().get("key")
        if not key:
            return MintResult("error", detail="gateway response had no 'key' field")
        return MintResult("ok", key=key)
    except httpx.HTTPError as exc:
        return MintResult("error", detail=f"gateway request failed: {exc}")


def sync_agent_model_groups(
    session: Session,
    agent: Agent,
    settings: Settings,
    *,
    previous_declared_models: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Creates/updates the gateway's `<agent-slug>__<task-type>` model group for every entry in
    `agent.declared_models`, and removes the group for any task type present in
    `previous_declared_models` (an update's pre-change map) but no longer declared. When a
    declared model carries a `fallback` reference (`add-declared-model-fallback`), its own
    `<agent-slug>__<task-type>__fallback` group is kept in sync the same way, reported under the
    key `"<task_type>__fallback"` - created/updated while the fallback is set, removed if the
    fallback is cleared (task type still declared) or the task type itself is removed. A fallback
    reference that fails to resolve (e.g. its provider was since removed) reports an error under
    that key without touching any already-existing fallback group - mirroring exactly how a
    broken *primary* reference is handled below, rather than introducing different behavior for
    the fallback case. Returns one `SyncResult` (as a plain dict, ready to put straight in an API
    response) per affected task type (and, where relevant, per `<task_type>__fallback`);
    `{"*": ...}` when sync could not even be attempted. Never raises."""
    if not settings.gateway_url:
        return {"*": SyncResult("skipped", "no gateway configured (EVAL_GATEWAY_URL unset)").as_dict()}
    admin_key = os.environ.get("EVAL_GATEWAY_ADMIN_KEY")
    if not admin_key:
        return {"*": SyncResult("skipped", "no gateway admin credential configured").as_dict()}

    slug = agent_slug(agent.name)
    results: dict[str, dict[str, Any]] = {}
    try:
        client = httpx.Client(
            base_url=settings.gateway_url,
            timeout=settings.gateway_sync_timeout_s,
            headers={"Authorization": f"Bearer {admin_key}"},
        )
    except Exception as exc:  # noqa: BLE001 - a malformed gateway_url must not crash the caller
        return {"*": SyncResult("error", f"could not reach gateway: {exc}").as_dict()}

    try:
        current = agent.declared_models or {}
        previous = previous_declared_models or {}
        removed_task_types = set(previous) - set(current)
        for task_type in removed_task_types:
            results[task_type] = _delete_group(client, model_group_name(slug, task_type)).as_dict()
            prev_entry = previous.get(task_type)
            if prev_entry is not None and declared_model_fallback_ref(prev_entry) is not None:
                fb_key = f"{task_type}__fallback"
                results[fb_key] = _delete_group(client, fallback_group_name(slug, task_type)).as_dict()

        for task_type, entry in current.items():
            ref = declared_model_ref(entry)
            params = entry.get("params") if isinstance(entry, dict) else None

            if custom_kind_endpoint(session, ref) is not None:
                # Never gateway-routed - an explicit status, not an error (add-custom-model-provider-kind). Any
                # fallback this task type declares doesn't apply either: there is no primary group to fall back
                # from. Clean up whatever gateway groups this task type may have had from a prior,
                # gateway-routable declared model - `_delete_group` is a no-op if there's nothing to remove.
                _delete_group(client, model_group_name(slug, task_type))
                _delete_group(client, fallback_group_name(slug, task_type))
                results[task_type] = SyncResult(
                    "not_gateway_routed", "custom-kind model; not routed through the gateway"
                ).as_dict()
                continue

            try:
                litellm_params = to_litellm_params(session, ref, params, settings)
            except ValueError as exc:
                results[task_type] = SyncResult("error", str(exc)).as_dict()
                continue
            results[task_type] = _upsert_group(client, model_group_name(slug, task_type), litellm_params).as_dict()

            fallback_ref = declared_model_fallback_ref(entry)
            prev_entry = previous.get(task_type)
            prev_fallback_ref = declared_model_fallback_ref(prev_entry) if prev_entry is not None else None
            fb_key = f"{task_type}__fallback"
            if fallback_ref is not None:
                try:
                    fallback_params = to_litellm_params(session, fallback_ref, params, settings)
                except ValueError as exc:
                    results[fb_key] = SyncResult("error", str(exc)).as_dict()
                else:
                    results[fb_key] = _upsert_group(
                        client, fallback_group_name(slug, task_type), fallback_params
                    ).as_dict()
            elif prev_fallback_ref is not None:
                # the fallback was cleared but the task type is still declared - remove its now-orphaned
                # gateway group rather than leaving it configured but unreferenced by anything
                results[fb_key] = _delete_group(client, fallback_group_name(slug, task_type)).as_dict()
    finally:
        client.close()
    return results
