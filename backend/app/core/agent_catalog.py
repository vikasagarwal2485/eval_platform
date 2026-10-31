"""Loads `agents/catalog.yaml` (add-agent-playground, design.md D3) - the static, repo-shipped list
of runnable agent flavors (`chatbot`/`reasoning`/`router`), each naming its entrypoint command, the
declared-model task slots its kind expects, and the CLI flags it accepts for a playground spawn.

Parsed once per process, mirroring `app.core.cost`'s `_load_prices()` caching pattern. Tests that
swap the catalog file must call `load_catalog.cache_clear()`."""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.config import ROOT_DIR

_CATALOG_FILE = ROOT_DIR / "agents" / "catalog.yaml"


@dataclass(frozen=True)
class AgentFlavor:
    id: str
    kind: str
    description: str
    entrypoint: list[str]
    cwd: str
    task_slots: list[str]
    accepts: list[str]
    # Empty for a flavor whose script has no concept of hand-off targets at all (every flavor but
    # `router` today). For a flavor that does, the kinds of hand-off target its *script* actually
    # knows how to spawn - a property of that script, never of the registry, which places no limit
    # on how many hand-off agents an agent may declare or what kind they are
    # (`add-agent-playground`/`add-chatbot-handoff`). `classifier_router_agent.py` resolves, among
    # its router's configured `handoff_agent_names`, at most one agent of each kind listed here -
    # "at most one of each listed kind" is this field's whole contract, not a count to compare
    # against the list's total length.
    handoff_kinds: list[str] = field(default_factory=list)


@functools.lru_cache(maxsize=1)
def load_catalog() -> dict[str, AgentFlavor]:
    if not _CATALOG_FILE.exists():
        return {}
    data = yaml.safe_load(_CATALOG_FILE.read_text()) or {}
    flavors = {}
    for flavor_id, entry in (data.get("flavors") or {}).items():
        flavors[flavor_id] = AgentFlavor(
            id=flavor_id,
            kind=entry["kind"],
            description=entry.get("description", ""),
            entrypoint=list(entry["entrypoint"]),
            cwd=entry.get("cwd", "."),
            task_slots=list(entry.get("task_slots", [])),
            accepts=list(entry.get("accepts", [])),
            handoff_kinds=list(entry.get("handoff_kinds", [])),
        )
    return flavors


def get_flavor(flavor_id: str) -> AgentFlavor | None:
    return load_catalog().get(flavor_id)


def flavor_root(flavor: AgentFlavor) -> Path:
    """`flavor.cwd` resolved against the repo root - the directory a spawn's subprocess runs in."""
    return ROOT_DIR / flavor.cwd
