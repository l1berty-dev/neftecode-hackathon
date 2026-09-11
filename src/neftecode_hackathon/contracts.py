"""Shared, versioned contracts for the decision-support application.

The models in this module are the integration boundary between data preparation,
quality/reliability assessment, orchestration, persistence, and HTTP transport.
They intentionally reject ambiguous numbers and timestamps at that boundary.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTRACT_VERSION = 1

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
NonNegativeFiniteFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Completeness = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
SignalId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]*:[^\s]+$")]
NonEmptyText = Annotated[str, Field(min_length=1)]


class ContractModel(BaseModel):
    """Strict and immutable base for every public contract object."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")


class MeasurementQuality(StrEnum):
    VALID = "valid"
    SUSPECT = "suspect"
    MISSING = "missing"


class SnapshotMode(StrEnum):
    REPLAY = "replay"
    MANUAL = "manual"


class ActionOrigin(StrEnum):
    BASELINE = "baseline"
    SYSTEM = "system"
    OPERATOR = "operator"


class CheckCategory(StrEnum):
    DATA = "data"
    QUALITY = "quality"
    RELIABILITY = "reliability"
    CONTROL = "control"
    APPLICABILITY = "applicability"


class EstimateBasis(StrEnum):
    MEASURED = "measured"
    PREDICTED = "predicted"
    PROXY = "proxy"
    UNAVAILABLE = "unavailable"


