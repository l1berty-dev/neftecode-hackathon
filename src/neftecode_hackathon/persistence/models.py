"""Initial PostgreSQL schema, created exclusively through Alembic."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SnapshotRow(Base):
    __tablename__ = "snapshots"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    mode: Mapped[str] = mapped_column(String(16))
    dataset_version: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DecisionRow(Base):
    __tablename__ = "decisions"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("snapshots.id"), index=True)
    status: Mapped[str] = mapped_column(String(32))
    horizon_minutes: Mapped[int] = mapped_column(Integer)
    model_version: Mapped[str] = mapped_column(String(128))
    constraint_version: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict] = mapped_column(JSONB)
    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvaluationRow(Base):
    __tablename__ = "scenario_evaluations"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("snapshots.id"), index=True)
    decision_id: Mapped[UUID | None] = mapped_column(ForeignKey("decisions.id"), index=True)
    action: Mapped[dict] = mapped_column(JSONB)
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReplayRow(Base):
    __tablename__ = "replay_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="single_replay_session"),
        CheckConstraint("position >= 0", name="replay_position_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    episode_id: Mapped[str] = mapped_column(String(128))
    current_snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("snapshots.id"))
    position: Mapped[int] = mapped_column(Integer)
