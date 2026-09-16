"""Versioned, fail-closed readiness audit for counterfactual action assessment."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from neftecode_hackathon.contracts import Action


def build_action_support_audit(
    model_config: Mapping[str, Any],
    data_dictionary: Mapping[str, Any],
    telemetry: pd.DataFrame,
    *,
    train_end: pd.Timestamp,
    selected_predictor: str,
) -> dict[str, Any]:
    """Describe why action effects are supported or blocked using train-only evidence."""

    config = model_config["action_assessment"]
    hold_minutes = int(config["hold_minutes"])
    sample_minutes = int(config["sample_interval_minutes"])
    if hold_minutes <= 0 or sample_minutes <= 0 or hold_minutes % sample_minutes:
        raise ValueError("action hold must be a positive multiple of the sample interval")
    controls = tuple(str(value) for value in config["controls"])
    if not controls or len(set(controls)) != len(controls):
        raise ValueError("action controls must be a non-empty unique list")

    dictionary = {item["signal_id"]: item for item in data_dictionary["fields"]}
    frame = telemetry.copy()
    frame["measured_at"] = pd.to_datetime(frame["measured_at"], utc=True)
    train_end = pd.Timestamp(train_end)
    if train_end.tzinfo is None:
        raise ValueError("action-support train_end must include timezone")
    frame = frame.loc[
        (frame["measured_at"] <= train_end)
        & (frame["quality"] == "valid")
        & np.isfinite(frame["value"])
    ]

    results = []
    for signal_id in controls:
        field = dictionary.get(signal_id)
        if field is None:
            raise ValueError(f"control is absent from the data dictionary: {signal_id}")
        records = frame.loc[frame["signal_id"] == signal_id].sort_values(
            "measured_at", kind="stable"
        )
        verification_status = str(field.get("verification_status") or "")
        unit_verified = bool(field.get("canonical_unit")) and (
            verification_status.startswith("source_verified")
            or verification_status == "organizer_confirmed_unit_correction"
        )
        blockers = []
        if not unit_verified:
            blockers.append(
                {
                    "code": "unit_scale_unverified",
                    "message": "Canonical numerical unit/scale is not verified from the supplied sources.",
                }
            )
        blockers.extend(
            (
                {
                    "code": "held_setting_episodes_unvalidated",
                    "message": "No physically justified tolerance separates a held setting from measurement noise.",
                },
                {
                    "code": "joint_support_not_calibrated",
                    "message": "Train-neighbour joint-support k and threshold cannot be calibrated in physical coordinates.",
                },
                {
                    "code": "transition_not_assessed",
                    "message": "Transition dynamics and safety of reaching the requested value are not assessed.",
                },
            )
        )
        if selected_predictor == "persistence_baseline":
            blockers.append(
                {
                    "code": "predictor_has_no_action_response",
                    "message": "The selected persistence predictor is invariant to control changes.",
                }
            )
        results.append(
            {
                "signal_id": signal_id,
                "description": field.get("description"),
                "mapping_verification_status": field.get("verification_status"),
                "source_unit": field.get("original_unit"),
                "canonical_unit": field.get("canonical_unit"),
                "unit_verified": unit_verified,
                "train_raw_audit": _raw_train_audit(
                    records, hold_minutes=hold_minutes, sample_minutes=sample_minutes
                ),
                "supported": False,
                "blockers": blockers,
            }
        )

    return {
        "schema_version": 1,
        "status": "blocked",
        "effect_basis": "unavailable",
        "causal_claim": False,
        "hold_assumption": (
            f"Requested absolute values would be held for {hold_minutes} minutes; "
            "this assumption is not validated by the supplied observations."
        ),
        "hold_assumption_validated": False,
        "controls": results,
        "joint_support": {
            "calibrated": False,
            "space": "physical control coordinates",
            "scaler_fit": None,
            "k_neighbors": None,
            "leave_one_out_threshold": None,
            "reason": "Physical units/scales and held-setting episodes are not verified.",
        },
        "counterfactual_uncertainty": {
            "calibrated": False,
            "interval_coverage_target": None,
            "reason": "Continuation residuals cannot be transferred to intervention effects.",
        },
        "transition": {
            "assessed": False,
            "reason": "No transition-response model or verified transition safety checks are available.",
        },
    }


def action_rejection_reasons(action: Action, audit: Mapping[str, Any]) -> tuple[str, ...]:
    """Return stable, content-based refusal reasons for a non-empty action."""

    if not action.changes:
        return ()
    controls = {item["signal_id"]: item for item in audit.get("controls", ())}
    reasons: list[str] = []
    for signal_id in sorted(action.changes):
        control = controls.get(signal_id)
        if control is None:
            reasons.append(f"Action signal {signal_id} is absent from the model action manifest.")
            continue
        if not control.get("supported", False):
            reasons.extend(
                f"{signal_id}: {blocker['message']}" for blocker in control.get("blockers", ())
            )
    if not audit.get("joint_support", {}).get("calibrated", False):
        reasons.append("Joint train-support distance is not calibrated for actions.")
    if not audit.get("counterfactual_uncertainty", {}).get("calibrated", False):
        reasons.append("Counterfactual effect uncertainty is not calibrated.")
    return tuple(dict.fromkeys(reasons))


def _raw_train_audit(
    records: pd.DataFrame, *, hold_minutes: int, sample_minutes: int
) -> dict[str, Any]:
    if records.empty:
        return {
            "count": 0,
            "minimum": None,
            "q01": None,
            "median": None,
            "q99": None,
            "maximum": None,
            "changed_step_fraction": None,
            "exact_hold_count": 0,
            "exact_hold_fraction": None,
            "unit": None,
        }
    records = records.reset_index(drop=True)
    values = records["value"].astype(float)
    exact_hold = np.ones(len(records), dtype=bool)
    steps = hold_minutes // sample_minutes
    for offset in range(1, steps + 1):
        expected_time = records["measured_at"] + pd.Timedelta(minutes=sample_minutes * offset)
        exact_hold &= (records["measured_at"].shift(-offset) == expected_time).fillna(
            False
        ).to_numpy() & (values.shift(-offset) == values).fillna(False).to_numpy()
    comparable_steps = max(len(values) - 1, 0)
    changed = int(values.diff().iloc[1:].ne(0).sum()) if comparable_steps else 0
    return {
        "count": len(records),
        "minimum": float(values.min()),
        "q01": float(values.quantile(0.01)),
        "median": float(values.median()),
        "q99": float(values.quantile(0.99)),
        "maximum": float(values.max()),
        "changed_step_fraction": changed / comparable_steps if comparable_steps else None,
        "exact_hold_count": int(exact_hold.sum()),
        "exact_hold_fraction": float(exact_hold.mean()),
        "exact_hold_definition": (
            f"All observations at {sample_minutes}-minute steps through +{hold_minutes} minutes "
            "are exactly equal; diagnostic only because no physical noise tolerance is verified."
        ),
        "unit": None,
    }
