"""HTTP-only request and response envelopes around the shared domain contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from neftecode_hackathon.contracts import (
    Decision,
    DecisionStatus,
    FiniteFloat,
    ProcessSnapshot,
    ScenarioEvaluation,
    SignalId,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorResponse(ApiModel):
    code: str
    message: str
    details: Any = None


class HealthResponse(ApiModel):
    ready: bool
    model_ready: bool
    data_ready: bool
    database_ready: bool
    issues: tuple[str, ...] = ()


class ControlResponse(ApiModel):
    signal_id: str
    label: str
    available: bool
    reason: str | None
    unit: str | None
    min: float | None
    max: float | None
    step: float | None
    source: str


class ControlsResponse(ApiModel):
    constraint_version: str
    controls: tuple[ControlResponse, ...]
    review_issues: tuple[str, ...]


class EpisodeResponse(ApiModel):
    episode_id: str
    name: str
    start: datetime
    end: datetime
    step_minutes: int
    synthetic: bool
    limitations: tuple[str, ...]


class EpisodesResponse(ApiModel):
    version: str
    episodes: tuple[EpisodeResponse, ...]


class SnapshotResponse(ApiModel):
    snapshot: ProcessSnapshot
    current_snapshot_id: UUID


class ReplayStartRequest(ApiModel):
    episode_id: Annotated[str, Field(min_length=1)] | None = None


class ReplayAdvanceRequest(ApiModel):
    expected_snapshot_id: UUID


class ActionInput(ApiModel):
    label: Annotated[str, Field(min_length=1)] = "Вариант оператора"
    changes: dict[SignalId, FiniteFloat] = Field(default_factory=dict)


class DecisionRequest(ApiModel):
    snapshot_id: UUID
    horizon_minutes: Literal[60] = 60
    operator_action: ActionInput | None = None


class ScenarioRequest(ApiModel):
    snapshot_id: UUID
    horizon_minutes: Literal[60] = 60
    changes: dict[SignalId, FiniteFloat]


class DecisionResponse(ApiModel):
    decision: Decision
    current_snapshot_id: UUID
    stale: bool


class ScenarioResponse(ApiModel):
    evaluation: ScenarioEvaluation
    current_snapshot_id: UUID
    stale: bool


class SaveDecisionResponse(ApiModel):
    decision_id: UUID
    saved: Literal[True] = True


class DecisionSummary(ApiModel):
    decision_id: UUID
    snapshot_id: UUID
    created_at: datetime
    status: DecisionStatus
    saved: bool


class DecisionListResponse(ApiModel):
    items: tuple[DecisionSummary, ...]


class StoredDecisionResponse(DecisionResponse):
    pass
