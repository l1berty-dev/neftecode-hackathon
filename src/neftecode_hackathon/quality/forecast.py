"""Artifact-backed quality agent for the 60-minute continuation forecast."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import joblib
import numpy as np
import yaml

from neftecode_hackathon.contracts import (
    Action,
    Applicability,
    ProcessSnapshot,
    QualityAssessment,
)
from neftecode_hackathon.quality.action_support import action_rejection_reasons
from neftecode_hackathon.quality.features import ForecastFeatureBuilder, ForecastFeatureConfig


class ForecastQualityAgent:
    """Serve continuation forecasts and explicit artifact-backed action refusals."""

    def __init__(self, artifacts_directory: Path, *, model_config_path: Path) -> None:
        artifacts_directory = artifacts_directory.resolve()
        self.manifest = json.loads(
            (artifacts_directory / "manifest.json").read_text(encoding="utf-8")
        )
        payload = joblib.load(artifacts_directory / "model.joblib")
        if payload["model_version"] != self.manifest["model_version"]:
            raise ValueError("model.joblib and manifest.json versions do not match")
        if payload["selected_predictor"] != self.manifest["selected_predictor"]:
            raise ValueError("model.joblib and manifest.json select different predictors")
        if list(payload["active_features"]) != self.manifest["active_features"]:
            raise ValueError("model.joblib and manifest.json active features do not match")
        if self.manifest.get("action_support", {}).get("schema_version") != 1:
            raise ValueError("manifest action-support audit is missing or unsupported")
        if self._sha256(model_config_path) != self.manifest["model_config_sha256"]:
            raise ValueError("runtime model configuration does not match the trained manifest")
        model_config = yaml.safe_load(model_config_path.read_text(encoding="utf-8"))
        self.feature_config = ForecastFeatureConfig.from_mapping(model_config)
        if list(self.feature_config.feature_names) != self.manifest["feature_schema"]:
            raise ValueError("runtime feature schema does not match the trained manifest")
        self.builder = ForecastFeatureBuilder(self.feature_config)
        self.estimator = payload["estimator"]
        self.active_features = tuple(payload["active_features"])
        self.selected_predictor = str(payload["selected_predictor"])
        self.model_version = str(payload["model_version"])

    @classmethod
    def from_repository(cls, root: Path | None = None) -> ForecastQualityAgent:
        repository = (root or Path(__file__).resolve().parents[3]).resolve()
        return cls(repository / "artifacts", model_config_path=repository / "config" / "model.yaml")

    def assess(
        self, snapshot: ProcessSnapshot, action: Action, horizon_minutes: int
    ) -> QualityAssessment:
        snapshot = ProcessSnapshot.model_validate(snapshot.model_dump())
        action = Action.model_validate(action.model_dump())
        forecast_at = snapshot.as_of + timedelta(minutes=horizon_minutes)
        reasons: list[str] = []
        applicability = Applicability.SUPPORTED
        if horizon_minutes != self.manifest["horizon_minutes"]:
            applicability = Applicability.UNSUPPORTED
            reasons.append("Artifact supports only the configured 60-minute horizon.")
        if action.changes:
            applicability = Applicability.UNSUPPORTED
            reasons.extend(action_rejection_reasons(action, self.manifest["action_support"]))
            reasons.append(
                "No counterfactual prediction is exposed; the continuation model does not establish intervention effects."
            )
        if snapshot.dataset_version != self.manifest["dataset_version"]:
            applicability = Applicability.INSUFFICIENT_DATA
            reasons.append("Snapshot dataset version does not match the model manifest.")
        replay_not_before = datetime.fromisoformat(self.manifest["replay_not_before"])
        if snapshot.as_of < replay_not_before:
            applicability = Applicability.UNSUPPORTED
            reasons.append(
                "Replay time precedes the untouched test period; model selection had access to its future."
            )
        features = self.builder.from_snapshot(snapshot)
        for required in self.manifest["required_inputs"]:
            spec = next(
                item
                for item in self.feature_config.series
                if item.signal_id == required["signal_id"]
            )
            if not np.isfinite(features.iloc[0][f"{spec.prefix}__current"]):
                applicability = Applicability.INSUFFICIENT_DATA
                reasons.append(f"Required current input is unavailable: {spec.signal_id}.")
        if applicability is not Applicability.SUPPORTED:
            return self._unavailable(forecast_at, applicability, tuple(reasons))

        if self.selected_predictor == "hist_gradient_boosting":
            prediction = float(self.estimator.predict(features.loc[:, self.active_features])[0])
        elif self.selected_predictor == "persistence_baseline":
            target_spec = next(
                item
                for item in self.feature_config.series
                if item.signal_id == self.feature_config.target_signal_id
            )
            prediction = float(features.iloc[0][f"{target_spec.prefix}__current"])
        else:
            raise ValueError(f"unknown selected predictor {self.selected_predictor!r}")
        prediction = max(0.0, prediction)
        radius = float(self.manifest["uncertainty"]["radius_mg_per_kg"])
        return QualityAssessment(
            target=self.manifest["output_target"],
            forecast_at=forecast_at,
            prediction=prediction,
            unit=self.manifest["target_unit"],
            lower=max(0.0, prediction - radius),
            upper=prediction + radius,
            interval_coverage_target=float(self.manifest["uncertainty"]["quantile"]),
            applicability=Applicability.SUPPORTED,
            reasons=(
                "Continuation forecast for unchanged settings; observational history, not a causal intervention estimate.",
                f"Predictor={self.selected_predictor}; interval is an empirical validation-residual band.",
            ),
            model_version=self.model_version,
        )

    def _unavailable(
        self, forecast_at: datetime, applicability: Applicability, reasons: tuple[str, ...]
    ) -> QualityAssessment:
        return QualityAssessment(
            target=self.manifest["output_target"],
            forecast_at=forecast_at,
            prediction=None,
            unit=self.manifest["target_unit"],
            lower=None,
            upper=None,
            interval_coverage_target=None,
            applicability=applicability,
            reasons=reasons,
            model_version=self.model_version,
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
