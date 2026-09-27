"""SQLAlchemy models (see design.md D8)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class ModelSnapshot(Base):
    """Immutable record of a model artifact as seen at run time."""

    __tablename__ = "model_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    digest: Mapped[str] = mapped_column(String(100), default="")
    parameter_size: Mapped[str | None] = mapped_column(String(50), nullable=True)
    quantization: Mapped[str | None] = mapped_column(String(50), nullable=True)
    family: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    # None = Ollama; otherwise the provider kind (openai | anthropic). `name` is then the @provider/model reference.
    provider_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source: Mapped[str] = mapped_column(String(10), default="local", server_default="local")  # local | cloud


class Provider(Base):
    """A registered enterprise provider. Holds the *name* of the env var with the key, never the key (design D4)."""

    __tablename__ = "provider"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # openai | anthropic
    name: Mapped[str] = mapped_column(String(40), unique=True)
    key_env: Mapped[str] = mapped_column(String(64))
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ack_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # data-sharing acknowledgment
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    models: Mapped[list[RegisteredModel]] = relationship(
        back_populates="provider", cascade="all, delete-orphan", order_by="RegisteredModel.id"
    )


class RegisteredModel(Base):
    __tablename__ = "registered_model"
    __table_args__ = (UniqueConstraint("provider_id", "model_id", name="uq_registered_model_provider_model"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("provider.id", ondelete="CASCADE"), index=True)
    model_id: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(200), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    reasoning: Mapped[bool] = mapped_column(Boolean, default=False)

    provider: Mapped[Provider] = relationship(back_populates="models")


class Suite(Base):
    __tablename__ = "suite"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    cases: Mapped[list[TestCase]] = relationship(
        back_populates="suite", cascade="all, delete-orphan", order_by="TestCase.position"
    )


class TestCase(Base):
    __tablename__ = "test_case"
    __test__ = False  # not a pytest class

    id: Mapped[int] = mapped_column(primary_key=True)
    suite_id: Mapped[int] = mapped_column(ForeignKey("suite.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    category: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200), default="")
    prompt: Mapped[str] = mapped_column(Text)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected: Mapped[str | None] = mapped_column(Text, nullable=True)
    # category-specific settings: labels / comparison / tolerance / constraints
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    rubric: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)

    suite: Mapped[Suite] = relationship(back_populates="cases")


class Run(Base):
    __tablename__ = "run"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    # queued | running | completed | cancelled | failed
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    judge_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # none | single | cross_model (cross_model: each model is judged only by the other evaluated models)
    judge_mode: Mapped[str] = mapped_column(String(20), default="none", server_default="none")
    model_ids: Mapped[list] = mapped_column(JSON, default=list)  # ordered ModelSnapshot ids
    footprints: Mapped[dict] = mapped_column(JSON, default=dict)  # snapshot id -> {size, size_vram}
    ollama_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_run_id: Mapped[int | None] = mapped_column(ForeignKey("run.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    cases: Mapped[list[RunCase]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunCase.position"
    )


class RunCase(Base):
    """Frozen copy of a test case taken when the run was created."""

    __tablename__ = "run_case"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"), index=True)
    source_case_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    category: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200), default="")
    prompt: Mapped[str] = mapped_column(Text)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    rubric: Mapped[list | None] = mapped_column(JSON, nullable=True)

    run: Mapped[Run] = relationship(back_populates="cases")


class Result(Base):
    __tablename__ = "result"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"), index=True)
    model_snapshot_id: Mapped[int] = mapped_column(ForeignKey("model_snapshot.id"), index=True)
    run_case_id: Mapped[int] = mapped_column(ForeignKey("run_case.id", ondelete="CASCADE"))
    repeat_idx: Mapped[int] = mapped_column(Integer, default=0)
    # ok | error | cancelled
    status: Mapped[str] = mapped_column(String(20), default="ok")
    sent_prompt: Mapped[str] = mapped_column(Text, default="")
    template_version: Mapped[str] = mapped_column(String(20), default="")
    output: Mapped[str] = mapped_column(Text, default="")
    thinking: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_cold: Mapped[bool] = mapped_column(Boolean, default=False)
    # typed columns used for sorting/aggregation
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    ttft_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    tokens_per_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # full raw Ollama counters and client timings
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScoringAttempt(Base):
    __tablename__ = "scoring_attempt"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"), index=True)
    judge_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    judge_mode: Mapped[str] = mapped_column(String(20), default="none", server_default="none")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Score(Base):
    __tablename__ = "score"

    id: Mapped[int] = mapped_column(primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("result.id", ondelete="CASCADE"), index=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("scoring_attempt.id", ondelete="CASCADE"), index=True)
    # auto | judge | constraints
    kind: Mapped[str] = mapped_column(String(20))
    value: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0..1, None = unscored
    # correct | wrong | unparseable | error | unscored | pass | fail | judged
    outcome: Mapped[str] = mapped_column(String(20))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class Judgement(Base):
    """One judge's verdict on one answer. The per-answer `Score(kind=judge*)` row is the aggregate of these."""

    __tablename__ = "judgement"

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("scoring_attempt.id", ondelete="CASCADE"), index=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("result.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # judge | judge_reasoning
    judge_model: Mapped[str] = mapped_column(String(200))
    value: Mapped[float | None] = mapped_column(Float, nullable=True)  # normalized 0..1, None on error
    outcome: Mapped[str] = mapped_column(String(20))  # judged | error
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
