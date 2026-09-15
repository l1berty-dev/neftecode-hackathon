import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import joblib
import numpy as np
import pandas as pd
import pytest
import yaml

from neftecode_hackathon.contracts import (
    Action,
    ActionOrigin,
    Applicability,
    HistoryRecord,
    Measurement,
    MeasurementQuality,
    ProcessSnapshot,
    SnapshotMode,
)
from neftecode_hackathon.quality.features import ForecastFeatureBuilder, ForecastFeatureConfig
from neftecode_hackathon.quality.forecast import ForecastQualityAgent
from neftecode_hackathon.quality.training import (
    _build_target_dataset,
    choose_predictor,
    forecast_metrics,
    temporal_split,
)


def model_config() -> dict:
    return {
        "forecast": {"horizon_minutes": 60, "history_minutes": 60, "random_seed": 42},
        "availability": {"freshness_minutes": {"pak": 20}},
        "training": {
            "target_signal_id": "pak:ht.product_sulfur",
            "target_unit": "mg/kg",
            "feature_series": [
                {
                    "signal_id": "pak:ht.product_sulfur",
                    "unit": "mg/kg",
                    "prefix": "pak_sulfur",
                    "required_current": True,
                }
            ],
            "analysis_features": [
                {
                    "signal_id": "lab:ht.point_2.sulfur",
                    "unit": "mg/kg",
                    "prefix": "lims_product_sulfur",
                    "freshness_minutes": 2880,
                }
            ],
            "lags_minutes": [10, 60],
            "rolling_windows_minutes": [60],
            "change_minutes": 60,
        },
    }


def analysis_row(signal_id, measured_at, value, *, available_at=None, source="pak"):
    return {
        "signal_id": signal_id,
        "measured_at": measured_at,
        "available_at": available_at or measured_at,
        "value": value,
        "unit": "mg/kg",
        "source": source,
        "quality": "valid",
        "issues": "[]",
    }


def snapshot_at(at: datetime) -> ProcessSnapshot:
    def measurement(value, measured_at, source):
        return Measurement(
            value=value,
            unit="mg/kg",
            source=source,
            measured_at=measured_at,
            available_at=measured_at if source == "pak" else at - timedelta(hours=1),
            age_seconds=(at - measured_at).total_seconds(),
            quality=MeasurementQuality.VALID,
        )

    return ProcessSnapshot(
        snapshot_id=uuid4(),
        as_of=at,
        mode=SnapshotMode.REPLAY,
        dataset_version="sha256:test",
        values={
            "pak:ht.product_sulfur": measurement(7.0, at, "pak"),
            "lab:ht.point_2.sulfur": measurement(20.0, at - timedelta(hours=5), "lims"),
        },
        history=(
            HistoryRecord(
                signal_id="pak:ht.product_sulfur",
                measured_at=at - timedelta(minutes=60),
                value=5.0,
            ),
            HistoryRecord(
                signal_id="pak:ht.product_sulfur",
                measured_at=at - timedelta(minutes=10),
                value=6.0,
            ),
            HistoryRecord(signal_id="pak:ht.product_sulfur", measured_at=at, value=7.0),
        ),
        completeness=1.0,
    )


def test_training_and_snapshot_feature_builder_are_identical() -> None:
    at = datetime(2026, 1, 2, 12, tzinfo=UTC)
    analyses = pd.DataFrame(
        [
            analysis_row("pak:ht.product_sulfur", at - timedelta(minutes=60), 5.0),
            analysis_row("pak:ht.product_sulfur", at - timedelta(minutes=10), 6.0),
            analysis_row("pak:ht.product_sulfur", at, 7.0),
            analysis_row(
                "lab:ht.point_2.sulfur",
                at - timedelta(hours=5),
                20.0,
                available_at=at - timedelta(hours=1),
                source="lims",
            ),
        ]
    )
    builder = ForecastFeatureBuilder(ForecastFeatureConfig.from_mapping(model_config()))

    training = builder.from_prepared(pd.DatetimeIndex([at]), analyses)
    serving = builder.from_snapshot(snapshot_at(at))

    pd.testing.assert_frame_equal(
        training.reset_index(drop=True), serving.reset_index(drop=True), check_dtype=False
    )
    assert training.iloc[0]["pak_sulfur__change_60m"] == 2.0
    assert training.iloc[0]["lims_product_sulfur__age_seconds"] == 5 * 3600


def test_future_lims_result_is_not_a_feature() -> None:
    at = datetime(2026, 1, 2, 12, tzinfo=UTC)
    analyses = pd.DataFrame(
        [
            analysis_row("pak:ht.product_sulfur", at, 7.0),
            analysis_row(
                "lab:ht.point_2.sulfur",
                at - timedelta(minutes=30),
                1.0,
                available_at=at + timedelta(hours=3, minutes=30),
                source="lims",
            ),
        ]
    )
    builder = ForecastFeatureBuilder(ForecastFeatureConfig.from_mapping(model_config()))

    features = builder.from_prepared(pd.DatetimeIndex([at]), analyses)

    assert np.isnan(features.iloc[0]["lims_product_sulfur__current"])


