import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from neftecode_hackathon.contracts import MeasurementQuality
from neftecode_hackathon.data import (
    RequiredInputSpec,
    SnapshotProvider,
    SourceConflictRule,
)


def _row(signal_id, measured_at, value, *, source="telemetry", available_at=None, unit=None):
    return {
        "signal_id": signal_id,
        "measured_at": measured_at,
        "available_at": available_at or measured_at,
        "value": value,
        "unit": unit,
        "source": source,
        "quality": "valid",
        "issues": "[]",
    }


@pytest.fixture
def prepared(tmp_path: Path) -> Path:
    version = "sha256:synthetic-point-in-time"
    (tmp_path / "audit_report.json").write_text(
        json.dumps({"dataset_version": version}), encoding="utf-8"
    )
    (tmp_path / "data_dictionary.json").write_text(
        json.dumps({"dataset_version": version}), encoding="utf-8"
    )
    at = datetime(2026, 1, 2, 12, tzinfo=UTC)
    pd.DataFrame(
        [
            _row("ht:P8", at - timedelta(hours=6), 100.0),
            _row("ht:P8", at - timedelta(minutes=10), 101.0),
            _row("ht:P8", at + timedelta(minutes=1), 999.0),
        ]
    ).to_parquet(tmp_path / "telemetry.parquet", index=False)
    pd.DataFrame(
        [
            _row(
                "lab:ht.point_1.sulfur",
                at - timedelta(hours=5),
                25.0,
                source="lims",
                available_at=at - timedelta(hours=1),
                unit="mg/kg",
            ),
            _row(
                "lab:ht.point_2.sulfur",
                at - timedelta(hours=4),
                5.0,
                source="lims",
                available_at=at,
                unit="mg/kg",
            ),
            _row(
                "lab:ht.point_2.sulfur",
                at - timedelta(minutes=30),
                1.0,
                source="lims",
                available_at=at + timedelta(hours=3, minutes=30),
                unit="mg/kg",
            ),
            _row(
                "pak:ht.product_sulfur",
                at - timedelta(minutes=10),
                8.0,
                source="pak",
                unit="mg/kg",
            ),
        ]
    ).to_parquet(tmp_path / "analyses.parquet", index=False)
    return tmp_path


def _provider(prepared: Path, **kwargs) -> SnapshotProvider:
    return SnapshotProvider(
        prepared,
        freshness_minutes={"online": 20, "pak": 20, "lims": 2880},
        required_inputs=(
            RequiredInputSpec("pak:ht.product_sulfur", "mg/kg", 1200),
            RequiredInputSpec("lab:ht.point_2.sulfur", "mg/kg", 172800),
        ),
        manifest_verified=True,
        **kwargs,
    )


def test_snapshot_uses_backward_asof_and_delayed_lab_boundary(prepared: Path) -> None:
    boundary = datetime(2026, 1, 2, 12, tzinfo=UTC)
    before = _provider(prepared).get_snapshot(boundary - timedelta(seconds=1))
    after = _provider(prepared).get_snapshot(boundary)

    assert "lab:ht.point_2.sulfur" not in before.values
    assert before.completeness == 0.5
    assert after.values["lab:ht.point_2.sulfur"].value == 5.0
    assert after.values["lab:ht.point_1.sulfur"].value == 25.0
    assert after.values["pak:ht.product_sulfur"].value == 8.0
    assert after.completeness == 1.0
    assert all(item.measured_at <= after.as_of for item in after.history)
    assert 999.0 not in {item.value for item in after.history}
    assert 1.0 not in {item.value for item in after.history}


def test_history_includes_exact_six_hour_boundary_and_snapshot_id_is_stable(
    prepared: Path,
) -> None:
    at = datetime(2026, 1, 2, 12, tzinfo=UTC)
    first = _provider(prepared).get_snapshot(at)
    second = _provider(prepared).get_snapshot(at)

    assert any(item.measured_at == at - timedelta(hours=6) for item in first.history)
    assert first.snapshot_id == second.snapshot_id
    assert first.values["ht:P8"].value == 101.0
    assert first.values["ht:P8"].age_seconds == 600


def test_unverified_manifest_is_explicit_and_not_complete(prepared: Path) -> None:
    snapshot = SnapshotProvider(prepared).get_snapshot(datetime(2026, 1, 2, 12, tzinfo=UTC))

    assert snapshot.completeness == 0
    assert "required_input_manifest_unverified" in snapshot.issues


def test_stale_value_is_suspect_and_reduces_completeness(prepared: Path) -> None:
    snapshot = SnapshotProvider(
        prepared,
        freshness_minutes={"pak": 5},
        required_inputs=(RequiredInputSpec("pak:ht.product_sulfur", "mg/kg", 300),),
        manifest_verified=True,
    ).get_snapshot(datetime(2026, 1, 2, 12, tzinfo=UTC))

    measurement = snapshot.values["pak:ht.product_sulfur"]
    assert measurement.quality is MeasurementQuality.SUSPECT
    assert "stale" in measurement.issues
    assert snapshot.completeness == 0


def test_trained_conflict_rule_marks_both_sources_suspect(prepared: Path) -> None:
    rule = SourceConflictRule(
        "lab:ht.point_2.sulfur",
        "pak:ht.product_sulfur",
        maximum_absolute_difference=2.0,
        unit="mg/kg",
        evidence="Synthetic train/validation threshold",
    )
    snapshot = _provider(prepared, conflict_rules=(rule,)).get_snapshot(
        datetime(2026, 1, 2, 12, tzinfo=UTC)
    )

    assert snapshot.values[rule.left_signal_id].quality is MeasurementQuality.SUSPECT
    assert snapshot.values[rule.right_signal_id].quality is MeasurementQuality.SUSPECT
    assert any(issue.startswith("source_conflict:") for issue in snapshot.issues)
    assert snapshot.completeness == 0


def test_naive_replay_timestamp_is_rejected(prepared: Path) -> None:
    with pytest.raises(ValueError, match="timezone"):
        _provider(prepared).get_snapshot(datetime(2026, 1, 2, 12))
