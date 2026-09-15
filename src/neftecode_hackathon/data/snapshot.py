"""Build immutable, point-in-time snapshots from prepared Parquet datasets."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

import pandas as pd
import pyarrow.parquet as pq
import yaml

from neftecode_hackathon.contracts import (
    HistoryRecord,
    Measurement,
    MeasurementQuality,
    ProcessSnapshot,
    SnapshotMode,
)

if TYPE_CHECKING:
    from neftecode_hackathon.scenarios.config import ScenarioPolicy


@dataclass(frozen=True)
class RequiredInputSpec:
    """Internal model-manifest requirement used to calculate snapshot completeness."""

    signal_id: str
    unit: str
    max_age_seconds: float


@dataclass(frozen=True)
class SourceConflictRule:
    """Train/validation-derived disagreement threshold for equivalent measurements."""

    left_signal_id: str
    right_signal_id: str
    maximum_absolute_difference: float
    unit: str
    evidence: str


class SnapshotProvider:
    """Read prepared history strictly as it was available at a replay timestamp."""

    def __init__(
        self,
        processed_directory: Path,
        *,
        history_minutes: int = 360,
        freshness_minutes: Mapping[str, int] | None = None,
        required_inputs: Iterable[RequiredInputSpec] = (),
        manifest_verified: bool = False,
        conflict_rules: Iterable[SourceConflictRule] = (),
    ) -> None:
        self.processed_directory = processed_directory.resolve()
        self.history_minutes = history_minutes
        if history_minutes <= 0:
            raise ValueError("history_minutes must be positive")
        self.freshness_minutes = dict(freshness_minutes or {})
        self.required_inputs = tuple(required_inputs)
        self.manifest_verified = manifest_verified
        self.conflict_rules = tuple(conflict_rules)
        self.dataset_version = self._read_dataset_version()

    @classmethod
    def from_repository(
        cls, root: Path | None = None, *, policy: ScenarioPolicy | None = None
    ) -> SnapshotProvider:
        """Construct from the repository config and developer-2's validated policy."""

        repository = (root or Path(__file__).resolve().parents[3]).resolve()
        model_config = yaml.safe_load(
            (repository / "config" / "model.yaml").read_text(encoding="utf-8")
        )
        if policy is None:
            from neftecode_hackathon.scenarios.config import load_policy

            policy = load_policy(
                repository / "config" / "controls.yaml",
                repository / "config" / "constraints.yaml",
            )
        constraints = policy.constraints
        required = tuple(
            RequiredInputSpec(item.signal_id, item.unit, item.max_age_seconds)
            for item in constraints.required_inputs
        )
        return cls(
            repository / "data" / "processed",
            history_minutes=model_config["forecast"]["history_minutes"],
            freshness_minutes=model_config["availability"]["freshness_minutes"],
            required_inputs=required,
            manifest_verified=constraints.model_inputs_verified,
        )

    def get_snapshot(
        self, at: datetime, *, mode: SnapshotMode = SnapshotMode.REPLAY
    ) -> ProcessSnapshot:
        """Return only records measured and available no later than ``at``."""

        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("snapshot timestamp must include a timezone offset")
        as_of = at.astimezone(UTC)
        history_start = as_of - timedelta(minutes=self.history_minutes)

        telemetry = self._read_parquet(
            "telemetry.parquet",
            filters=[
                ("measured_at", ">=", history_start),
                ("measured_at", "<=", as_of),
                ("available_at", "<=", as_of),
            ],
        )
        analyses_current = self._read_parquet(
            "analyses.parquet",
            filters=[("measured_at", "<=", as_of), ("available_at", "<=", as_of)],
        )
        analyses_history = analyses_current.loc[analyses_current["measured_at"] >= history_start]

        current_frames = []
        for frame in (telemetry, analyses_current):
            if not frame.empty:
                current_frames.append(
                    frame.sort_values(["signal_id", "measured_at", "available_at"], kind="stable")
                    .groupby("signal_id", sort=False)
                    .tail(1)
                )
        current = (
            pd.concat(current_frames, ignore_index=True)
            if current_frames
            else pd.DataFrame(columns=["signal_id"])
        )
        values = {
            str(row.signal_id): self._measurement_from_row(row, as_of)
            for row in current.itertuples(index=False)
        }
        issues: list[str] = []
        self._apply_conflict_rules(values, issues)
        completeness = self._calculate_completeness(values, issues)

        history_frame = pd.concat([telemetry, analyses_history], ignore_index=True)
        history = tuple(
            HistoryRecord(
                signal_id=str(row.signal_id),
                measured_at=self._utc(row.measured_at),
                value=float(row.value),
            )
            for row in history_frame.sort_values(
                ["measured_at", "signal_id"], kind="stable"
            ).itertuples(index=False)
        )
        fingerprint = json.dumps(
            {
                "dataset_version": self.dataset_version,
                "as_of": as_of.isoformat(),
                "mode": mode.value,
                "values": {
                    key: value.model_dump(mode="json") for key, value in sorted(values.items())
                },
                "history": [item.model_dump(mode="json") for item in history],
                "issues": issues,
                "completeness": completeness,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return ProcessSnapshot(
            snapshot_id=uuid5(NAMESPACE_URL, fingerprint),
            as_of=as_of,
            mode=mode,
            dataset_version=self.dataset_version,
            values=dict(sorted(values.items())),
            history=history,
            issues=tuple(issues),
            completeness=completeness,
        )

    def _read_dataset_version(self) -> str:
        audit_path = self.processed_directory / "audit_report.json"
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        version = audit.get("dataset_version")
        if not isinstance(version, str) or not version:
            raise ValueError("audit_report.json has no dataset_version")
        dictionary_path = self.processed_directory / "data_dictionary.json"
        dictionary = json.loads(dictionary_path.read_text(encoding="utf-8"))
        if dictionary.get("dataset_version") != version:
            raise ValueError("prepared data versions do not match")
        return version

    def _read_parquet(self, filename: str, *, filters: list[tuple]) -> pd.DataFrame:
        path = self.processed_directory / filename
        return pq.read_table(path, filters=filters).to_pandas()

    def _measurement_from_row(self, row, as_of: datetime) -> Measurement:
        measured_at = self._utc(row.measured_at)
        available_at = self._utc(row.available_at)
        row_issues = tuple(json.loads(row.issues))
        source = str(row.source)
        freshness_key = "online" if source == "telemetry" else source
        max_age_minutes = self.freshness_minutes.get(freshness_key)
        age_seconds = (as_of - measured_at).total_seconds()
        stale = max_age_minutes is not None and age_seconds > max_age_minutes * 60
        issues = (*row_issues, *(("stale",) if stale and "stale" not in row_issues else ()))
        quality = MeasurementQuality(str(row.quality))
        if stale and quality is MeasurementQuality.VALID:
            quality = MeasurementQuality.SUSPECT
        unit = None if pd.isna(row.unit) else str(row.unit)
        return Measurement(
            value=float(row.value),
            unit=unit,
            source=source,
            measured_at=measured_at,
            available_at=available_at,
            age_seconds=age_seconds,
            quality=quality,
            issues=issues,
        )

    def _calculate_completeness(
        self, values: Mapping[str, Measurement], issues: list[str]
    ) -> float:
        if not self.manifest_verified:
            issues.append("required_input_manifest_unverified")
            return 0.0
        if not self.required_inputs:
            raise ValueError("a verified manifest must define required inputs")
        ready = 0
        for required in self.required_inputs:
            measurement = values.get(required.signal_id)
            valid = (
                measurement is not None
                and measurement.quality is MeasurementQuality.VALID
                and measurement.unit == required.unit
                and measurement.age_seconds <= required.max_age_seconds
            )
            if valid:
                ready += 1
            else:
                issues.append(f"required_input_unavailable:{required.signal_id}")
        return ready / len(self.required_inputs)

    def _apply_conflict_rules(self, values: dict[str, Measurement], issues: list[str]) -> None:
        for rule in self.conflict_rules:
            left = values.get(rule.left_signal_id)
            right = values.get(rule.right_signal_id)
            if (
                left is None
                or right is None
                or left.quality is not MeasurementQuality.VALID
                or right.quality is not MeasurementQuality.VALID
                or left.unit != rule.unit
                or right.unit != rule.unit
            ):
                continue
            if abs(left.value - right.value) <= rule.maximum_absolute_difference:
                continue
            code = f"source_conflict:{rule.left_signal_id}:{rule.right_signal_id}"
            issues.append(code)
            for signal_id in (rule.left_signal_id, rule.right_signal_id):
                measurement = values[signal_id]
                values[signal_id] = measurement.model_copy(
                    update={
                        "quality": MeasurementQuality.SUSPECT,
                        "issues": (*measurement.issues, code),
                    }
                )

    @staticmethod
    def _utc(value) -> datetime:
        if isinstance(value, pd.Timestamp):
            value = value.to_pydatetime()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("prepared timestamps must include a timezone offset")
        return value.astimezone(UTC)
