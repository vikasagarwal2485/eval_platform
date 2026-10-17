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
    # --- enterprise providers (name is then the @provider/model reference)
    source: str = "local"  # local | cloud
    provider: str | None = None  # registered provider name
    provider_kind: str | None = None  # openai | anthropic
    display_name: str | None = None
    reasoning: bool = False
    available: bool = True
    unavailable_reason: str | None = None


# ---------------------------------------------------------------- test cases / suites
from typing import Any, Literal  # noqa: E402

from pydantic import BaseModel as _BM  # noqa: E402
from pydantic import ConfigDict, Field, field_validator, model_validator

from app.core.text import normalize, parse_number  # noqa: E402
from app.providers.refs import parse_ref  # noqa: E402

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


# ---------------------------------------------------------------- live agent evaluation
AgentKind = Literal["chatbot", "reasoning"]


class RubricCriterionIn(_BM):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str = ""


class EvalConfigIn(_BM):
    """Per-agent evaluation settings (design D4). Every field has a default so an agent needs none of them set."""

    model_config = ConfigDict(extra="forbid")

    evaluators: list[str] = []
    sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    quiet_period_s: float = Field(default=20.0, ge=0.0, le=3600.0)
    context_turns: int = Field(default=4, ge=0, le=50)
    attention_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    abandon_after_s: float = Field(default=600.0, gt=0.0, le=86_400.0)
    retention_days: int | None = Field(default=None, ge=1, le=3650)


class DeclaredModelSpec(_BM):
    """A declared model given as an object instead of a plain string, to carry generation-parameter
    overrides alongside the model reference (`add-gateway-model-sync`) - e.g.
    `{"model": "@anthropic-main/claude-sonnet-5", "params": {"temperature": 0.2}}`. `params` is passed through
    opaquely to the gateway sync step; this schema does not know or validate any individual provider's valid
    parameter set.

    `fallback` (`add-declared-model-fallback`) is an optional second model reference, synced to its own gateway
    model group, for the platform to fall back to when the primary is unreachable - validated the same way as
    `model`, but it does not get its own nested `params`/`fallback` (see design.md's "Decisions": a fallback's
    own generation params, if ever needed, reuse the primary's `params` rather than needing a separate field)."""

    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=300)
    params: dict[str, Any] | None = None
    fallback: str | None = Field(default=None, min_length=1, max_length=300)


def declared_model_ref(entry: str | DeclaredModelSpec | dict) -> str:
    """The model reference out of one `declared_models` entry, whichever of the two accepted shapes it is -
    shared by every reader (the self-evaluator check, the gateway sync step, ...) so neither has to know about
    the other's shape assumptions."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, DeclaredModelSpec):
        return entry.model
    return entry["model"]


def declared_model_fallback_ref(entry: str | DeclaredModelSpec | dict) -> str | None:
    """The fallback model reference out of one `declared_models` entry, if it has one - `None` for a plain-string
    entry (no fallback possible) or an object entry with no `fallback` set. Mirrors `declared_model_ref` so every
    reader (validation, provider-ack checks, gateway sync) extracts it the same way."""
    if isinstance(entry, str):
        return None
    if isinstance(entry, DeclaredModelSpec):
        return entry.fallback
    return entry.get("fallback")


def _validate_declared_models(
    v: dict[str, str | DeclaredModelSpec],
) -> dict[str, str | dict[str, Any]]:
    """Shared by AgentCreate/AgentSettingsUpdate (spec `agent-registry`, "Register an agent" / "At least one
    declared model is required"): each value must be a real model reference, and the map must not be empty - an
    agent with no declared model can't be checked against its evaluator list. A plain-string entry is stored
    exactly as given (unchanged from before this schema accepted the object form); an object entry is stored as
    a plain dict (`{"model": ..., "params": {...}}`), never a pydantic model instance, so every downstream
    reader (ORM assignment, JSON serialization) sees only `str | dict`."""
    if not v:
        raise ValueError("at least one declared model is required")
    out: dict[str, str | dict[str, Any]] = {}
    for key, entry in v.items():
        try:
            parse_ref(declared_model_ref(entry))
        except ValueError as exc:
            raise ValueError(f"declared_models['{key}']: {exc}") from None
        fallback_ref = declared_model_fallback_ref(entry)
        if fallback_ref is not None:
            try:
                parse_ref(fallback_ref)
            except ValueError as exc:
                raise ValueError(f"declared_models['{key}'].fallback: {exc}") from None
        out[key] = entry if isinstance(entry, str) else entry.model_dump(exclude_none=True)
    return out


class AgentCreate(_BM):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    kind: AgentKind
    # One or more models the agent declares it uses, keyed by the task each serves (e.g. "reasoning",
    # "generation"); an agent with one undifferentiated task uses the conventional key "default". A value is
    # either a plain model-reference string, or a DeclaredModelSpec object carrying generation-parameter
    # overrides alongside the reference.
    declared_models: dict[str, str | DeclaredModelSpec]
    eval_config: EvalConfigIn = EvalConfigIn()
    rubric: list[RubricCriterionIn] | None = None
    provider_acks: list[str] = []  # provider names being acknowledged in this same request

    @field_validator("declared_models")
    @classmethod
    def _check_declared_models(cls, v: dict[str, str | DeclaredModelSpec]) -> dict[str, str | dict[str, Any]]:
        return _validate_declared_models(v)


class AgentSettingsUpdate(_BM):
    model_config = ConfigDict(extra="forbid")

    declared_models: dict[str, str | DeclaredModelSpec] | None = None
    eval_config: EvalConfigIn | None = None
    rubric: list[RubricCriterionIn] | None = None
    clear_rubric: bool = False
    provider_acks: list[str] = []

    @field_validator("declared_models")
    @classmethod
    def _check_declared_models(
        cls, v: dict[str, str | DeclaredModelSpec] | None
    ) -> dict[str, str | dict[str, Any]] | None:
        return v if v is None else _validate_declared_models(v)


class EvaluateTurnRequest(_BM):
    model_config = ConfigDict(extra="forbid")

    evaluators: list[str] | None = None
    rubric: list[RubricCriterionIn] | None = None


class BulkReevaluateRequest(_BM):
    model_config = ConfigDict(extra="forbid")

    since: str | None = None
    until: str | None = None
    below_score: float | None = Field(default=None, ge=0.0, le=1.0)
    evaluators: list[str] | None = None
