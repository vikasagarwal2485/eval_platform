from sqlalchemy import inspect


def test_schema_creates_all_tables(engine):
    tables = set(inspect(engine).get_table_names())
    assert {
        "model_snapshot",
        "suite",
        "test_case",
        "run",
        "run_case",
        "result",
        "score",
        "scoring_attempt",
    } <= tables
