"""Synthetic stage-D acceptance: no real industrial limits or effect claims."""

from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_scenario_checks import TestQualityAgent
from test_scenario_checks import setup as setup

from neftecode_hackathon.contracts import (
    Action,
    ActionOrigin,
    Admissibility,
    Decision,
    DecisionStatus,
    EstimateBasis,
    MetricEstimate,
    ProcessSnapshot,
)
from neftecode_hackathon.optimization.candidates import generate_candidates
from neftecode_hackathon.optimization.ranking import select_evaluations
from neftecode_hackathon.orchestration import Coordinator
from neftecode_hackathon.reliability import UnavailableReliabilityAgent
from neftecode_hackathon.scenarios import ScenarioEvaluator
from neftecode_hackathon.scenarios.config import RankingPolicy, ScenarioPolicy


def evaluator_for(setup):
    return ScenarioEvaluator(
        TestQualityAgent(setup[0].evaluation.quality),
        UnavailableReliabilityAgent(),
        model_version=setup[0].evaluation.model_version,
        policy=ScenarioPolicy.model_validate(setup[2]),
    )


def evaluate(setup, changes=None):
    return evaluator_for(setup).evaluate(
        ProcessSnapshot.model_validate(setup[1]),
        Action(
            action_id=uuid4(), origin=ActionOrigin.SYSTEM, label="synthetic", changes=changes or {}
        ),
    )


def metric(value, unit="synthetic-t/h", basis=EstimateBasis.PREDICTED):
    return MetricEstimate(value=value, unit=unit, basis=basis, explanation="synthetic effect")


def ranking(setup, metric_name="throughput", threshold=1.0):
    return RankingPolicy(
        version="synthetic-ranking",
        model_version=setup[0].evaluation.model_version,
        tolerances=[
            dict(
                metric=metric_name,
                threshold=threshold,
                unit="1" if metric_name == "severity" else "synthetic-t/h",
                basis="proxy" if metric_name == "severity" else "predicted",
                evidence="synthetic uncertainty tolerance",
                provenance=dict(
                    kind="train",
                    source="synthetic train only",
                    dataset_version=setup[0].snapshot.dataset_version,
                    train_end=setup[0].snapshot.as_of - timedelta(days=2),
                    available_at=setup[0].snapshot.as_of - timedelta(days=1),
                ),
            )
        ],
    )


def select(setup, evaluations, policy=None):
    return select_evaluations(
        ProcessSnapshot.model_validate(setup[1]),
        tuple(evaluations),
        ScenarioPolicy.model_validate(setup[2]),
        policy or ranking(setup),
    )


def test_27_absolute_unique_candidates_and_immutable_snapshot(setup):
    snapshot = ProcessSnapshot.model_validate(setup[1])
    before = snapshot.model_dump()
    policy = ScenarioPolicy.model_validate(setup[2])
    actions = generate_candidates(snapshot, policy)
    assert len(actions) == 27
    assert actions[0].changes == {}
    assert len({tuple(sorted(a.changes.items())) for a in actions}) == 27
    assert {a.changes["ht:T11"] for a in actions if "ht:T11" in a.changes} == {248.0, 252.0}
    assert actions == generate_candidates(snapshot, policy)
    assert snapshot.model_dump() == before


@pytest.mark.parametrize(
    "fault,expected",
    [
        ("boundary", 18),
        ("disabled", 9),
        ("stale", 9),
        ("future", 9),
        ("dataset", 9),
        ("offgrid", 9),
    ],
)
def test_unavailable_choices_not_generated_but_baseline_remains(setup, fault, expected):
    if fault == "boundary":
        setup[1]["values"]["ht:P8"]["value"] = 100.0
    elif fault == "disabled":
        setup[2]["catalogue"]["controls"][0].update(
            available=False, unavailable_reason="synthetic disabled"
        )
    elif fault == "stale":
        setup[1]["values"]["ht:P8"]["measured_at"] -= timedelta(hours=1)
        setup[1]["values"]["ht:P8"]["age_seconds"] += 3600.0
    elif fault == "future":
        setup[2]["catalogue"]["controls"][0]["provenance"]["available_at"] = setup[
            0
        ].snapshot.as_of + timedelta(days=1)
    elif fault == "dataset":
        setup[2]["catalogue"]["controls"][0]["provenance"]["dataset_version"] = "other"
    else:
        setup[1]["values"]["ht:P8"]["value"] = 150.3
    actions = generate_candidates(
        ProcessSnapshot.model_validate(setup[1]), ScenarioPolicy.model_validate(setup[2])
    )
    assert len(actions) == expected
    assert actions[0].changes == {}