def test_exact_target_matching_does_not_interpolate() -> None:
    config = ForecastFeatureConfig.from_mapping(model_config())
    start = datetime(2026, 1, 1, tzinfo=UTC)
    analyses = pd.DataFrame(
        [
            analysis_row("pak:ht.product_sulfur", start, 5.0),
            analysis_row("pak:ht.product_sulfur", start + timedelta(minutes=50), 6.0),
            analysis_row("pak:ht.product_sulfur", start + timedelta(minutes=60), 7.0),
        ]
    )

    dataset, audit = _build_target_dataset(analyses, config)

    assert len(dataset) == 1
    assert dataset.iloc[0]["origin"] == start
    assert dataset.iloc[0]["target"] == 7.0
    assert audit["origins_without_exact_60m_target"] == 2


def test_temporal_split_purges_crossing_targets() -> None:
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    origins = pd.date_range(start, periods=100, freq="10min")
    frame = pd.DataFrame(
        {
            "origin": origins,
            "target_time": origins + pd.Timedelta(minutes=60),
            "target": np.arange(100, dtype=float),
        }
    )

    splits = temporal_split(frame, (0.7, 0.15, 0.15))

    assert splits.purged_train == 6
    assert splits.purged_validation == 6
    assert splits.train["target_time"].max() < splits.validation_start
    assert splits.validation["target_time"].max() < splits.test_start


def test_selection_and_event_rates_are_fail_honest() -> None:
    assert choose_predictor(1.0, 1.0) == "persistence_baseline"
    assert choose_predictor(0.9, 1.0) == "hist_gradient_boosting"
    metrics = forecast_metrics(np.array([1.0, 2.0]), np.array([1.0, 2.0]), 0.1)
    assert metrics["missed_exceedance_rate"] is None
    assert metrics["false_alarm_rate"] == 0


def test_artifact_agent_serves_only_safe_baseline_replay(tmp_path: Path) -> None:
    config_path = tmp_path / "model.yaml"
    config_path.write_text(yaml.safe_dump(model_config()), encoding="utf-8")
    feature_config = ForecastFeatureConfig.from_mapping(model_config())
    config_sha256 = hashlib.sha256(config_path.read_bytes()).hexdigest()
    manifest = {
        "model_version": "forecast-v1:test",
        "dataset_version": "sha256:test",
        "output_target": "ht.product_sulfur",
        "target_unit": "mg/kg",
        "horizon_minutes": 60,
        "replay_not_before": "2026-01-02T00:00:00+00:00",
        "selected_predictor": "persistence_baseline",
        "feature_schema": list(feature_config.feature_names),
        "active_features": list(feature_config.feature_names),
        "model_config_sha256": config_sha256,
        "required_inputs": [
            {
                "signal_id": "pak:ht.product_sulfur",
                "unit": "mg/kg",
                "max_age_seconds": 1200,
            }
        ],
        "uncertainty": {"radius_mg_per_kg": 1.0, "quantile": 0.9},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    joblib.dump(
        {
            "model_version": "forecast-v1:test",
            "estimator": None,
            "selected_predictor": "persistence_baseline",
            "active_features": feature_config.feature_names,
        },
        tmp_path / "model.joblib",
    )
    agent = ForecastQualityAgent(tmp_path, model_config_path=config_path)
    baseline = Action(action_id=uuid4(), label="Keep", origin=ActionOrigin.BASELINE)
    safe_snapshot = snapshot_at(datetime(2026, 1, 2, 12, tzinfo=UTC))

    result = agent.assess(safe_snapshot, baseline, 60)
    assert result.applicability is Applicability.SUPPORTED
    assert result.prediction == 7.0
    assert (result.lower, result.upper) == (6.0, 8.0)

    early = snapshot_at(datetime(2026, 1, 1, 12, tzinfo=UTC))
    assert agent.assess(early, baseline, 60).applicability is Applicability.UNSUPPORTED
    changed = baseline.model_copy(update={"changes": {"ht:P8": 1.0}})
    assert agent.assess(safe_snapshot, changed, 60).applicability is Applicability.UNSUPPORTED

    changed_config = model_config()
    changed_config["forecast"]["random_seed"] = 7
    config_path.write_text(yaml.safe_dump(changed_config), encoding="utf-8")
    with pytest.raises(ValueError, match="configuration"):
        ForecastQualityAgent(tmp_path, model_config_path=config_path)


def test_feature_config_rejects_window_beyond_snapshot_history() -> None:
    raw = model_config()
    raw["training"]["lags_minutes"] = [120]
    with pytest.raises(ValueError, match="history"):
        ForecastFeatureConfig.from_mapping(raw)
