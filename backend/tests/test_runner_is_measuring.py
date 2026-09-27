import asyncio

from app.core.events import EventHub
from app.core.model_discovery import ModelDiscovery
from app.core.runner import Job, Runner
from tests.fakes import FakeOllama
from tests.helpers import CLS, make_responder


def test_is_measuring_true_while_a_job_runs_and_false_once_idle(session_factory, settings):
    fake = FakeOllama([{"name": "a:1", "digest": "d", "details": {}}], make_responder(), chunk_delay_s=0.05)
    runner = Runner(session_factory, fake, ModelDiscovery(fake), EventHub(), settings)

    async def go():
        assert runner.is_measuring() is False
        await runner.start()
        from app import repo
        from app.schemas import CaseIn

        with session_factory() as session:
            snap = repo.get_or_create_snapshot(
                session, __import__("app.schemas", fromlist=["ModelInfo"]).ModelInfo(name="a:1", digest="d")
            )
            run = repo.create_run(
                session,
                name="r",
                config={},
                judge_model=None,
                snapshots=[snap],
                cases=[repo.CaseSource(CaseIn(**CLS), None)],
            )
            session.commit()
            run_id = run.id
        runner.submit(Job("eval", run_id))
        await asyncio.sleep(0.05)
        assert runner.is_measuring() is True
        for _ in range(200):
            if not runner.is_measuring():
                break
            await asyncio.sleep(0.02)
        assert runner.is_measuring() is False
        await runner.stop()

    asyncio.run(go())
