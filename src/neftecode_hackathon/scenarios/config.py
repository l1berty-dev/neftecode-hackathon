"""Validated internal policy, not a second set of public contract DTOs."""

from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from neftecode_hackathon.contracts import CheckCategory, NonEmptyText, SignalId

Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Positive = Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]


class PolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RangeProvenance(PolicyModel):
    kind: Literal["train", "expert"]
    source: NonEmptyText
    available_at: datetime
    train_end: datetime | None = None
    dataset_version: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_times(self) -> Self:
        for time in (self.available_at, self.train_end):
            if time is not None and (time.tzinfo is None or time.utcoffset() is None):
                raise ValueError("Policy provenance timestamps must include timezone")
        if self.kind == "train" and (self.train_end is None or self.dataset_version is None):
            raise ValueError(
                "Train ranges require train_end and dataset_version; full-dataset ranges are forbidden"
            )
        if self.train_end is not None and self.train_end > self.available_at:
            raise ValueError("train_end cannot follow policy availability")
        return self


class Control(PolicyModel):
    signal_id: SignalId
    name: NonEmptyText
    verification_status: Literal["confirmed", "unverified"]
    evidence: tuple[NonEmptyText, ...]
    canonical_unit: NonEmptyText | None
    unit_verified: StrictBool
    action_support_verified: StrictBool
    support_model_version: NonEmptyText | None = None
    available: StrictBool
    unavailable_reason: NonEmptyText | None
    model_min: Number | None
    model_max: Number | None
    step: Positive | None
    provenance: RangeProvenance | None
    range_kind: Literal["experimental"] = "experimental"
    max_change_per_minute: Positive | None = None
    ramp_evidence: NonEmptyText | None = None
    max_age_seconds: Positive = 1200

    @model_validator(mode="after")
    def validate_readiness(self) -> Self:
        if (self.model_min is None) != (self.model_max is None):
            raise ValueError("Both range bounds must be supplied together")
        if self.model_min is not None:
            if self.model_min >= self.model_max:
                raise ValueError("Control range must be increasing")
            if self.provenance is None:
                raise ValueError("Every numerical range requires provenance")
        if self.unit_verified and self.canonical_unit is None:
            raise ValueError("A verified unit cannot be unknown")
        if self.max_change_per_minute is not None and self.ramp_evidence is None:
            raise ValueError("Ramp limits require confirmation evidence")
        ready = (
            self.verification_status == "confirmed"
            and bool(self.evidence)
            and self.unit_verified
            and self.canonical_unit is not None
            and self.action_support_verified
            and self.support_model_version is not None
            and self.model_min is not None
            and self.step is not None
            and self.provenance is not None
        )
        if self.available and not ready:
            raise ValueError(
                "available=true requires verified control/unit/support and sourced range/step"
            )
        if not self.available and self.unavailable_reason is None:
            raise ValueError("Unavailable controls require an explanation")
        return self


class ControlCatalogue(PolicyModel):
    constraint_version: NonEmptyText
    controls: tuple[Control, ...]
    review_issues: tuple[str, ...] = ()

    @model_validator(mode="after")
    def unique_signals(self) -> Self:
        if len({c.signal_id for c in self.controls}) != len(self.controls):
            raise ValueError("Duplicate control signal IDs")
        if sum(c.available for c in self.controls) > 3:
            raise ValueError("v1 permits at most three available controls")
        return self


class RequiredInput(PolicyModel):
    signal_id: SignalId
    unit: NonEmptyText
    max_age_seconds: Positive


class SignalLimit(PolicyModel):
    code: NonEmptyText
    signal_id: SignalId
    unit: NonEmptyText
    minimum: Number | None = None
    maximum: Number | None = None
    max_age_seconds: Positive
    required: StrictBool = True
    category: Literal[CheckCategory.RELIABILITY, CheckCategory.CONTROL]
    evidence: NonEmptyText

    @model_validator(mode="after")
    def ordered_bounds(self) -> Self:
        if self.minimum is None and self.maximum is None:
            raise ValueError("A signal limit requires at least one bound")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("Limit bounds are reversed")
        return self


