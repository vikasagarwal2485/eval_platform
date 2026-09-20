"""In-memory per-run event hub feeding the SSE endpoint.

Buffered events let a reconnecting client catch up; `token` events are live-only. The database is the
source of truth - the client resyncs via GET /api/runs/{id} (design D4).
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

TERMINAL = {"run_finished", "rescore_finished"}
BUFFER_LIMIT = 2000


@dataclass
class Event:
    id: int
    type: str
    data: dict


@dataclass
class _RunStream:
    events: list[Event] = field(default_factory=list)
    next_id: int = 1
    active: bool = False
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    current: dict = field(default_factory=dict)


class EventHub:
    def __init__(self) -> None:
        self._runs: dict[int, _RunStream] = defaultdict(_RunStream)

    def begin(self, run_id: int) -> None:
        """A new job for this run starts: reset the buffer."""
        s = self._runs[run_id]
        s.events.clear()
        s.current = {}
        s.active = True

    def is_active(self, run_id: int) -> bool:
        return run_id in self._runs and self._runs[run_id].active

    def current(self, run_id: int) -> dict:
        return dict(self._runs[run_id].current) if run_id in self._runs else {}

    def publish(self, run_id: int, type_: str, data: dict | None = None) -> Event:
        s = self._runs[run_id]
        data = data or {}
        if type_ in ("model_started", "request_started"):
            s.current.update({k: v for k, v in data.items() if k in ("model", "case_id", "case_title", "repeat")})
        ev = Event(s.next_id, type_, data)
        s.next_id += 1
        if type_ != "token":
            s.events.append(ev)
            if len(s.events) > BUFFER_LIMIT:
                del s.events[: len(s.events) - BUFFER_LIMIT]
        if type_ in TERMINAL:
            s.active = False
        for q in list(s.subscribers):
            q.put_nowait(ev)
        return ev

    async def subscribe(self, run_id: int, after: int = 0) -> AsyncIterator[Event]:
        """Yield buffered events after `after`, then live ones, until a terminal event or inactivity."""
        s = self._runs[run_id]
        q: asyncio.Queue = asyncio.Queue()
        backlog = [e for e in s.events if e.id > after]
        s.subscribers.append(q)
        try:
            for e in backlog:
                yield e
                if e.type in TERMINAL:
                    return
            if not s.active:
                return
            while True:
                e = await q.get()
                if e.id <= after:
                    continue
                yield e
                if e.type in TERMINAL:
                    return
        finally:
            s.subscribers.remove(q)
