"""Suite import/export (JSON or YAML) and the built-in starter suite."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import repo
from app.models import Suite
from app.schemas import CaseIn, SuiteIn

STARTER_PATH = Path(__file__).resolve().parents[1] / "data" / "starter_suite.yaml"
STARTER_NAME = "Starter suite"


class SuiteFileError(ValueError):
    """The uploaded suite file is invalid; `errors` is a list of {field, message} dicts."""

    def __init__(self, errors: list[dict]):
        super().__init__("; ".join(f"{e['field']}: {e['message']}" for e in errors))
        self.errors = errors


def _field_path(loc: tuple) -> str:
    out = ""
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out or "(root)"


def parse_suite_file(content: str, name_override: str | None = None) -> SuiteIn:
    try:
        data = yaml.safe_load(content)  # YAML is a superset of JSON
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"line {mark.line + 1}, column {mark.column + 1}" if mark else "unknown position"
        raise SuiteFileError([{"field": "(syntax)", "message": f"invalid YAML/JSON at {where}"}]) from exc
    if not isinstance(data, dict):
        raise SuiteFileError([{"field": "(root)", "message": "expected an object with 'name' and 'cases'"}])
    if name_override:
        data["name"] = name_override
    try:
        return SuiteIn.model_validate(data)
    except ValidationError as exc:
        raise SuiteFileError(
            [{"field": _field_path(e["loc"]), "message": e["msg"].removeprefix("Value error, ")} for e in exc.errors()]
        ) from exc


def dump_suite(suite: Suite, fmt: str = "json") -> str:
    payload = {
        "name": suite.name,
        "description": suite.description,
        "cases": [CaseIn.from_row(c).export_dict() for c in suite.cases],
    }
    if fmt == "yaml":
        return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    return json.dumps(payload, indent=2, ensure_ascii=False)


def seed_starter_suite(session: Session) -> Suite | None:
    """Create the built-in suite if it is missing. Idempotent."""
    existing = session.scalar(select(Suite).where(Suite.is_builtin.is_(True)))
    if existing:
        return None
    data = parse_suite_file(STARTER_PATH.read_text())
    return repo.create_suite(session, data, is_builtin=True)