class ForbiddenCombination(PolicyModel):
    code: NonEmptyText
    signals: tuple[SignalId, ...] = Field(min_length=2)
    evidence: NonEmptyText

    @model_validator(mode="after")
    def unique_signals(self) -> Self:
        if len(set(self.signals)) != len(self.signals):
            raise ValueError("Duplicate signals in combination")
        return self


class Constraints(PolicyModel):
    constraint_version: NonEmptyText
    horizon_minutes: Literal[60] = 60
    target: Literal["ht.product_sulfur"] = "ht.product_sulfur"
    unit: Literal["mg/kg"] = "mg/kg"
    sulfur_upper_limit: Annotated[float, Field(strict=True, gt=0, le=10, allow_inf_nan=False)] = 10
    minimum_interval_coverage: (
        Annotated[float, Field(strict=True, gt=0, le=1, allow_inf_nan=False)] | None
    )
    quality_evidence: NonEmptyText
    model_inputs_verified: StrictBool
    model_version: NonEmptyText | None
    required_inputs: tuple[RequiredInput, ...]
    hard_check_inventory_verified: StrictBool
    hard_check_inventory_evidence: NonEmptyText | None
    signal_limits: tuple[SignalLimit, ...] = ()
    forbidden_combinations: tuple[ForbiddenCombination, ...] = ()
    transition_minutes: Positive | None = None
    transition_required: StrictBool = False
    transition_evidence: NonEmptyText | None = None
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.model_inputs_verified and (self.model_version is None or not self.required_inputs):
            raise ValueError("Verified model inputs require model_version and a non-empty manifest")
        if len({r.signal_id for r in self.required_inputs}) != len(self.required_inputs):
            raise ValueError("Duplicate required inputs")
        codes = [x.code for x in (*self.signal_limits, *self.forbidden_combinations)]
        if len(set(codes)) != len(codes) or any(not c.startswith("policy.") for c in codes):
            raise ValueError("Policy codes must be unique and start with policy.")
        if self.hard_check_inventory_verified and self.hard_check_inventory_evidence is None:
            raise ValueError("Verified hard-check inventory requires evidence, even when empty")
        if self.transition_required and self.transition_evidence is None:
            raise ValueError("Required transition assessment needs evidence")
        return self


class ScenarioPolicy(PolicyModel):
    catalogue: ControlCatalogue
    constraints: Constraints

    @model_validator(mode="after")
    def shared_version(self) -> Self:
        if self.catalogue.constraint_version != self.constraints.constraint_version:
            raise ValueError("Catalogue and constraints must have the same version")
        known = {c.signal_id for c in self.catalogue.controls}
        for control in self.catalogue.controls:
            if control.available and (
                not self.constraints.model_inputs_verified
                or control.support_model_version != self.constraints.model_version
            ):
                raise ValueError("Available controls require support for the active manifest model")
        for combination in self.constraints.forbidden_combinations:
            if not set(combination.signals) <= known:
                raise ValueError("Combination references unknown controls")
        return self


class UniqueKeyLoader(yaml.SafeLoader):
    """Reject ambiguous duplicate YAML keys rather than silently overriding safety policy."""


def _unique_mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"Duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def load_policy(
    controls_path: Path = Path("config/controls.yaml"),
    constraints_path: Path = Path("config/constraints.yaml"),
) -> ScenarioPolicy:
    """Read explicit files with safe YAML and validate without touching DB/model/data."""
    return ScenarioPolicy(
        catalogue=ControlCatalogue.model_validate(
            yaml.load(controls_path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
        ),
        constraints=Constraints.model_validate(
            yaml.load(constraints_path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
        ),
    )
