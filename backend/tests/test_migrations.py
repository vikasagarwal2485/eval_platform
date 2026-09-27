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
