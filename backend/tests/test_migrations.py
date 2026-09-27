import pytest
from sqlalchemy import create_engine, inspect, text

import app.models  # noqa: F401
from app.db import Base
from app.migrate import upgrade_to_head


def test_alembic_upgrade_head_creates_all_tables(tmp_path):
    db = tmp_path / "fresh.db"
    url = f"sqlite:///{db}"
    upgrade_to_head(url)
    tables = set(inspect(create_engine(url)).get_table_names())
    assert set(Base.metadata.tables) <= tables
    assert "alembic_version" in tables


def test_migration_matches_models(tmp_path):
    """Autogenerate would find no drift between migrations and ORM models."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    url = f"sqlite:///{tmp_path / 'drift.db'}"
    upgrade_to_head(url)
    with create_engine(url).connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_0002_backfills_judge_mode_on_existing_rows(tmp_path):
    """Databases created at 0001 keep working: runs/attempts with a judge become `single`, others `none`."""
    from alembic import command
    from app.migrate import alembic_config

    url = f"sqlite:///{tmp_path / 'old.db'}"
    cfg = alembic_config(url)
    command.upgrade(cfg, "0001")
    eng = create_engine(url)
    with eng.begin() as conn:
        for rid, judge in ((1, "judge:1"), (2, None)):
            conn.execute(
                text(
                    "INSERT INTO run (id, name, status, config, judge_model, model_ids, footprints, created_at) "
                    "VALUES (:i, 'r', 'completed', '{}', :j, '[]', '{}', '2026-01-01')"
                ),
                {"i": rid, "j": judge},
            )
            conn.execute(
                text(
                    "INSERT INTO scoring_attempt (id, run_id, judge_model, created_at) VALUES (:i, :i, :j, '2026-01-01')"
                ),
                {"i": rid, "j": judge},
            )
    command.upgrade(cfg, "head")
    with eng.connect() as conn:
        runs = dict(conn.execute(text("SELECT id, judge_mode FROM run")).all())
        atts = dict(conn.execute(text("SELECT id, judge_mode FROM scoring_attempt")).all())
    assert runs == {1: "single", 2: "none"} and atts == {1: "single", 2: "none"}
    assert "judgement" in inspect(eng).get_table_names()


def test_0002_downgrade_restores_0001_shape(tmp_path):
    from alembic import command
    from app.migrate import alembic_config

    url = f"sqlite:///{tmp_path / 'down.db'}"
    cfg = alembic_config(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0001")
    insp = inspect(create_engine(url))
    assert "judgement" not in insp.get_table_names()
    assert "judge_mode" not in {c["name"] for c in insp.get_columns("run")}


def test_0003_keeps_existing_snapshots_as_local(tmp_path):
    """A database at 0002 with a real model snapshot upgrades in place; existing models read as local."""
    from alembic import command
    from app.migrate import alembic_config

    url = f"sqlite:///{tmp_path / 'at0002.db'}"
    cfg = alembic_config(url)
    command.upgrade(cfg, "0002")
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO model_snapshot (id, name, digest, capabilities) "
                "VALUES (1, 'qwen3:8b', 'abc123', '[\"completion\", \"thinking\"]')"
            )
        )
    command.upgrade(cfg, "head")
    with eng.connect() as conn:
        row = conn.execute(text("SELECT name, digest, source, provider_kind FROM model_snapshot")).one()
    assert tuple(row) == ("qwen3:8b", "abc123", "local", None)
    tables = set(inspect(eng).get_table_names())
    assert {"provider", "registered_model"} <= tables


def test_0003_downgrade_removes_provider_tables_and_columns(tmp_path):
    from alembic import command
    from app.migrate import alembic_config

    url = f"sqlite:///{tmp_path / 'down3.db'}"
    cfg = alembic_config(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0002")
    insp = inspect(create_engine(url))
    assert not ({"provider", "registered_model"} & set(insp.get_table_names()))
    cols = {c["name"] for c in insp.get_columns("model_snapshot")}
    assert "source" not in cols and "provider_kind" not in cols and "name" in cols


def test_0004_upgrades_a_populated_0003_database(tmp_path):
    """A database at 0003 with a real run and snapshot upgrades in place; existing runs stay readable."""
    from alembic import command
    from app.migrate import alembic_config

    url = f"sqlite:///{tmp_path / 'at0003.db'}"
    cfg = alembic_config(url)
    command.upgrade(cfg, "0003")
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO model_snapshot (id, name, digest, capabilities, provider_kind, source) "
                "VALUES (1, 'qwen3:8b', 'abc123', '[]', NULL, 'local')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO run (id, name, status, config, model_ids, footprints, judge_mode, created_at) "
                "VALUES (1, 'r', 'completed', '{}', '[1]', '{}', 'none', '2026-01-01')"
            )
        )
    command.upgrade(cfg, "head")
    tables = set(inspect(eng).get_table_names())
    assert {"agent", "agent_session", "agent_turn", "agent_span", "turn_evaluation", "turn_judgement"} <= tables
    with eng.connect() as conn:
        row = conn.execute(text("SELECT name FROM run WHERE id = 1")).one()
    assert row[0] == "r"  # existing run still reads fine


def test_0004_downgrade_removes_agent_tables(tmp_path):
    from alembic import command
    from app.migrate import alembic_config

    url = f"sqlite:///{tmp_path / 'down4.db'}"
    cfg = alembic_config(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0003")
    tables = set(inspect(create_engine(url)).get_table_names())
    assert not (
        {"agent", "agent_session", "agent_turn", "agent_span", "turn_evaluation", "turn_judgement"} & tables
    )


def test_agent_turn_and_session_are_unique_per_agent_and_cascade(tmp_path):
    from sqlalchemy.exc import IntegrityError

    from app.db import make_engine
    from app.migrate import upgrade_to_head

    url = f"sqlite:///{tmp_path / 'agent_uq.db'}"
    upgrade_to_head(url)
    eng = make_engine(url)
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agent (id, name, kind, declared_model, status, token_hash, token_prefix, "
                "eval_config, provider_acks, created_at) "
                "VALUES (1, 'bot', 'chatbot', 'qwen3:8b', 'active', 'h', 'p', '{}', '{}', '2026-01-01')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO agent_session (id, agent_id, external_id, started_at, last_event_at) "
                "VALUES (1, 1, 's1', '2026-01-01', '2026-01-01')"
            )
        )
    with pytest.raises(IntegrityError), eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agent_session (agent_id, external_id, started_at, last_event_at) "
                "VALUES (1, 's1', '2026-01-01', '2026-01-01')"
            )
        )
    with eng.begin() as conn:
        conn.execute(text("DELETE FROM agent WHERE id = 1"))  # cascades to sessions
        assert conn.execute(text("SELECT count(*) FROM agent_session")).scalar() == 0


def test_registered_model_is_unique_per_provider_and_cascades(tmp_path):
    from sqlalchemy.exc import IntegrityError

    from app.migrate import upgrade_to_head

    url = f"sqlite:///{tmp_path / 'uq.db'}"
    upgrade_to_head(url)
    from app.db import make_engine

    eng = make_engine(url)
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO provider (id, kind, name, key_env, created_at) VALUES (1, 'openai', 'p', 'K', '2026-01-01')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO registered_model (provider_id, model_id, display_name, enabled, reasoning) VALUES (1, 'gpt-4o', '', 1, 0)"
            )
        )
    with pytest.raises(IntegrityError), eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO registered_model (provider_id, model_id, display_name, enabled, reasoning) VALUES (1, 'gpt-4o', '', 1, 0)"
            )
        )
    with eng.begin() as conn:
        conn.execute(text("DELETE FROM provider WHERE id = 1"))  # FK cascade removes its models
        assert conn.execute(text("SELECT count(*) FROM registered_model")).scalar() == 0
