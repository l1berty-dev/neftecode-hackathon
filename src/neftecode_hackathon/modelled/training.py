"""Train-only support, lag selection and sign-constrained sulfur response audit."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from neftecode_hackathon.quality.training import temporal_split


def _series(frame: pd.DataFrame, signal_id: str, time_column: str) -> pd.DataFrame:
    result = frame.loc[
        (frame["signal_id"] == signal_id) & (frame["quality"] == "valid"),
        [time_column, "value"],
    ].copy()
    result[time_column] = pd.to_datetime(result[time_column], utc=True).astype(
        "datetime64[ns, UTC]"
    )
    return result.dropna().sort_values(time_column).drop_duplicates(time_column, keep="last")


def _features_for_lag(
    origins: pd.DataFrame,
    telemetry: pd.DataFrame,
    analyses: pd.DataFrame,
    lag_minutes: int,
) -> pd.DataFrame:
    result = origins.sort_values("origin").copy()
    lookup_time = (result["origin"] - pd.Timedelta(minutes=lag_minutes)).astype(
        "datetime64[ns, UTC]"
    )
    for signal_id, name in (("ht:P8", "p8"), ("ht:T11", "t11"), ("ht:F19", "f19")):
        source = _series(telemetry, signal_id, "measured_at").rename(
            columns={"measured_at": "lookup", "value": name}
        )
        probe = pd.DataFrame({"lookup": lookup_time, "row": np.arange(len(result))})
        aligned = pd.merge_asof(
            probe.sort_values("lookup"),
            source,
            on="lookup",
            direction="backward",
            tolerance=pd.Timedelta("30min"),
        ).sort_values("row")
        result[name] = aligned[name].to_numpy()
    feed = _series(analyses, "lab:ht.point_1.sulfur_mass_fraction", "available_at").rename(
        columns={"available_at": "origin", "value": "feed_sulfur"}
    )
    result = pd.merge_asof(
        result.sort_values("origin"),
        feed,
        on="origin",
        direction="backward",
        tolerance=pd.Timedelta("2880min"),
    )
    return result.dropna().reset_index(drop=True)


def train_modelled_response(
    root: Path | None = None, *, progress: Callable[[str], None] | None = None
) -> dict[str, Any]:
    """Select lag and ridge on validation; touch test only for the final report."""

    repository = (root or Path(__file__).resolve().parents[3]).resolve()
    processed = repository / "data/processed"
    artifacts = repository / "artifacts"
    telemetry = pq.read_table(
        processed / "telemetry.parquet",
        filters=[("signal_id", "in", ["ht:P8", "ht:T11", "ht:F19"])],
        columns=["signal_id", "measured_at", "value", "quality"],
    ).to_pandas()
    analyses = pq.read_table(
        processed / "analyses.parquet",
        filters=[
            (
                "signal_id",
                "in",
                ["pak:ht.product_sulfur", "lab:ht.point_1.sulfur_mass_fraction"],
            )
        ],
        columns=["signal_id", "measured_at", "available_at", "value", "quality"],
    ).to_pandas()
    target = _series(analyses, "pak:ht.product_sulfur", "measured_at").rename(
        columns={"measured_at": "origin", "value": "current_sulfur"}
    )
    future = target.rename(columns={"origin": "target_time", "current_sulfur": "target"})
    target["target_time"] = target["origin"] + pd.Timedelta(minutes=180)
    origins = pd.merge_asof(
        target.sort_values("target_time"),
        future.sort_values("target_time"),
        on="target_time",
        direction="nearest",
        tolerance=pd.Timedelta("2min"),
    ).dropna()
    origins = origins[["origin", "target_time", "current_sulfur", "target"]]
    splits = temporal_split(origins, (0.70, 0.15, 0.15))
    candidate_lags = tuple(range(0, 181, 30))
    alphas = (0.01, 0.1, 1.0, 10.0)
    selected: tuple[float, int, float, Ridge, StandardScaler, tuple[str, ...]] | None = None
    if progress:
        progress("Selecting 0–180 minute response lag and ridge on validation")
    feature_names = ("feed_sulfur", "negative_p8", "t11", "negative_f19")
    for lag in candidate_lags:
        frame = _features_for_lag(origins, telemetry, analyses, lag)
        train = frame[frame["origin"].isin(splits.train["origin"])]
        validation = frame[frame["origin"].isin(splits.validation["origin"])]
        if len(train) < 100 or len(validation) < 20:
            continue
        x_train = np.column_stack([train["feed_sulfur"], -train["p8"], train["t11"], -train["f19"]])
        x_validation = np.column_stack(
            [
                validation["feed_sulfur"],
                -validation["p8"],
                validation["t11"],
                -validation["f19"],
            ]
        )
        scaler = StandardScaler().fit(x_train)
        for alpha in alphas:
            model = Ridge(alpha=alpha, positive=True, solver="lbfgs")
            model.fit(scaler.transform(x_train), train["target"].to_numpy())
            prediction = model.predict(scaler.transform(x_validation))
            mae = float(np.mean(np.abs(validation["target"].to_numpy() - prediction)))
            candidate = (mae, lag, alpha, model, scaler, feature_names)
            if selected is None or candidate[:3] < selected[:3]:
                selected = candidate
    if selected is None:
        raise ValueError("not enough point-in-time rows to train modelled response")

    validation_mae, lag, alpha, model, scaler, feature_names = selected
    frame = _features_for_lag(origins, telemetry, analyses, lag)
    validation = frame[frame["origin"].isin(splits.validation["origin"])]
    test = frame[frame["origin"].isin(splits.test["origin"])]

    def matrix(segment: pd.DataFrame) -> np.ndarray:
        return np.column_stack(
            [segment["feed_sulfur"], -segment["p8"], segment["t11"], -segment["f19"]]
        )

    validation_prediction = model.predict(scaler.transform(matrix(validation)))
    q90 = float(
        np.quantile(
            np.abs(validation["target"].to_numpy() - validation_prediction),
            0.90,
            method="higher",
        )
    )
    test_prediction = model.predict(scaler.transform(matrix(test)))
    test_mae = float(np.mean(np.abs(test["target"].to_numpy() - test_prediction)))
    train = frame[frame["origin"].isin(splits.train["origin"])]
    ranges = {
        name: {
            "p05": float(train[name].quantile(0.05)),
            "median": float(train[name].median()),
            "p95": float(train[name].quantile(0.95)),
        }
        for name in ("p8", "t11", "f19")
    }
    payload = {
        "schema_version": 1,
        "method": "positive ridge on [feed_sulfur, -P8, T11, -F19]",
        "selected_lag_minutes": lag,
        "selected_alpha": alpha,
        "validation_q90_mg_kg": q90,
        "coefficients_standardised": dict(zip(feature_names, model.coef_.tolist(), strict=True)),
        "intercept": float(model.intercept_),
        "control_ranges_train": ranges,
        "split": {
            "train_count": len(train),
            "validation_count": len(validation),
            "test_count": len(test),
            "validation_start": splits.validation_start.isoformat(),
            "test_start": splits.test_start.isoformat(),
            "purged_train": splits.purged_train,
            "purged_validation": splits.purged_validation,
        },
        "metrics": {"validation_mae": validation_mae, "test_mae": test_mae},
        "limitations": [
            "Historical association does not prove an unseen intervention effect.",
            "Scenario magnitudes remain explicit modelling assumptions; signs, lag and support are audited.",
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["model_version"] = (
        "modelled-response-v1:" + hashlib.sha256(canonical.encode()).hexdigest()[:16]
    )
    artifacts.mkdir(parents=True, exist_ok=True)
    output = artifacts / "modelled_manifest.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if progress:
        progress(f"Wrote {output.relative_to(repository)}")
    return payload