class Applicability(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    INSUFFICIENT_DATA = "insufficient_data"


class Admissibility(StrEnum):
    ADMISSIBLE = "admissible"
    REJECTED = "rejected"
    NOT_ASSESSABLE = "not_assessable"


class DecisionStatus(StrEnum):
    CHANGE_RECOMMENDED = "change_recommended"
    NO_CHANGE = "no_change"
    INSUFFICIENT_DATA = "insufficient_data"
    NO_FEASIBLE_OPTION = "no_feasible_option"


class Measurement(ContractModel):
    """One value together with its event time, availability, and quality."""

    value: FiniteFloat | None
    unit: NonEmptyText | None
    source: NonEmptyText
    measured_at: datetime
    available_at: datetime
    age_seconds: NonNegativeFiniteFloat
    quality: MeasurementQuality
    issues: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_measurement(self) -> Self:
        _require_aware(self.measured_at, "measured_at")
        _require_aware(self.available_at, "available_at")
        if self.available_at < self.measured_at:
            raise ValueError("available_at cannot be earlier than measured_at")
        if (self.value is None) != (self.quality is MeasurementQuality.MISSING):
            raise ValueError("value must be null exactly when quality is missing")
        return self


class HistoryRecord(ContractModel):
    """A historical observation included in a snapshot history window."""

    signal_id: SignalId
    measured_at: datetime
    value: FiniteFloat

    @model_validator(mode="after")
    def validate_timestamp(self) -> Self:
        _require_aware(self.measured_at, "measured_at")
        return self


class ProcessSnapshot(ContractModel):
    contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION
    snapshot_id: UUID
    as_of: datetime
    mode: SnapshotMode
    dataset_version: NonEmptyText
    values: dict[SignalId, Measurement]
    history: tuple[HistoryRecord, ...]
    issues: tuple[str, ...] = ()
    completeness: Completeness

    @model_validator(mode="after")
    def reject_future_information(self) -> Self:
        _require_aware(self.as_of, "as_of")
        for signal_id, measurement in self.values.items():
            if measurement.measured_at > self.as_of or measurement.available_at > self.as_of:
                raise ValueError(f"values[{signal_id!r}] contains information from the future")
        for item in self.history:
            if item.measured_at > self.as_of:
                raise ValueError(
                    f"history[{item.signal_id!r}] contains information from the future"
                )
        return self


class Action(ContractModel):
    """Alternative next action; changes are absolute current setpoints."""

    action_id: UUID
    label: NonEmptyText
    origin: ActionOrigin
    changes: dict[SignalId, FiniteFloat] = Field(default_factory=dict)


class CheckResult(ContractModel):
    code: NonEmptyText
    passed: bool | None
    category: CheckCategory
    message: NonEmptyText
    actual: FiniteFloat | None = None
    limit: FiniteFloat | None = None
    unit: NonEmptyText | None = None


class MetricEstimate(ContractModel):
    value: FiniteFloat | None
    unit: NonEmptyText | None
    basis: EstimateBasis
    explanation: NonEmptyText
    lower: FiniteFloat | None = None
    upper: FiniteFloat | None = None

    @model_validator(mode="after")
    def validate_estimate(self) -> Self:
        if self.basis is EstimateBasis.UNAVAILABLE and self.value is not None:
            raise ValueError("an unavailable estimate cannot have a value")
        if self.basis is not EstimateBasis.UNAVAILABLE and self.value is None:
            raise ValueError("an available estimate must have a value")
        if (self.lower is None) != (self.upper is None):
            raise ValueError("lower and upper must either both be present or both be null")
        if self.lower is not None and self.upper is not None:
            if self.lower > self.upper:
                raise ValueError("lower cannot exceed upper")
            if self.value is not None and not self.lower <= self.value <= self.upper:
                raise ValueError("value must lie inside the interval")
        return self


class QualityAssessment(ContractModel):
    target: NonEmptyText
    forecast_at: datetime
    prediction: FiniteFloat | None
    unit: NonEmptyText
    lower: FiniteFloat | None
    upper: FiniteFloat | None
    interval_coverage_target: Completeness | None
    applicability: Applicability
    reasons: tuple[str, ...]
    model_version: NonEmptyText

    @model_validator(mode="after")
    def validate_assessment(self) -> Self:
        _require_aware(self.forecast_at, "forecast_at")
        values = (self.prediction, self.lower, self.upper)
        if self.applicability is Applicability.SUPPORTED and any(v is None for v in values):
            raise ValueError("a supported quality assessment requires prediction and interval")
        if self.applicability is not Applicability.SUPPORTED and any(v is not None for v in values):
            raise ValueError("an unsupported quality assessment cannot expose forecast numbers")
        if self.lower is not None and self.upper is not None and self.prediction is not None:
            if not self.lower <= self.prediction <= self.upper:
                raise ValueError("prediction must lie inside the interval")
        return self


class ReliabilityFactor(ContractModel):
    name: NonEmptyText
    contribution: FiniteFloat
    explanation: NonEmptyText


class ReliabilityAssessment(ContractModel):
    severity_index: FiniteFloat | None
    factors: tuple[ReliabilityFactor, ...]
    transition_assessed: bool
    limitations: tuple[str, ...]


class ScenarioEvaluation(ContractModel):
    evaluation_id: UUID
    snapshot_id: UUID
    horizon_minutes: Annotated[int, Field(gt=0)]
    action: Action
    quality: QualityAssessment
    reliability: ReliabilityAssessment
    throughput: MetricEstimate
    cost: MetricEstimate
    checks: tuple[CheckResult, ...]
    admissibility: Admissibility
    reasons: tuple[str, ...]
    model_version: NonEmptyText
    constraint_version: NonEmptyText


class TraceEntry(ContractModel):
    role: NonEmptyText
    input_ids: tuple[UUID, ...]
    output_summary: NonEmptyText
    check_codes: tuple[str, ...] = ()


class Decision(ContractModel):
    decision_id: UUID
    snapshot_id: UUID
    horizon_minutes: Annotated[int, Field(gt=0)]
    status: DecisionStatus
    baseline: ScenarioEvaluation
    preferred: ScenarioEvaluation | None
    alternatives: tuple[ScenarioEvaluation, ...] = Field(max_length=2)
    rejected_evaluations: tuple[ScenarioEvaluation, ...]
    explanation: tuple[str, ...]
    trace: tuple[TraceEntry, ...]
    dataset_version: NonEmptyText
    model_version: NonEmptyText
    constraint_version: NonEmptyText

    @model_validator(mode="after")
    def validate_shared_cycle(self) -> Self:
        evaluations = (
            self.baseline,
            *((self.preferred,) if self.preferred is not None else ()),
            *self.alternatives,
            *self.rejected_evaluations,
        )
        for evaluation in evaluations:
            if evaluation.snapshot_id != self.snapshot_id:
                raise ValueError("every evaluation must use the decision snapshot_id")
            if evaluation.horizon_minutes != self.horizon_minutes:
                raise ValueError("every evaluation must use the decision horizon_minutes")
            if evaluation.model_version != self.model_version:
                raise ValueError("every evaluation must use the decision model_version")
            if evaluation.constraint_version != self.constraint_version:
                raise ValueError("every evaluation must use the decision constraint_version")
        return self


class ContractExample(ContractModel):
    """Versioned wrapper used only to exchange the common synthetic fixture."""

    contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION
    synthetic: Literal[True]
    disclaimer: NonEmptyText
    snapshot: ProcessSnapshot
    action: Action
    evaluation: ScenarioEvaluation
    decision: Decision