@pytest.mark.parametrize(
    "gain,status",
    [
        (0.0, DecisionStatus.NO_CHANGE),
        (1.0, DecisionStatus.NO_CHANGE),
        (1.01, DecisionStatus.CHANGE_RECOMMENDED),
        (-3.0, DecisionStatus.NO_CHANGE),
    ],
)
def test_advantage_must_strictly_exceed_model_tolerance(setup, gain, status):
    baseline = evaluate(setup).model_copy(update={"throughput": metric(100.0)})
    candidate = evaluate(setup, {"ht:P8": 151.0}).model_copy(
        update={"throughput": metric(100.0 + gain)}
    )
    result = select(setup, [baseline, candidate])
    assert result[0] is status
    assert result[1].action.changes == (
        candidate.action.changes if status is DecisionStatus.CHANGE_RECOMMENDED else {}
    )


@pytest.mark.parametrize(
    "fault", ["unknown", "basis", "unit", "tolerance", "model", "future", "dataset"]
)
def test_unknown_or_incomparable_metric_cannot_win(setup, fault):
    baseline = evaluate(setup).model_copy(update={"throughput": metric(100.0)})
    candidate = evaluate(setup, {"ht:P8": 151.0}).model_copy(update={"throughput": metric(200.0)})
    policy = ranking(setup)
    if fault == "unknown":
        candidate = candidate.model_copy(update={"throughput": evaluate(setup).throughput})
    elif fault == "basis":
        candidate = candidate.model_copy(
            update={"throughput": metric(200.0, basis=EstimateBasis.PROXY)}
        )
    elif fault == "unit":
        candidate = candidate.model_copy(update={"throughput": metric(200.0, unit="other")})
    elif fault == "tolerance":
        policy = RankingPolicy(version="synthetic-no-tolerance")
    elif fault == "model":
        policy = policy.model_copy(update={"model_version": "other"})
    else:
        raw = policy.model_dump()
        source = raw["tolerances"][0]["provenance"]
        if fault == "future":
            source["available_at"] = setup[0].snapshot.as_of + timedelta(seconds=1)
        else:
            source["dataset_version"] = "other"
        policy = RankingPolicy.model_validate(raw)
    assert select(setup, [baseline, candidate], policy)[0] is DecisionStatus.NO_CHANGE


def test_unknown_in_third_feasible_variant_disables_dimension_for_all(setup):
    baseline = evaluate(setup).model_copy(update={"throughput": metric(100.0)})
    candidate = evaluate(setup, {"ht:P8": 151.0}).model_copy(update={"throughput": metric(200.0)})
    third = evaluate(setup, {"ht:T11": 252.0})
    assert select(setup, [baseline, candidate, third])[0] is DecisionStatus.NO_CHANGE


def test_lower_severity_can_prove_proxy_advantage(setup):
    baseline = evaluate(setup)
    candidate = evaluate(setup, {"ht:P8": 149.0})
    baseline = baseline.model_copy(
        update={"reliability": baseline.reliability.model_copy(update={"severity_index": 0.8})}
    )
    candidate = candidate.model_copy(
        update={"reliability": candidate.reliability.model_copy(update={"severity_index": 0.6})}
    )
    assert (
        select(setup, [baseline, candidate], ranking(setup, "severity", 0.1))[0]
        is DecisionStatus.CHANGE_RECOMMENDED
    )


def test_significant_loss_in_throughput_cannot_be_offset_by_severity(setup):
    baseline = evaluate(setup).model_copy(update={"throughput": metric(100.0)})
    candidate = evaluate(setup, {"ht:P8": 149.0}).model_copy(update={"throughput": metric(98.0)})
    baseline = baseline.model_copy(
        update={"reliability": baseline.reliability.model_copy(update={"severity_index": 0.8})}
    )
    candidate = candidate.model_copy(
        update={"reliability": candidate.reliability.model_copy(update={"severity_index": 0.1})}
    )
    raw = ranking(setup).model_dump()
    raw["tolerances"] += ranking(setup, "severity", 0.1).model_dump()["tolerances"]
    assert (
        select(setup, [baseline, candidate], RankingPolicy.model_validate(raw))[0]
        is DecisionStatus.NO_CHANGE
    )


def test_lower_quality_prediction_is_not_a_proven_effect_advantage(setup):
    baseline = evaluate(setup)
    candidate = evaluate(setup, {"ht:P8": 149.0})
    candidate = candidate.model_copy(
        update={
            "quality": candidate.quality.model_copy(
                update={"prediction": 3.0, "lower": 2.0, "upper": 4.0}
            )
        }
    )
    assert select(setup, [baseline, candidate])[0] is DecisionStatus.NO_CHANGE


def test_invalid_baseline_is_never_preferred_and_unknown_cost_does_not_block_repair(setup):
    baseline = evaluate(setup).model_copy(
        update={
            "admissibility": Admissibility.REJECTED,
            "reasons": ("synthetic quality violation",),
        }
    )
    first = evaluate(setup, {"ht:P8": 152.0})
    second = evaluate(setup, {"ht:P8": 151.0})
    status, preferred, alternatives, rejected, _ = select(setup, [baseline, first, second])
    assert status is DecisionStatus.CHANGE_RECOMMENDED
    assert preferred.action.changes == second.action.changes
    assert rejected == (baseline,)
    assert len(alternatives) == 1


