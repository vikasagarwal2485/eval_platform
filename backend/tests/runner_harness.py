"""Drive the run worker directly with a real router, a fake Ollama and fake provider HTTP servers."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from app import repo
from app.config import Settings
from app.core.events import EventHub
from app.core.model_discovery import ModelDiscovery
from app.core.runner import Job, Runner
from app.db import Base, make_engine, make_session_factory
from app.providers.backend import ModelRouter
from app.providers.factories import make_factories
from app.providers.refs import format_ref
from app.providers.secrets import KeyProvider
from app.repo import CaseSource
from app.schemas import CaseIn, ModelInfo
from tests.fake_providers import FakeAnthropic, FakeOpenAI
from tests.fakes import FakeOllama, make_tag

KEY = "test-key-123"


class Harness:
    """Providers `oa` (OpenAI) and `an` (Anthropic) point at fake servers; keys live in `self.env`."""

    def __init__(self, tmp_path, ollama: FakeOllama | None = None):
        engine = make_engine(f"sqlite:///{tmp_path / 'h.db'}")
        Base.metadata.create_all(engine)
        self.engine, self.sf = engine, make_session_factory(engine)
        self.ollama = ollama or FakeOllama([make_tag("qwen3:8b"), make_tag("gemma:test")])
        self.oa, self.an = FakeOpenAI(), FakeAnthropic()
        self.env = {"OA_KEY": KEY, "AN_KEY": KEY}
        self.settings = Settings(
            max_retries=1, retry_backoff_s=0.0, request_timeout_s=10.0, provider_max_retries=2, provider_backoff_s=0.0
        )
        self.hub = EventHub()
        self.router: ModelRouter | None = None
        self.runner: Runner | None = None
        self.models: dict[str, str] = {}  # ref -> provider kind

    async def start(self) -> Harness:
        oa_url, an_url = self.oa.start(), self.an.start()
        with self.sf() as s:
            for kind, name, env, url, ids in (
                ("openai", "oa", "OA_KEY", oa_url, ["gpt-4o", "o3"]),
                ("anthropic", "an", "AN_KEY", an_url, ["claude"]),
            ):
                p = repo.create_provider(s, kind=kind, name=name, key_env=env, base_url=url, ack_at=datetime.now(UTC))
                for mid in ids:
                    repo.add_registered_model(s, p.id, mid, reasoning=(mid == "o3"))
            s.commit()
        self.router = ModelRouter(self.ollama, self.sf, KeyProvider(self.env), factories=make_factories(self.settings))
        self.runner = Runner(self.sf, self.router, ModelDiscovery(self.ollama), self.hub, self.settings)
        await self.runner.start()
        return self

    async def stop(self) -> None:
        await self.runner.stop()
        await self.router.aclose()
        self.oa.stop()
        self.an.stop()
        self.engine.dispose()

    # ---- runs
    def info(self, ref: str) -> ModelInfo:
        if not ref.startswith("@"):
            return ModelInfo(name=ref, digest=f"digest-{ref}", capabilities=["completion"])
        provider, _, model = ref[1:].partition("/")
        with self.sf() as s:
            p, m = repo.find_registered(s, provider, model)
            kind, reasoning = p.kind, m.reasoning
        return ModelInfo(
            name=ref,
            digest="",
            source="cloud",
            provider=provider,
            provider_kind=kind,
            reasoning=reasoning,
            capabilities=["completion"] + (["thinking"] if reasoning else []),
            thinking=reasoning,
        )

    def add_run(self, refs: list[str], cases: list[CaseIn], *, judge_mode="none", judge_model=None, config=None) -> int:
        with self.sf() as s:
            snaps = [repo.get_or_create_snapshot(s, self.info(r)) for r in refs]
            run = repo.create_run(
                s,
                name="r",
                config=config or {"warmup": True},
                judge_model=judge_model,
                judge_mode=judge_mode,
                snapshots=snaps,
                cases=[CaseSource(c) for c in cases],
            )
            s.commit()
            return run.id

    async def run(self, run_id: int, timeout: float = 30.0):
        self.runner.submit(Job("eval", run_id))
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.sf() as s:
                run = repo.get_run(s, run_id)
                if run.status in ("completed", "failed", "cancelled") and not self.runner.is_busy(run_id):
                    s.expunge(run)
                    return run
            await asyncio.sleep(0.02)
        raise AssertionError(f"run {run_id} did not finish")

    def results(self, run_id: int):
        with self.sf() as s:
            names = {sn.id: sn.name for sn in repo.run_snapshots(s, repo.get_run(s, run_id))}
            rows = repo.list_results(s, run_id)
            for r in rows:
                s.expunge(r)
        return [(names[r.model_snapshot_id], r) for r in rows]

    def by_model(self, run_id: int):
        out: dict[str, list] = {}
        for name, r in self.results(run_id):
            out.setdefault(name, []).append(r)
        return out


def ref(provider: str, model: str) -> str:
    return format_ref(provider, model)


CLS = CaseIn(
    category="classification", title="c", prompt="I love it", labels=["positive", "negative"], expected="positive"
)
GEN = CaseIn(
    category="generation", title="g", prompt="Write a haiku", rubric=[{"name": "Relevance"}, {"name": "Fluency"}]
)
