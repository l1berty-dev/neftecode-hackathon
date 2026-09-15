"""One point-in-time feature definition shared by training and inference."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from neftecode_hackathon.contracts import MeasurementQuality, ProcessSnapshot


@dataclass(frozen=True)
class SeriesSpec:
    signal_id: str
    unit: str
    prefix: str
    required_current: bool


@dataclass(frozen=True)
class AnalysisSpec:
    signal_id: str
    unit: str
    prefix: str
    freshness_minutes: int


@dataclass(frozen=True)
class ForecastFeatureConfig:
    target_signal_id: str
    target_unit: str
    horizon_minutes: int
    history_minutes: int
    online_freshness_minutes: int
    series: tuple[SeriesSpec, ...]
    analyses: tuple[AnalysisSpec, ...]
    lags_minutes: tuple[int, ...]
    rolling_windows_minutes: tuple[int, ...]
    change_minutes: int

    @classmethod
    def from_mapping(cls, model_config: Mapping[str, Any]) -> ForecastFeatureConfig:
        training = model_config["training"]
        forecast = model_config["forecast"]
        availability = model_config["availability"]
        result = cls(
            target_signal_id=str(training["target_signal_id"]),
            target_unit=str(training["target_unit"]),
            horizon_minutes=int(forecast["horizon_minutes"]),
            history_minutes=int(forecast["history_minutes"]),
            online_freshness_minutes=int(availability["freshness_minutes"]["pak"]),
            series=tuple(SeriesSpec(**item) for item in training["feature_series"]),
            analyses=tuple(AnalysisSpec(**item) for item in training["analysis_features"]),
            lags_minutes=tuple(int(value) for value in training["lags_minutes"]),
            rolling_windows_minutes=tuple(
                int(value) for value in training["rolling_windows_minutes"]
            ),
            change_minutes=int(training["change_minutes"]),
        )
        result._validate()
        return result

    @property
    def feature_names(self) -> tuple[str, ...]:
        names: list[str] = []
        for spec in self.series:
            names.append(f"{spec.prefix}__current")
            names.append(f"{spec.prefix}__age_seconds")
            names.extend(f"{spec.prefix}__lag_{lag}m" for lag in self.lags_minutes)
            names.extend(
                f"{spec.prefix}__mean_{window}m" for window in self.rolling_windows_minutes
            )
            names.append(f"{spec.prefix}__change_{self.change_minutes}m")
        for spec in self.analyses:
            names.extend((f"{spec.prefix}__current", f"{spec.prefix}__age_seconds"))
        return tuple(names)

    def _validate(self) -> None:
        if self.horizon_minutes <= 0 or self.history_minutes <= 0:
            raise ValueError("forecast horizon/history must be positive")
        if any(value <= 0 for value in (*self.lags_minutes, *self.rolling_windows_minutes)):
            raise ValueError("lags and rolling windows must be positive")
        if max((*self.lags_minutes, *self.rolling_windows_minutes, self.change_minutes)) > (
            self.history_minutes
        ):
            raise ValueError("feature window exceeds snapshot history")
        prefixes = [item.prefix for item in (*self.series, *self.analyses)]
        if len(prefixes) != len(set(prefixes)):
            raise ValueError("feature prefixes must be unique")
        if not any(
            item.signal_id == self.target_signal_id and item.required_current
            for item in self.series
        ):
            raise ValueError("target current value must be a required feature")


class ForecastFeatureBuilder:
    """Create identical named features from prepared records or a ProcessSnapshot."""

    def __init__(self, config: ForecastFeatureConfig) -> None:
        self.config = config

    def from_prepared(self, origins: pd.DatetimeIndex, analyses: pd.DataFrame) -> pd.DataFrame:
        origins = self._utc_index(origins)
        features = pd.DataFrame(index=origins)
        for spec in self.config.series:
            records = self._valid_records(analyses, spec.signal_id, spec.unit)
            current, current_age = self._asof_series(
                origins, records, self.config.online_freshness_minutes
            )
            features[f"{spec.prefix}__current"] = current.to_numpy()
            features[f"{spec.prefix}__age_seconds"] = current_age.to_numpy()
            for lag in self.config.lags_minutes:
                lagged, _ = self._asof_series(
                    origins - pd.Timedelta(minutes=lag),
                    records,
                    self.config.online_freshness_minutes,
                )
                features[f"{spec.prefix}__lag_{lag}m"] = lagged.to_numpy()
            indexed = records.drop_duplicates("measured_at", keep="last").set_index("measured_at")
            for window in self.config.rolling_windows_minutes:
                rolled = indexed["value"].rolling(f"{window}min", closed="both").mean()
                features[f"{spec.prefix}__mean_{window}m"] = rolled.reindex(origins).to_numpy()
            change_lag, _ = self._asof_series(
                origins - pd.Timedelta(minutes=self.config.change_minutes),
                records,
                self.config.online_freshness_minutes,
            )
            features[f"{spec.prefix}__change_{self.config.change_minutes}m"] = (
                current.to_numpy() - change_lag.to_numpy()
            )
        for spec in self.config.analyses:
            records = self._valid_records(analyses, spec.signal_id, spec.unit)
            current, age = self._asof_analysis(origins, records, spec.freshness_minutes)
            features[f"{spec.prefix}__current"] = current.to_numpy()
            features[f"{spec.prefix}__age_seconds"] = age.to_numpy()
        return features.loc[:, self.config.feature_names]

    def from_snapshot(self, snapshot: ProcessSnapshot) -> pd.DataFrame:
        snapshot = ProcessSnapshot.model_validate(snapshot.model_dump())
        origin = pd.Timestamp(snapshot.as_of)
        features: dict[str, float] = {}
        history_by_signal: dict[str, list[tuple[pd.Timestamp, float]]] = {}
        for item in snapshot.history:
            history_by_signal.setdefault(item.signal_id, []).append(
                (pd.Timestamp(item.measured_at), item.value)
            )
        for spec in self.config.series:
            measurement = snapshot.values.get(spec.signal_id)
            current = np.nan
            age = np.nan
            if (
                measurement is not None
                and measurement.value is not None
                and measurement.quality is MeasurementQuality.VALID
                and measurement.unit == spec.unit
                and measurement.age_seconds <= self.config.online_freshness_minutes * 60
                and measurement.value >= 0
            ):
                current = measurement.value
                age = measurement.age_seconds
            features[f"{spec.prefix}__current"] = current
            features[f"{spec.prefix}__age_seconds"] = age
            records = sorted(history_by_signal.get(spec.signal_id, ()))
            for lag in self.config.lags_minutes:
                features[f"{spec.prefix}__lag_{lag}m"] = self._history_asof(
                    records, origin - pd.Timedelta(minutes=lag)
                )
            for window in self.config.rolling_windows_minutes:
                start = origin - pd.Timedelta(minutes=window)
                values = [
                    value for time, value in records if start <= time <= origin and value >= 0
                ]
                features[f"{spec.prefix}__mean_{window}m"] = (
                    float(np.mean(values)) if values else np.nan
                )
            change_lag = self._history_asof(
                records, origin - pd.Timedelta(minutes=self.config.change_minutes)
            )
            features[f"{spec.prefix}__change_{self.config.change_minutes}m"] = (
                current - change_lag if np.isfinite(current) and np.isfinite(change_lag) else np.nan
            )
        for spec in self.config.analyses:
            measurement = snapshot.values.get(spec.signal_id)
            value = np.nan
            age = np.nan
            if (
                measurement is not None
                and measurement.value is not None
                and measurement.quality is MeasurementQuality.VALID
                and measurement.unit == spec.unit
                and measurement.age_seconds <= spec.freshness_minutes * 60
                and measurement.value >= 0
            ):
                value = measurement.value
                age = measurement.age_seconds
            features[f"{spec.prefix}__current"] = value
            features[f"{spec.prefix}__age_seconds"] = age
        return pd.DataFrame(
            [[features[name] for name in self.config.feature_names]],
            columns=self.config.feature_names,
        )

    @staticmethod
    def _utc_index(values: pd.DatetimeIndex) -> pd.DatetimeIndex:
        values = pd.DatetimeIndex(values)
        if values.tz is None:
            raise ValueError("feature origins must include timezone")
        return values.tz_convert("UTC")

    @staticmethod
    def _valid_records(frame: pd.DataFrame, signal_id: str, unit: str) -> pd.DataFrame:
        records = frame.loc[
            (frame["signal_id"] == signal_id)
            & (frame["quality"] == "valid")
            & (frame["unit"] == unit),
            ["measured_at", "available_at", "value"],
        ].copy()
        records["measured_at"] = pd.to_datetime(records["measured_at"], utc=True)
        records["available_at"] = pd.to_datetime(records["available_at"], utc=True)
        records = records.loc[np.isfinite(records["value"]) & (records["value"] >= 0)].sort_values(
            ["measured_at", "available_at"], kind="stable"
        )
        return records

    @staticmethod
    def _asof_series(
        queries: pd.DatetimeIndex, records: pd.DataFrame, freshness_minutes: int
    ) -> tuple[pd.Series, pd.Series]:
        left = pd.DataFrame({"query": queries, "_order": np.arange(len(queries))}).sort_values(
            "query"
        )
        if records.empty:
            empty = pd.Series(np.nan, index=range(len(queries)), dtype=float)
            return empty, empty.copy()
        right = records.sort_values("measured_at", kind="stable").drop_duplicates(
            "measured_at", keep="last"
        )
        merged = pd.merge_asof(
            left,
            right,
            left_on="query",
            right_on="measured_at",
            direction="backward",
            tolerance=pd.Timedelta(minutes=freshness_minutes),
        ).sort_values("_order")
        unavailable = merged["available_at"].isna() | (merged["available_at"] > merged["query"])
        values = merged["value"].mask(unavailable).reset_index(drop=True)
        age = (merged["query"] - merged["measured_at"]).dt.total_seconds().mask(unavailable)
        return values.reset_index(drop=True), age.reset_index(drop=True)

    @staticmethod
    def _asof_analysis(
        origins: pd.DatetimeIndex, records: pd.DataFrame, freshness_minutes: int
    ) -> tuple[pd.Series, pd.Series]:
        left = pd.DataFrame({"query": origins, "_order": np.arange(len(origins))}).sort_values(
            "query"
        )
        if records.empty:
            empty = pd.Series(np.nan, index=range(len(origins)), dtype=float)
            return empty, empty.copy()
        right = records.sort_values("available_at", kind="stable").drop_duplicates(
            "available_at", keep="last"
        )
        merged = pd.merge_asof(
            left,
            right,
            left_on="query",
            right_on="available_at",
            direction="backward",
        ).sort_values("_order")
        age = (merged["query"] - merged["measured_at"]).dt.total_seconds()
        invalid = merged["measured_at"].isna() | (age < 0) | (age > freshness_minutes * 60)
        return (
            merged["value"].mask(invalid).reset_index(drop=True),
            age.mask(invalid).reset_index(drop=True),
        )

    def _history_asof(
        self, records: list[tuple[pd.Timestamp, float]], query: pd.Timestamp
    ) -> float:
        candidates = [
            (time, value)
            for time, value in records
            if time <= query
            and query - time <= pd.Timedelta(minutes=self.config.online_freshness_minutes)
            and value >= 0
        ]
        return float(candidates[-1][1]) if candidates else np.nan
