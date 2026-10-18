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
    status: str  # "ok" | "error" | "skipped"
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
