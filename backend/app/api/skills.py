"""Skills registry API (`add-run-skills`): named, Markdown-instruction bundles a run can attach to
every model it evaluates - text injected into the prompt, never executed."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import repo
from app.api.deps import get_session
from app.core import skill_io
from app.models import Skill
from app.schemas import SkillIn, SkillOut, SkillUpdate

router = APIRouter(prefix="/api")


def _skill_out(s: Skill) -> SkillOut:
    return SkillOut(
        id=s.id,
        name=s.name,
        description=s.description,
        instructions=s.instructions,
        created_at=s.created_at.isoformat(),
    )


@router.get("/skills", response_model=list[SkillOut])
def list_skills(session: Session = Depends(get_session)):
    return [_skill_out(s) for s in repo.list_skills(session)]


@router.post("/skills", response_model=SkillOut, status_code=201)
def create_skill(body: SkillIn, session: Session = Depends(get_session)):
    return _skill_out(repo.create_skill(session, body))


class ImportBody(BaseModel):
    content: str
    filename: str | None = None  # drives the .md extension check when the upload came from a file picker
    content_type: str | None = None


@router.post("/skills/import", response_model=SkillOut, status_code=201)
def import_skill(body: ImportBody, session: Session = Depends(get_session)):
    try:
        data = skill_io.parse_skill_file(body.content, body.filename, body.content_type)
    except skill_io.SkillFileError as exc:
        return JSONResponse(status_code=422, content={"detail": {"code": "invalid_skill_file", "errors": exc.errors}})
    return _skill_out(repo.create_skill(session, data))  # single transaction: all-or-nothing


@router.get("/skills/{skill_id}", response_model=SkillOut)
def get_skill(skill_id: int, session: Session = Depends(get_session)):
    return _skill_out(repo.get_skill(session, skill_id))


@router.patch("/skills/{skill_id}", response_model=SkillOut)
def update_skill(skill_id: int, body: SkillUpdate, session: Session = Depends(get_session)):
    skill = repo.update_skill(
        session, skill_id, name=body.name, description=body.description, instructions=body.instructions
    )
    return _skill_out(skill)


@router.delete("/skills/{skill_id}", status_code=204)
def delete_skill(skill_id: int, session: Session = Depends(get_session)):
    repo.delete_skill(session, skill_id)
    return Response(status_code=204)
