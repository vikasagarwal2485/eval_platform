"""Pydantic API schemas."""

from __future__ import annotations

from pydantic import BaseModel


class ModelInfo(BaseModel):
    name: str
    digest: str
    size_bytes: int | None = None
    parameter_size: str | None = None
    quantization: str | None = None
    family: str | None = None
    capabilities: list[str] = []
    thinking: bool = False


# ---------------------------------------------------------------- test cases / suites
from typing import Literal  # noqa: E402

from pydantic import BaseModel as _BM  # noqa: E402
from pydantic import ConfigDict, Field, field_validator, model_validator

from app.core.text import normalize, parse_number  # noqa: E402

Category = Literal["classification", "reasoning", "generation"]
CATEGORIES: tuple[str, ...] = ("classification", "reasoning", "generation")


class RubricCriterion(_BM):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""


class Constraints(_BM):
    max_words: int | None = Field(default=None, ge=1)
    min_words: int | None = Field(default=None, ge=1)
    required_keywords: list[str] = []
    forbidden_keywords: list[str] = []

    def is_empty(self) -> bool:
        return not (self.max_words or self.min_words or self.required_keywords or self.forbidden_keywords)


class CaseIn(_BM):
    """A test case as authored by a user (also the import/export file format)."""

    model_config = ConfigDict(extra="forbid")

    category: Category
    title: str = Field(default="", max_length=200)
    prompt: str
    system_prompt: str | None = None
    expected: str | None = None
    tags: list[str] = []
    # classification
    labels: list[str] = []
    # reasoning
    comparison: Literal["text", "numeric"] = "text"
    tolerance: float = Field(default=0.0, ge=0)
    # generation
    constraints: Constraints | None = None
    rubric: list[RubricCriterion] | None = None

    @field_validator("prompt")
    @classmethod
    def _prompt_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("prompt must not be empty")
        return v

    @field_validator("expected")
    @classmethod
    def _blank_expected_is_none(cls, v: str | None) -> str | None:
        return v if v is not None and v.strip() else None

    @model_validator(mode="after")
    def _category_rules(self) -> CaseIn:
        if self.category == "classification":
            labels = [x.strip() for x in self.labels if x.strip()]
            if len(labels) < 2:
                raise ValueError("classification cases need at least two allowed labels")
            if len({normalize(x) for x in labels}) != len(labels):
                raise ValueError("classification labels must be unique")
            self.labels = labels
            if self.expected is not None and normalize(self.expected) not in {normalize(x) for x in labels}:
                raise ValueError("expected label must be one of the allowed labels")
        elif self.category == "reasoning":
            if self.comparison == "numeric" and self.expected is not None and parse_number(self.expected) is None:
                raise ValueError("numeric comparison requires a numeric expected answer")
        return self

    # --- persistence mapping
    def to_config(self) -> dict:
        if self.category == "classification":
            return {"labels": self.labels}
        if self.category == "reasoning":
            return {"comparison": self.comparison, "tolerance": self.tolerance}
        cfg: dict = {}
        if self.constraints and not self.constraints.is_empty():
            cfg["constraints"] = self.constraints.model_dump()
        return cfg

    def to_rubric(self) -> list[dict] | None:
        if self.category != "generation" or not self.rubric:
            return None
        return [c.model_dump() for c in self.rubric]

    @classmethod
    def from_row(cls, row) -> CaseIn:
        cfg = row.config or {}
        return cls(
            category=row.category,
            title=row.title or "",
            prompt=row.prompt,
            system_prompt=row.system_prompt,
            expected=row.expected,
            tags=list(getattr(row, "tags", None) or []),
            labels=cfg.get("labels", []),
            comparison=cfg.get("comparison", "text"),
            tolerance=cfg.get("tolerance", 0.0),
            constraints=Constraints(**cfg["constraints"]) if cfg.get("constraints") else None,
            rubric=[RubricCriterion(**c) for c in row.rubric] if row.rubric else None,
        )

    def export_dict(self) -> dict:
        """Compact dict for export files (drops defaults/irrelevant fields)."""
        d = self.model_dump(exclude_none=True)
        d.pop("tags", None) if not self.tags else None
        if self.category != "classification":
            d.pop("labels", None)
        if self.category != "reasoning":
            d.pop("comparison", None)
            d.pop("tolerance", None)
        else:
            if self.comparison == "text":
                d.pop("comparison", None)
            if not self.tolerance:
                d.pop("tolerance", None)
        if not self.title:
            d.pop("title", None)
        return d


class CaseOut(CaseIn):
    id: int
    suite_id: int
    position: int


class SuiteIn(_BM):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    cases: list[CaseIn] = []


class SuiteUpdate(_BM):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class SuiteOut(_BM):
    id: int
    name: str
    description: str
    is_builtin: bool
    case_count: int
    counts_by_category: dict[str, int]


class SuiteDetail(SuiteOut):
    cases: list[CaseOut]


# ---------------------------------------------------------------- runs
class RunConfig(_BM):
    """Per-run settings. Defaults favour reproducibility (temperature 0, fixed seed)."""

    model_config = ConfigDict(extra="forbid")

    temperature: float = Field(default=0.0, ge=0, le=2)
    seed: int = 42
    max_output_tokens: int = Field(default=4096, ge=16, le=65536)
    num_ctx: int = Field(default=8192, ge=512, le=262144)
    repeats: int = Field(default=1, ge=1, le=20)
    think: bool = True  # only applied to thinking-capable models
    warmup: bool = True
    request_timeout_s: float | None = Field(default=None, gt=0, le=3600)
    judge_reasoning: bool = False  # also judge reasoning-trace quality (needs a judge model)


class RunCreate(_BM):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=200)
    models: list[str] = []
    suite_ids: list[int] = []
    exclude_case_ids: list[int] = []
    case_ids: list[int] = []
    adhoc_cases: list[CaseIn] = []
    config: RunConfig = RunConfig()
    judge_model: str | None = None
    # none | single | cross_model; omitted = inferred from judge_model (backward compatible)
    judge_mode: Literal["none", "single", "cross_model"] | None = None
