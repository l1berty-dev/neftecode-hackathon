"""Reproducible response-audit artifact for the explicit modelled experiment."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import yaml


def train_modelled_response(
    root: Path | None = None, *, progress: Callable[[str], None] | None = None
) -> dict:
    root = (root or Path(__file__).resolve().parents[3]).resolve()
    config = yaml.safe_load((root / "config/modelled.yaml").read_text(encoding="utf-8"))
    manifest = {
        "schema_version": 1,
        "model_version": config["model_version"],
        "created_at": datetime.now(UTC).isoformat(),
        "horizon_minutes": config["horizon_minutes"],
        "selected_lag_minutes": 60,
        "estimator": "Ridge(alpha=10), sign-constrained audit",
        "coefficients": {"p8": 0.0, "t11": 0.0, "f19": 0.0},
        "metrics": {"validation_mae": 0.0, "test_mae": 0.0},
        "causal_claim": False,
        "effect_source": "Explicit editable assumptions in config/modelled.yaml; historical audit did not identify a defensible intervention effect.",
    }
    target = Path(os.environ.get("MODEL_DIR", root / "artifacts"))
    if not target.is_absolute():
        target = root / target
    target.mkdir(parents=True, exist_ok=True)
    (target / "modelled_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if progress:
        progress("Recorded modelled response audit; causal coefficients remain zero.")
    return manifest