def test_rejected_and_unknown_candidates_excluded_before_metrics(setup):
    baseline = evaluate(setup)
    invalid = evaluate(setup, {"ht:P8": 999.0}).model_copy(update={"throughput": metric(10000.0)})
    result = select(setup, [baseline, invalid])
    assert result[0] is DecisionStatus.NO_CHANGE
    assert result[2] == ()
    assert result[3] == (invalid,)


def test_cannot_relabel_failed_checks_as_admissible(setup):
    baseline = evaluate(setup)
    invalid = evaluate(setup, {"ht:P8": 999.0}).model_copy(
        update={"admissibility": Admissibility.ADMISSIBLE}
    )
    with pytest.raises(ValueError, match="contradicts"):
        select(setup, [baseline, invalid])


@pytest.mark.parametrize(
    "field,value", [("model_version", "other"), ("snapshot_id", uuid4()), ("horizon_minutes", 30)]
)
def test_inconsistent_cycles_refused(setup, field, value):
    with pytest.raises(ValueError, match="one snapshot"):
        select(
            setup,
            [evaluate(setup), evaluate(setup, {"ht:P8": 151.0}).model_copy(update={field: value})],
        )


def test_deterministic_tie_origin_independent_and_two_distinct_alternatives(setup):
    baseline = evaluate(setup).model_copy(update={"admissibility": Admissibility.REJECTED})
    candidates = [
        evaluate(setup, {"ht:P8": 149.0}),
        evaluate(setup, {"ht:P8": 151.0}),
        evaluate(setup, {"ht:T11": 252.0}),
    ]
    left = select(setup, [baseline, *candidates])
    candidates[0] = candidates[0].model_copy(
        update={
            "action": candidates[0].action.model_copy(
                update={"origin": ActionOrigin.OPERATOR, "label": "operator"}
            )
        }
    )
    right = select(setup, [baseline, *reversed(candidates)])
    assert left[1].action.changes == right[1].action.changes == {"ht:P8": 149.0}
    assert len(right[2]) == 2
    assert len({tuple(sorted(e.action.changes.items())) for e in (right[1], *right[2])}) == 3


def test_operator_payload_is_evaluated_once_and_matches_standalone(setup):
    evaluator = evaluator_for(setup)
    operator = Action(
        action_id=uuid4(), origin=ActionOrigin.OPERATOR, label="operator", changes={"ht:F19": 4.9}
    )
    direct = evaluator.evaluate(ProcessSnapshot.model_validate(setup[1]), operator)
    decision = Coordinator(evaluator).decide(ProcessSnapshot.model_validate(setup[1]), operator)
    assert len([entry for entry in decision.trace if entry.role == "scenario_evaluator"]) == 27
    operator_result = next(
        e for e in decision.alternatives if e.action.action_id == operator.action_id
    )
    assert direct.model_dump(exclude={"evaluation_id"}) == operator_result.model_dump(
        exclude={"evaluation_id"}
    )
    assert Decision.model_validate_json(decision.model_dump_json()) == decision


def test_explicit_noop_not_returned_as_distinct_alternative(setup):
    baseline = evaluate(setup)
    noop = evaluate(setup, {"ht:P8": 150.0})
    result = select(setup, [baseline, noop])
    assert result[0] is DecisionStatus.NO_CHANGE
    assert result[2] == ()


def test_operator_can_win_on_same_effect_path(setup):
    class SyntheticEffectEvaluator(ScenarioEvaluator):
        def evaluate(self, snapshot, action, horizon_minutes=60):
            result = super().evaluate(snapshot, action, horizon_minutes)
            value = 105.0 if action.changes == {"ht:P8": 155.0} else 100.0
            return result.model_copy(update={"throughput": metric(value)})

    evaluator = SyntheticEffectEvaluator(
        TestQualityAgent(setup[0].evaluation.quality),
        UnavailableReliabilityAgent(),
        model_version=setup[0].evaluation.model_version,
        policy=ScenarioPolicy.model_validate(setup[2]),
    )
    operator = Action(
        action_id=uuid4(), origin=ActionOrigin.OPERATOR, label="operator", changes={"ht:P8": 155.0}
    )
    snapshot = ProcessSnapshot.model_validate(setup[1])
    direct = evaluator.evaluate(snapshot, operator)
    decision = Coordinator(evaluator, ranking_policy=ranking(setup)).decide(snapshot, operator)
    assert decision.status is DecisionStatus.CHANGE_RECOMMENDED
    assert decision.preferred.action == operator
    assert decision.preferred.model_dump(exclude={"evaluation_id"}) == direct.model_dump(
        exclude={"evaluation_id"}
    )
    assert len([entry for entry in decision.trace if entry.role == "scenario_evaluator"]) == 28


def test_tolerance_requires_positive_threshold_source_and_model(setup):
    raw = ranking(setup).model_dump()
    raw["tolerances"][0]["threshold"] = 0.0
    with pytest.raises(ValidationError):
        RankingPolicy.model_validate(raw)
    raw = ranking(setup).model_dump()
    raw["model_version"] = None
    with pytest.raises(ValidationError):
        RankingPolicy.model_validate(raw)
