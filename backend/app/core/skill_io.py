"""Skill import (`add-run-skills`): parses raw text (typed, pasted, or uploaded from a `.md` file)
into name/description/instructions. Deliberately not YAML/JSON like `suite_io.py` - a skill's
content is "plain Markdown the system never parses deeply" (design.md Decision 3)."""

from __future__ import annotations

from app.schemas import SkillIn

MAX_BYTES = 300_000  # "a few hundred KB" (design.md Decision 3)
ALLOWED_CONTENT_TYPES = ("text/markdown", "text/plain", "text/x-markdown")


class SkillFileError(ValueError):
    """The uploaded/pasted skill content is invalid; `errors` is a list of {field, message} dicts."""

    def __init__(self, errors: list[dict]):
        super().__init__("; ".join(f"{e['field']}: {e['message']}" for e in errors))
        self.errors = errors


def _split_blocks(content: str) -> list[str]:
    return [b.strip() for b in content.strip().split("\n\n") if b.strip()]


def parse_skill_file(
    content: str, filename: str | None = None, content_type: str | None = None
) -> SkillIn:
    """First block (minus a leading `# ` heading marker) -> name, next block -> description,
    every remaining block (rejoined with blank lines) -> instructions."""
    if len(content.encode("utf-8")) > MAX_BYTES:
        raise SkillFileError([{"field": "(file)", "message": f"exceeds the {MAX_BYTES // 1000}KB size limit"}])
    if filename is not None and not filename.lower().endswith(".md"):
        raise SkillFileError([{"field": "(file)", "message": "must be a .md (Markdown) file"}])
    if content_type is not None and content_type not in ALLOWED_CONTENT_TYPES:
        raise SkillFileError([{"field": "(file)", "message": f"unsupported content type '{content_type}'"}])

    blocks = _split_blocks(content)
    if not blocks:
        raise SkillFileError([{"field": "instructions", "message": "field required"}])

    name = blocks[0].removeprefix("# ").strip()
    description = blocks[1] if len(blocks) > 1 else ""
    instructions = "\n\n".join(blocks[2:]) if len(blocks) > 2 else ""

    try:
        return SkillIn(name=name, description=description, instructions=instructions)
    except Exception as exc:  # pydantic.ValidationError
        errors = exc.errors() if hasattr(exc, "errors") else [{"loc": ("instructions",), "msg": str(exc)}]
        raise SkillFileError(
            [{"field": ".".join(str(p) for p in e["loc"]) or "(root)", "message": e["msg"]} for e in errors]
        ) from exc
