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
