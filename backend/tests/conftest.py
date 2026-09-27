import pytest

import app.models  # noqa: F401
from app.config import Settings
from app.db import Base, make_engine, make_session_factory


@pytest.fixture
def engine():
    eng = make_engine("sqlite://")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    return make_session_factory(engine)


@pytest.fixture
def session(session_factory):
    s = session_factory()
    yield s
    s.close()


@pytest.fixture
def settings():
    return Settings(
        ollama_base_url="http://fake-ollama:11434",
        request_timeout_s=5.0,
        max_retries=1,
        retry_backoff_s=0.0,
        provider_max_retries=1,
        provider_backoff_s=0.0,
    )


@pytest.fixture
def file_session_factory(tmp_path):
    """File-backed DB: API tests read while the run worker writes from another connection."""
    eng = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(eng)
    yield make_session_factory(eng)
    eng.dispose()
