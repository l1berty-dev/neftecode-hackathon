"""Handoff-A integration uses synthetic agents only within tests."""

from pathlib import Path
from uuid import uuid4

import pytest

from neftecode_hackathon.contracts import (
    ActionOrigin,
    Admissibility,
    Applicability,
    ContractExample,
    Decision,
    DecisionStatus,
)
from neftecode_hackathon.orchestration import Coordinator
from neftecode_hackathon.reliability import UnavailableReliabilityAgent
from neftecode_hackathon.scenarios import ScenarioEvaluator
from neftecode_hackathon.scenarios.config import ScenarioPolicy, load_policy


@pytest.fixture
def example():
    return ContractExample.model_validate_json(
        Path("examples/contract_v1.synthetic.json").read_text()
    )


class SyntheticQualityAgent:
    def __init__(self, quality):
        self.quality = quality
        self.calls = 0

    def assess(self, snapshot, action, horizon_minutes):
        self.calls += 1
        return self.quality


def make_evaluator(example, quality=None):
    agent = SyntheticQualityAgent(quality or example.evaluation.quality)
    raw_policy = load_policy().model_dump()
    raw_policy["constraints"].update(
        model_inputs_verified=True,
        model_version=agent.quality.model_version,
        required_inputs=[
            dict(signal_id="pak:ht.product_sulfur", unit="mg/kg", max_age_seconds=1200)
        ],
        minimum_interval_coverage=0.9,
    )
    evaluator = ScenarioEvaluator(
        agent,
        UnavailableReliabilityAgent(),
        model_version=agent.quality.model_version,
        policy=ScenarioPolicy.model_validate(raw_policy),
    )
    return evaluator, agent


def test_fixture_full_cycle_and_roundtrip(example):
    evaluator, agent = make_evaluator(example)
    before = example.snapshot.model_dump_json()
    decision = Coordinator(evaluator).decide(example.snapshot, example.action)
    assert Decision.model_validate_json(decision.model_dump_json()) == decision
    assert decision.baseline.action.changes == {}
    assert decision.status is DecisionStatus.NO_FEASIBLE_OPTION
    assert decision.preferred is None
    assert agent.calls == 1  # unverified operator/system change never reaches model
    assert example.snapshot.model_dump_json() == before
    assert decision.baseline.cost.value is None
    assert decision.baseline.throughput.value is None
    assert decision.baseline.reliability.transition_assessed is False
    assert len([entry for entry in decision.trace if entry.role == "scenario_evaluator"]) == 2


@pytest.mark.parametrize("changes", [{}, {"ht:F26": 252.0}, {"ht:unknown": 1.0}])
def test_equal_action_independent_of_origin_and_label(example, changes):
    evaluator, _ = make_evaluator(example)
    a = example.action.model_copy(update={"changes": changes})
    b = a.model_copy(
        update={
            "action_id": uuid4(),
            "origin": ActionOrigin.OPERATOR,
            "label": "Operator",
        }
    )
    left = evaluator.evaluate(example.snapshot, a)
    right = evaluator.evaluate(example.snapshot, b)
    assert left.model_dump(exclude={"evaluation_id", "action"}) == right.model_dump(
        exclude={"evaluation_id", "action"}
    )


def test_baseline_quality_failure_never_becomes_no_change(example):
    quality = example.evaluation.quality.model_copy(update={"upper": 12.0})
    evaluator, _ = make_evaluator(example, quality)
    decision = Coordinator(evaluator).decide(example.snapshot)
    assert decision.baseline.admissibility is Admissibility.REJECTED
    assert decision.status is DecisionStatus.NO_FEASIBLE_OPTION
    assert decision.preferred is None


def test_insufficient_data_has_no_forecast(example):
    quality = example.evaluation.quality.model_copy(
        update={
            "prediction": None,
            "lower": None,
            "upper": None,
            "applicability": Applicability.INSUFFICIENT_DATA,
            "reasons": ("Missing inputs",),
        }
    )
    evaluator, _ = make_evaluator(example, quality)
    decision = Coordinator(evaluator).decide(example.snapshot)
    assert decision.status is DecisionStatus.INSUFFICIENT_DATA
    assert decision.baseline.quality.prediction is None
    assert decision.baseline.admissibility is Admissibility.NOT_ASSESSABLE


def test_unknown_required_check_blocks_baseline(example):
    evaluator, _ = make_evaluator(example)
    baseline = example.action.model_copy(update={"changes": {}})
    evaluation = evaluator.evaluate(example.snapshot, baseline)
    assert evaluation.admissibility is Admissibility.NOT_ASSESSABLE
    assert any(c.passed is None for c in evaluation.checks)


@pytest.mark.parametrize(
    "field,value",
    [
        ("model_version", "wrong"),
        ("unit", "ppm"),
        ("target", "wrong"),
    ],
)
def test_quality_contract_mismatch_not_admissible(example, field, value):
    evaluator, agent = make_evaluator(example)
    agent.quality = agent.quality.model_copy(update={field: value})
    baseline = example.action.model_copy(update={"changes": {}})
    if field == "model_version":
        with pytest.raises(ValueError):
            evaluator.evaluate(example.snapshot, baseline)
    else:
        assert (
            evaluator.evaluate(example.snapshot, baseline).admissibility is Admissibility.REJECTED
        )


def test_unsupported_horizon_does_not_call_model(example):
    evaluator, agent = make_evaluator(example)
    with pytest.raises(ValueError):
        evaluator.evaluate(example.snapshot, example.action, 30)
    assert agent.calls == 0
