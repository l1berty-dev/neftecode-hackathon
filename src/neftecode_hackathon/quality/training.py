"""Reproducible 60-minute continuation forecast training and evaluation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml
from sklearn.ensemble import HistGradientBoostingRegressor

from neftecode_hackathon.quality.features import ForecastFeatureBuilder, ForecastFeatureConfig


@dataclass(frozen=True)
class TemporalSplits:
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    validation_start: pd.Timestamp
    test_start: pd.Timestamp
    purged_train: int
    purged_validation: int


def temporal_split(frame: pd.DataFrame, fractions: tuple[float, float, float]) -> TemporalSplits:
    """Split ordered origins and purge rows whose future targets cross a boundary."""

    if len(frame) < 3 or not np.isclose(sum(fractions), 1.0):
        raise ValueError("temporal split requires data and fractions summing to one")
    ordered = frame.sort_values("origin", kind="stable").reset_index(drop=True)
    first = int(len(ordered) * fractions[0])
    second = int(len(ordered) * (fractions[0] + fractions[1]))
    if first <= 0 or second <= first or second >= len(ordered):
        raise ValueError("temporal split produced an empty segment")
    validation_start = ordered.loc[first, "origin"]
    test_start = ordered.loc[second, "origin"]
    raw_train = ordered.iloc[:first]
    raw_validation = ordered.iloc[first:second]
    train = raw_train.loc[raw_train["target_time"] < validation_start].copy()
    validation = raw_validation.loc[raw_validation["target_time"] < test_start].copy()
    test = ordered.iloc[second:].copy()
    return TemporalSplits(
        train=train,
        validation=validation,
        test=test,
        validation_start=validation_start,
        test_start=test_start,
        purged_train=len(raw_train) - len(train),
        purged_validation=len(raw_validation) - len(validation),
    )


def choose_predictor(model_mae: float, baseline_mae: float) -> str:
    """Use the learned model only for a strict validation improvement."""

    return "hist_gradient_boosting" if model_mae < baseline_mae else "persistence_baseline"


def forecast_metrics(
    actual: np.ndarray, prediction: np.ndarray, interval_radius: float, *, limit: float = 10.0
) -> dict[str, Any]:
    actual = np.asarray(actual, dtype=float)
    prediction = np.asarray(prediction, dtype=float)
    if len(actual) == 0 or len(actual) != len(prediction):
        raise ValueError("metrics require equally sized non-empty arrays")
    lower = np.maximum(0.0, prediction - interval_radius)
    upper = prediction + interval_radius
    exceedance = actual > limit
    alert = upper > limit
    missed = int(np.sum(exceedance & ~alert))
    false_alarm = int(np.sum(~exceedance & alert))
    exceedance_count = int(exceedance.sum())
    normal_count = int((~exceedance).sum())
    return {
        "count": int(len(actual)),
        "mae": float(np.mean(np.abs(actual - prediction))),
        "exceedance_count": exceedance_count,
        "normal_count": normal_count,
        "missed_exceedance_count": missed,
        "missed_exceedance_rate": (missed / exceedance_count if exceedance_count else None),
        "false_alarm_count": false_alarm,
        "false_alarm_rate": false_alarm / normal_count if normal_count else None,
        "interval_coverage": float(np.mean((actual >= lower) & (actual <= upper))),
        "mean_interval_width": float(np.mean(upper - lower)),
        "alert_rule": f"upper_interval_bound > {limit:g} mg/kg",
    }


def train_forecast(
    root: Path | None = None, *, progress: Callable[[str], None] | None = None
) -> dict[str, Any]:
    """Train, select on validation, evaluate once on test, and write local artifacts."""

    repository = (root or Path(__file__).resolve().parents[3]).resolve()
    processed = repository / "data" / "processed"
    artifacts = repository / "artifacts"
    audit = _read_json(processed / "audit_report.json")
    model_config_path = repository / "config" / "model.yaml"
    model_config = yaml.safe_load(model_config_path.read_text(encoding="utf-8"))
    feature_config = ForecastFeatureConfig.from_mapping(model_config)
    training_config = model_config["training"]
    if progress:
        progress("Loading prepared analyses")
    analyses = pq.read_table(
        processed / "analyses.parquet",
        columns=[
            "signal_id",
            "measured_at",
            "available_at",
            "value",
            "unit",
            "quality",
        ],
    ).to_pandas()
    dataset, target_audit = _build_target_dataset(analyses, feature_config)
    fractions = tuple(float(value) for value in training_config["split_fractions"])
    splits = temporal_split(dataset, fractions)
    builder = ForecastFeatureBuilder(feature_config)
    if progress:
        progress("Building point-in-time features")
    all_features = builder.from_prepared(pd.DatetimeIndex(dataset["origin"]), analyses)
    all_features.index = pd.DatetimeIndex(dataset["origin"])
    feature_lookup = all_features

    def features_for(segment: pd.DataFrame) -> pd.DataFrame:
        return feature_lookup.loc[pd.DatetimeIndex(segment["origin"])].reset_index(drop=True)

    x_train = features_for(splits.train)
    x_validation = features_for(splits.validation)
    x_test = features_for(splits.test)
    y_train = splits.train["target"].to_numpy(dtype=float)
    y_validation = splits.validation["target"].to_numpy(dtype=float)
    y_test = splits.test["target"].to_numpy(dtype=float)
    active_features = tuple(column for column in x_train if x_train[column].notna().any())
    dropped_features = tuple(column for column in x_train if column not in active_features)
    if not active_features:
        raise ValueError("all configured features are missing on train")
    estimator_config = training_config["estimator"]
    if estimator_config["name"] != "HistGradientBoostingRegressor":
        raise ValueError("unsupported estimator")
    estimator = HistGradientBoostingRegressor(
        loss=estimator_config["loss"],
        max_iter=int(estimator_config["max_iter"]),
        max_leaf_nodes=int(estimator_config["max_leaf_nodes"]),
        learning_rate=float(estimator_config["learning_rate"]),
        l2_regularization=float(estimator_config["l2_regularization"]),
        early_stopping=bool(estimator_config["early_stopping"]),
        random_state=int(model_config["forecast"]["random_seed"]),
    )
    if progress:
        progress(f"Fitting estimator on {len(x_train)} train rows")
    estimator.fit(x_train.loc[:, active_features], y_train)
    model_validation = estimator.predict(x_validation.loc[:, active_features])
    baseline_column = next(
        f"{spec.prefix}__current"
        for spec in feature_config.series
        if spec.signal_id == feature_config.target_signal_id
    )
    baseline_validation = x_validation[baseline_column].to_numpy(dtype=float)
    model_validation_mae = float(np.mean(np.abs(y_validation - model_validation)))
    baseline_validation_mae = float(np.mean(np.abs(y_validation - baseline_validation)))
    selected = choose_predictor(model_validation_mae, baseline_validation_mae)
    selected_validation = (
        model_validation if selected == "hist_gradient_boosting" else baseline_validation
    )
    quantile = float(training_config["interval_quantile"])
    interval_radius = float(
        np.quantile(np.abs(y_validation - selected_validation), quantile, method="higher")
    )
    model_test = estimator.predict(x_test.loc[:, active_features])
    baseline_test = x_test[baseline_column].to_numpy(dtype=float)
    selected_test = model_test if selected == "hist_gradient_boosting" else baseline_test

    split_summary = {
        "fractions": list(fractions),
        "validation_start": splits.validation_start.isoformat(),
        "test_start": splits.test_start.isoformat(),
        "train_count": len(splits.train),
        "validation_count": len(splits.validation),
        "test_count": len(splits.test),
        "purged_train_origins": splits.purged_train,
        "purged_validation_origins": splits.purged_validation,
        "purge_rule": "target_time must be strictly earlier than the next segment origin",
    }
    version_payload = {
        "dataset_version": audit["dataset_version"],
        "model_config_sha256": _sha256(model_config_path),
        "feature_schema": list(feature_config.feature_names),
        "active_features": list(active_features),
        "split": split_summary,
        "training_code_sha256": _sha256(Path(__file__)),
        "feature_code_sha256": _sha256(Path(__file__).with_name("features.py")),
    }
    model_version = "forecast-v1:" + _canonical_hash(version_payload)
    validation_metrics = {
        "model": forecast_metrics(y_validation, model_validation, interval_radius),
        "baseline": forecast_metrics(y_validation, baseline_validation, interval_radius),
        "selected": forecast_metrics(y_validation, selected_validation, interval_radius),
    }
    test_metrics = {
        "model": forecast_metrics(y_test, model_test, interval_radius),
        "baseline": forecast_metrics(y_test, baseline_test, interval_radius),
        "selected": forecast_metrics(y_test, selected_test, interval_radius),
    }
    lab_metrics = _evaluate_lims(
        analyses,
        builder,
        feature_config,
        estimator,
        active_features,
        selected,
        baseline_column,
        splits.test_start,
        interval_radius,
    )
    required_inputs = [
        {
            "signal_id": spec.signal_id,
            "unit": spec.unit,
            "max_age_seconds": feature_config.online_freshness_minutes * 60,
        }
        for spec in feature_config.series
        if spec.required_current
    ]
    manifest = {
        "schema_version": 1,
        "model_version": model_version,
        "dataset_version": audit["dataset_version"],
        "output_target": "ht.product_sulfur",
        "target_signal_id": feature_config.target_signal_id,
        "target_unit": feature_config.target_unit,
        "horizon_minutes": feature_config.horizon_minutes,
        "history_minutes": feature_config.history_minutes,
        "trained_through": splits.train["target_time"].max().isoformat(),
        "selected_through": splits.validation["target_time"].max().isoformat(),
        "replay_not_before": splits.test_start.isoformat(),
        "selected_predictor": selected,
        "estimator": dict(estimator_config),
        "feature_schema": list(feature_config.feature_names),
        "active_features": list(active_features),
        "dropped_train_empty_features": list(dropped_features),
        "required_inputs": required_inputs,
        "freshness_minutes": model_config["availability"]["freshness_minutes"],
        "uncertainty": {
            "method": "symmetric absolute validation residual quantile with lower clipped at zero",
            "quantile": quantile,
            "radius_mg_per_kg": interval_radius,
            "coverage_claim": "empirical validation calibration; test coverage is reported, not guaranteed",
        },
        "model_config_sha256": version_payload["model_config_sha256"],
        "limitations": [
            "Continuation forecast only; it does not establish a causal action effect.",
            "Only the 60-minute horizon is supported.",
            "Telemetry controls are excluded until their numerical units/scales are verified.",
            "LIMS features use only results available by origin under the 240-minute delay policy.",
            "Replay at or before selected_through is refused because model selection saw its future.",
        ],
    }
    metrics = {
        "schema_version": 1,
        "model_version": model_version,
        "dataset_version": audit["dataset_version"],
        "target_audit": target_audit,
        "split": split_summary,
        "selection": {
            "selected_predictor": selected,
            "rule": "select learned model only when validation MAE is strictly lower",
            "model_validation_mae": model_validation_mae,
            "baseline_validation_mae": baseline_validation_mae,
            "final_test_used_for_selection": False,
        },
        "interval_radius_mg_per_kg": interval_radius,
        "validation": validation_metrics,
        "test": test_metrics,
        "lims_product_sulfur_test": lab_metrics,
    }
    artifacts.mkdir(parents=True, exist_ok=True)
    _write_json(artifacts / "manifest.json", manifest)
    _write_json(artifacts / "metrics.json", metrics)
    joblib.dump(
        {
            "schema_version": 1,
            "model_version": model_version,
            "estimator": estimator,
            "selected_predictor": selected,
            "active_features": active_features,
            "feature_config": feature_config,
        },
        artifacts / "model.joblib",
    )
    (artifacts / "model_report.md").write_text(_model_report(manifest, metrics), encoding="utf-8")
    if progress:
        progress(
            f"Selected {selected}; validation MAE={validation_metrics['selected']['mae']:.6g}; "
            f"test MAE={test_metrics['selected']['mae']:.6g}"
        )
    return {"manifest": manifest, "metrics": metrics}


def _build_target_dataset(
    analyses: pd.DataFrame, config: ForecastFeatureConfig
) -> tuple[pd.DataFrame, dict[str, Any]]:
    raw = analyses.loc[analyses["signal_id"] == config.target_signal_id].copy()
    valid = raw.loc[
        (raw["quality"] == "valid")
        & (raw["unit"] == config.target_unit)
        & np.isfinite(raw["value"])
        & (raw["value"] >= 0)
    ].copy()
    valid["measured_at"] = pd.to_datetime(valid["measured_at"], utc=True)
    duplicate_count = int(valid.duplicated("measured_at", keep=False).sum())
    valid = valid.sort_values(["measured_at", "available_at"], kind="stable").drop_duplicates(
        "measured_at", keep="last"
    )
    series = valid.set_index("measured_at")["value"].sort_index()
    origins = series.index
    target_times = origins + pd.Timedelta(minutes=config.horizon_minutes)
    targets = series.reindex(target_times).to_numpy()
    paired = pd.DataFrame(
        {"origin": origins, "target_time": target_times, "target": targets}
    ).dropna(subset=["target"])
    return paired.reset_index(drop=True), {
        "raw_target_rows": len(raw),
        "valid_unique_target_rows": len(series),
        "excluded_invalid_or_duplicate_rows": len(raw) - len(series),
        "duplicate_timestamp_rows": duplicate_count,
        "origins_with_exact_60m_target": len(paired),
        "origins_without_exact_60m_target": len(series) - len(paired),
        "target_matching": "exact timestamp only; no interpolation",
    }


def _evaluate_lims(
    analyses: pd.DataFrame,
    builder: ForecastFeatureBuilder,
    config: ForecastFeatureConfig,
    estimator,
    active_features: tuple[str, ...],
    selected: str,
    baseline_column: str,
    test_start: pd.Timestamp,
    interval_radius: float,
) -> dict[str, Any]:
    lab = ForecastFeatureBuilder._valid_records(
        analyses, "lab:ht.point_2.sulfur", config.target_unit
    )
    lab = lab.loc[lab["measured_at"] - pd.Timedelta(minutes=config.horizon_minutes) >= test_start]
    if lab.empty:
        return {
            "count": 0,
            "mae": None,
            "reason": "No valid product LIMS samples in the untouched test period.",
            "origin_rule": "sample measured_at minus 60 minutes; sample value is label only",
        }
    origins = pd.DatetimeIndex(lab["measured_at"] - pd.Timedelta(minutes=config.horizon_minutes))
    features = builder.from_prepared(origins, analyses)
    usable = features[baseline_column].notna()
    if not usable.any():
        return {
            "count": 0,
            "mae": None,
            "reason": "No exact point-in-time PAK state for test-period LIMS samples.",
            "origin_rule": "sample measured_at minus 60 minutes; sample value is label only",
        }
    features = features.loc[usable]
    actual = lab.loc[usable.to_numpy(), "value"].to_numpy(dtype=float)
    prediction = (
        estimator.predict(features.loc[:, active_features])
        if selected == "hist_gradient_boosting"
        else features[baseline_column].to_numpy(dtype=float)
    )
    result = forecast_metrics(actual, prediction, interval_radius)
    result.update(
        {
            "sample_count_before_feature_filter": len(lab),
            "origin_rule": "state at sample measured_at minus 60 minutes; laboratory value is never a feature for its own forecast",
            "availability_rule": "all features require available_at <= origin; LIMS delay is 240 minutes",
        }
    )
    return result


def _model_report(manifest: Mapping[str, Any], metrics: Mapping[str, Any]) -> str:
    selection = metrics["selection"]
    validation = metrics["validation"]["selected"]
    test = metrics["test"]["selected"]
    lab = metrics["lims_product_sulfur_test"]
    return f"""# Continuation forecast report

Model version: `{manifest["model_version"]}`
Dataset version: `{manifest["dataset_version"]}`

The selected predictor is **{manifest["selected_predictor"]}**. Selection used validation MAE
only: learned model `{selection["model_validation_mae"]:.6g}`, persistence baseline
`{selection["baseline_validation_mae"]:.6g}`. The final test was not used for feature,
hyperparameter, predictor, or interval selection.

The forecast target is PAK product sulfur at exactly t+60 minutes. No target interpolation is
performed. Validation MAE is `{validation["mae"]:.6g}` mg/kg; untouched test MAE is
`{test["mae"]:.6g}` mg/kg. The symmetric interval radius is
`{manifest["uncertainty"]["radius_mg_per_kg"]:.6g}` mg/kg, calibrated as the 90% quantile of
absolute validation residuals; the lower bound is clipped at zero. Test coverage is
`{test["interval_coverage"]:.6g}` and is an empirical result, not a guaranteed probability.

Product LIMS comparison uses state at 60 minutes before sample time and never exposes the sample
to its own features. Matched test samples: `{lab["count"]}`; MAE: `{lab["mae"]}`.

Limitations:

""" + "".join(f"- {item}\n" for item in manifest["limitations"])


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
