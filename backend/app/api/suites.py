from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import repo
from app.api.deps import get_session
from app.core import suite_io
from app.models import Suite, TestCase
from app.schemas import CaseIn, CaseOut, SuiteDetail, SuiteIn, SuiteOut, SuiteUpdate

router = APIRouter(prefix="/api")

READ_ONLY_MSG = "The built-in suite is read-only; duplicate it to customise."


def _case_out(row: TestCase) -> CaseOut:
    base = CaseIn.from_row(row)
    return CaseOut(**base.model_dump(), id=row.id, suite_id=row.suite_id, position=row.position)


def _suite_out(s: Suite) -> SuiteOut:
    return SuiteOut(
        id=s.id,
        name=s.name,
        description=s.description,
        is_builtin=s.is_builtin,
        case_count=len(s.cases),
        counts_by_category=repo.suite_counts(s),
    )


def _suite_detail(s: Suite) -> SuiteDetail:
    return SuiteDetail(**_suite_out(s).model_dump(), cases=[_case_out(c) for c in s.cases])


def _writable(suite: Suite) -> Suite:
    if suite.is_builtin:
        raise repo.Conflict(READ_ONLY_MSG)
    return suite


@router.get("/suites", response_model=list[SuiteOut])
def list_suites(session: Session = Depends(get_session)):
    return [_suite_out(s) for s in repo.list_suites(session)]


@router.post("/suites", response_model=SuiteDetail, status_code=201)
def create_suite(body: SuiteIn, session: Session = Depends(get_session)):
    return _suite_detail(repo.create_suite(session, body))


class ImportBody(BaseModel):
    content: str
    name: str | None = None  # optional rename to avoid a name conflict


@router.post("/suites/import", response_model=SuiteDetail, status_code=201)
def import_suite(body: ImportBody, session: Session = Depends(get_session)):
    try:
        data = suite_io.parse_suite_file(body.content, body.name)
    except suite_io.SuiteFileError as exc:
        return JSONResponse(status_code=422, content={"detail": {"code": "invalid_suite_file", "errors": exc.errors}})
    return _suite_detail(repo.create_suite(session, data))  # single transaction: all-or-nothing


class AdhocSave(BaseModel):
    case: CaseIn
    suite_id: int | None = None
    new_suite_name: str | None = None


@router.post("/suites/save-adhoc", response_model=CaseOut, status_code=201)
def save_adhoc(body: AdhocSave, session: Session = Depends(get_session)):
    """Save an ad-hoc prompt as a test case in an existing or newly created suite."""
    if body.suite_id is None and not body.new_suite_name:
        raise HTTPException(422, "Provide suite_id or new_suite_name")
    if body.suite_id is not None:
        suite = _writable(repo.get_suite(session, body.suite_id))
        row = repo.add_case(session, suite.id, body.case)
    else:
        suite = repo.create_suite(session, SuiteIn(name=body.new_suite_name, cases=[body.case]))
        row = suite.cases[0]
    return _case_out(row)


@router.get("/suites/{suite_id}", response_model=SuiteDetail)
def get_suite(suite_id: int, session: Session = Depends(get_session)):
    return _suite_detail(repo.get_suite(session, suite_id))


@router.patch("/suites/{suite_id}", response_model=SuiteDetail)
def update_suite(suite_id: int, body: SuiteUpdate, session: Session = Depends(get_session)):
    _writable(repo.get_suite(session, suite_id))
    return _suite_detail(repo.update_suite(session, suite_id, name=body.name, description=body.description))


@router.delete("/suites/{suite_id}", status_code=204)
def delete_suite(suite_id: int, session: Session = Depends(get_session)):
    _writable(repo.get_suite(session, suite_id))
    repo.delete_suite(session, suite_id)
    return Response(status_code=204)


@router.post("/suites/{suite_id}/duplicate", response_model=SuiteDetail, status_code=201)
def duplicate_suite(suite_id: int, session: Session = Depends(get_session)):
    return _suite_detail(repo.duplicate_suite(session, suite_id))


@router.get("/suites/{suite_id}/export")
def export_suite(suite_id: int, format: str = "json", session: Session = Depends(get_session)):
    if format not in ("json", "yaml"):
        raise HTTPException(422, "format must be json or yaml")
    suite = repo.get_suite(session, suite_id)
    media = "application/json" if format == "json" else "application/x-yaml"
    filename = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in suite.name) + f".{format}"
    return Response(
        suite_io.dump_suite(suite, format),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/suites/{suite_id}/cases", response_model=CaseOut, status_code=201)
def add_case(suite_id: int, body: CaseIn, session: Session = Depends(get_session)):
    _writable(repo.get_suite(session, suite_id))
    return _case_out(repo.add_case(session, suite_id, body))


@router.put("/cases/{case_id}", response_model=CaseOut)
def update_case(case_id: int, body: CaseIn, session: Session = Depends(get_session)):
    _writable(repo.get_case(session, case_id).suite)
    return _case_out(repo.update_case(session, case_id, body))


@router.delete("/cases/{case_id}", status_code=204)
def delete_case(case_id: int, session: Session = Depends(get_session)):
    _writable(repo.get_case(session, case_id).suite)
    repo.delete_case(session, case_id)
    return Response(status_code=204)
