"""C arithmetic fixtures are synthetic; no industrial normalization is claimed."""

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from neftecode_hackathon.contracts import (
    Action,
    ActionOrigin,
    ContractExample,
    EstimateBasis,
    ProcessSnapshot,
)
from neftecode_hackathon.reliability import SeverityProxyAgent
from neftecode_hackathon.scenarios.config import (
    SeverityPolicy,
    ThroughputPolicy,
    load_severity_policy,
)
from neftecode_hackathon.scenarios.efficiency import current_throughput, scenario_efficiency


@pytest.fixture
def inputs():
    example = ContractExample.model_validate_json(
        Path("examples/contract_v1.synthetic.json").read_text(encoding="utf-8")
    )
    raw = example.snapshot.model_dump()
    template = next(iter(raw["values"].values())).copy()
    template.update(
        value=50.0,
        unit="synthetic-unit",
        measured_at=example.snapshot.as_of,
        available_at=example.snapshot.as_of,
        age_seconds=0.0,
        quality="valid",
        issues=(),
    )
    raw["values"] = {signal: template.copy() for signal in ("ht:P8", "ht:T11", "ht:F19", "ht:F17")}
    policy = load_severity_policy().model_dump()
    for factor in policy["factors"]:
        factor.update(
            unit="synthetic-unit",
            unit_verified=True,
            minimum=0.0,
            maximum=100.0,
            provenance=dict(
                kind="train",
                source="synthetic train only",
                available_at=example.snapshot.as_of - timedelta(days=1),
                train_end=example.snapshot.as_of - timedelta(days=2),
                dataset_version=example.snapshot.dataset_version,
            ),
        )
    return raw, policy


def action(changes=None, origin=ActionOrigin.OPERATOR):
    return Action(action_id=uuid4(), origin=origin, label="synthetic", changes=changes or {})


def test_static_factors_are_auditable_and_input_is_unchanged(inputs):
    raw, policy = inputs
    snapshot = ProcessSnapshot.model_validate(raw)
    before = snapshot.model_dump()
    agent = SeverityProxyAgent(SeverityPolicy.model_validate(policy))
    baseline = agent.assess(snapshot, action())
    changed = agent.assess(snapshot, action({"ht:P8": 80.0}))
    assert baseline.severity_index == pytest.approx(0.5)
    assert changed.severity_index == pytest.approx(0.6)
    assert len(changed.factors) == 3
    factor = changed.factors[0]
    assert factor.contribution == pytest.approx(0.8 / 3)
    for marker in (
        "current=50",
        "scenario=80",
        "current_z=0.5",
        "scenario_z=0.8",
        "current_contribution=",
        "normalization=",
        "synthetic train only",
    ):
        assert marker in factor.explanation
    assert not changed.transition_assessed
    assert snapshot.model_dump() == before
    assert agent.assess(snapshot, action({"ht:P8": 80.0}, ActionOrigin.SYSTEM)) == changed


@pytest.mark.parametrize("value,expected", [(0.0, 0.0), (100.0, 1.0)])
def test_normalization_boundaries(inputs, value, expected):
    raw, policy = inputs
    for measurement in raw["values"].values():
        measurement["value"] = value
    result = SeverityProxyAgent(SeverityPolicy.model_validate(policy)).assess(
        ProcessSnapshot.model_validate(raw), action()
    )
    assert result.severity_index == pytest.approx(expected)


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "unit",
        "suspect",
        "stale",
        "future",
        "age",
        "future_policy",
        "dataset",
        "unverified",
        "range",
        "unknown_action",
    ],
)
def test_unknown_factor_never_becomes_partial_index(inputs, fault):
    raw, policy = inputs
    measurement = raw["values"]["ht:P8"]
    factor = policy["factors"][0]
    changes = {}
    if fault == "missing":
        del raw["values"]["ht:P8"]
    elif fault == "unit":
        measurement["unit"] = "wrong"
    elif fault == "suspect":
        measurement["quality"] = "suspect"
    elif fault == "stale":
        measurement["measured_at"] -= timedelta(hours=1)
        measurement["age_seconds"] = 3600.0
    elif fault == "future":
        measurement["available_at"] += timedelta(seconds=1)
    elif fault == "age":
        measurement["age_seconds"] = 100.0
    elif fault == "future_policy":
        factor["provenance"]["available_at"] = raw["as_of"] + timedelta(seconds=1)
    elif fault == "dataset":
        factor["provenance"]["dataset_version"] = "other"
    elif fault == "unverified":
        factor["unit_verified"] = False
    elif fault == "range":
        changes = {"ht:P8": 101.0}
    else:
        changes = {"ht:F26": 1.0}
    if fault == "future":
        with pytest.raises(ValidationError, match="future"):
            ProcessSnapshot.model_validate(raw)
        return
    result = SeverityProxyAgent(SeverityPolicy.model_validate(policy)).assess(
        ProcessSnapshot.model_validate(raw), action(changes)
    )
    assert result.severity_index is None
    assert result.limitations
    assert not result.transition_assessed


