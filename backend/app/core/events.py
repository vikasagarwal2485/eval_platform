"""Event hub feeding SSE endpoints, keyed by an opaque channel string (design D9).

Buffered events let a reconnecting client catch up; `token` events are live-only. The database is the source of
truth - a run client resyncs via GET /api/runs/{id}, an agent client via GET /api/agents/{id}/turns (design D4/D9).

Existing call sites pass a bare integer `run_id`; it is transparently namespaced as `run:{id}` so it can never
collide with an agent channel (`agent:{id}`), and their behaviour is unchanged. Agent code passes the string
channel directly.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

Channel = int | str

TERMINAL = {"run_finished", "rescore_finished"}
BUFFER_LIMIT = 2000


@dataclass
class Event:
    id: int
    type: str
    data: dict


@dataclass
class _Stream:
    events: list[Event] = field(default_factory=list)
    next_id: int = 1
    active: bool = False
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    current: dict = field(default_factory=dict)


def agent_channel(agent_id: int) -> str:
    return f"agent:{agent_id}"


class EventHub:
    def __init__(self) -> None:
        self._streams: dict[str, _Stream] = defaultdict(_Stream)

    @staticmethod
    def _key(channel: Channel) -> str:
        return f"run:{channel}" if isinstance(channel, int) else channel

    def begin(self, channel: Channel) -> None:
        """A new job for this channel starts: reset the buffer. Runs only - agent channels are continuous and
        never `begin()` (there is no job to reset between)."""
        s = self._streams[self._key(channel)]
        s.events.clear()
        s.current = {}
        s.active = True

    def is_active(self, channel: Channel) -> bool:
        k = self._key(channel)
        return k in self._streams and self._streams[k].active

    def current(self, channel: Channel) -> dict:
        k = self._key(channel)
        return dict(self._streams[k].current) if k in self._streams else {}

    def publish(self, channel: Channel, type_: str, data: dict | None = None) -> Event:
        s = self._streams[self._key(channel)]
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

    async def subscribe(self, channel: Channel, after: int = 0) -> AsyncIterator[Event]:
        """Yield buffered events after `after`, then live ones, until a terminal event or inactivity (runs)."""
        s = self._streams[self._key(channel)]
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

    async def subscribe_open(self, channel: Channel, after: int = 0) -> AsyncIterator[Event]:
        """Like `subscribe`, but for a channel with no terminal event (an agent's live feed): it never stops on
        its own, only when the caller stops iterating (the client disconnects)."""
        s = self._streams[self._key(channel)]
        q: asyncio.Queue = asyncio.Queue()
        backlog = [e for e in s.events if e.id > after]
        s.subscribers.append(q)
        try:
            for e in backlog:
                yield e
            while True:
                e = await q.get()
                if e.id <= after:
                    continue
                yield e
        finally:
            s.subscribers.remove(q)