@pytest.mark.parametrize(
    "fault", ["weights", "duplicate", "bounds", "provenance", "unit", "nan", "naive", "overflow"]
)
def test_invalid_calibration_fails_explicitly(inputs, fault):
    _, policy = inputs
    factor = policy["factors"][0]
    if fault == "weights":
        factor["weight"] = 0.9
    elif fault == "duplicate":
        policy["factors"][1]["signal_id"] = factor["signal_id"]
    elif fault == "bounds":
        factor["maximum"] = factor["minimum"]
    elif fault == "provenance":
        factor["provenance"]["train_end"] = None
    elif fault == "unit":
        factor["unit"] = None
    elif fault == "nan":
        factor["minimum"] = float("nan")
    elif fault == "overflow":
        factor["minimum"], factor["maximum"] = -1e308, 1e308
    else:
        factor["provenance"]["available_at"] = factor["provenance"]["available_at"].replace(
            tzinfo=None
        )
    with pytest.raises(ValidationError):
        SeverityPolicy.model_validate(policy)


def throughput_policy(policy):
    return ThroughputPolicy(
        version="synthetic",
        evidence="synthetic outlet flow",
        unit="synthetic-unit",
        unit_verified=True,
        provenance=policy["factors"][0]["provenance"],
    )


def test_current_flow_is_measured_but_never_a_future_forecast(inputs):
    raw, policy = inputs
    snapshot = ProcessSnapshot.model_validate(raw)
    measured = current_throughput(snapshot, throughput_policy(policy))
    assert measured.value == 50.0
    assert measured.basis is EstimateBasis.MEASURED
    assert "не прогноз" in measured.explanation
    for candidate in (action(), action({"ht:T11": 60.0})):
        future, cost = scenario_efficiency(snapshot, candidate, 60)
        assert future.value is cost.value is None
        assert future.unit is cost.unit is None
        assert future.basis is cost.basis is EstimateBasis.UNAVAILABLE
        assert '"value":null' in future.model_dump_json()
    with pytest.raises(ValueError):
        scenario_efficiency(snapshot, action(), 120)


@pytest.mark.parametrize("fault", ["missing", "negative", "unit", "future", "dataset"])
def test_current_flow_requires_its_own_outlet_measurement(inputs, fault):
    raw, policy = inputs
    if fault == "missing":
        del raw["values"]["ht:F17"]
    elif fault == "negative":
        raw["values"]["ht:F17"]["value"] = -1.0
    elif fault == "unit":
        raw["values"]["ht:F17"]["unit"] = "wrong"
    elif fault == "future":
        raw["values"]["ht:F17"]["available_at"] += timedelta(seconds=1)
    else:
        policy["factors"][0]["provenance"]["dataset_version"] = "other"
    if fault == "future":
        with pytest.raises(ValidationError, match="future"):
            ProcessSnapshot.model_validate(raw)
        return
    result = current_throughput(ProcessSnapshot.model_validate(raw), throughput_policy(policy))
    assert result.value is None
    assert result.basis is EstimateBasis.UNAVAILABLE


def test_repository_defaults_do_not_invent_units_or_calibration(inputs):
    raw, _ = inputs
    snapshot = ProcessSnapshot.model_validate(raw)
    assert SeverityProxyAgent().assess(snapshot, action()).severity_index is None
    assert current_throughput(snapshot).basis is EstimateBasis.UNAVAILABLE
