"""E explanations and trace use computed synthetic facts, never invented outcomes."""

from uuid import uuid4

import pytest
from test_candidate_ranking import evaluator_for, metric, ranking
from test_scenario_checks import TestQualityAgent
from test_scenario_checks import setup as setup

from neftecode_hackathon.contracts import (
    Action,
    ActionOrigin,
    Applicability,
    Decision,
    DecisionStatus,
    ProcessSnapshot,
)
from neftecode_hackathon.orchestration import Coordinator
from neftecode_hackathon.orchestration.explanation import action_facts, evaluation_facts
from neftecode_hackathon.reliability import UnavailableReliabilityAgent
from neftecode_hackathon.scenarios import ScenarioEvaluator
from neftecode_hackathon.scenarios.config import ScenarioPolicy


def synthetic_example(setup):
    for control in setup[2]["catalogue"]["controls"][1:]:
        control.update(available=False, unavailable_reason="synthetic disabled")

    class SyntheticEffectEvaluator(ScenarioEvaluator):
        def evaluate(self, snapshot, action, horizon_minutes=60):
            result = super().evaluate(snapshot, action, horizon_minutes)
            throughput = 105.0 if action.changes == {"ht:P8": 155.0} else 100.0
            return result.model_copy(update={"throughput": metric(throughput)})

    evaluator = SyntheticEffectEvaluator(
        TestQualityAgent(setup[0].evaluation.quality),
        UnavailableReliabilityAgent(),
        model_version=setup[0].evaluation.model_version,
        policy=ScenarioPolicy.model_validate(setup[2]),
    )
    operator = Action(
        action_id=uuid4(),
        origin=ActionOrigin.OPERATOR,
        label="synthetic operator",
        changes={"ht:P8": 155.0},
    )
    snapshot = ProcessSnapshot.model_validate(setup[1])
    return Coordinator(evaluator, ranking_policy=ranking(setup)).decide(snapshot, operator)


def test_synthetic_operator_example_has_exact_facts_and_selection_reason(setup):
    decision = synthetic_example(setup)
    text = "\n".join(decision.explanation)
    assert decision.status is DecisionStatus.CHANGE_RECOMMENDED
    for fact in (
        "150.0 → 155.0",
        "synthetic-C",
        "age_seconds=",
        "measured_at=",
        "available_at=",
        "Сера: прогноз=7.8",
        "интервал=[6.1, 9.5] mg/kg",
        "coverage_target=0.9",
        "Будущий выпуск: 105.0 (synthetic-t/h); basis=predicted",
        "Будущие затраты: не оценено",
        "basis=unavailable",
        "transition_assessed=false",
        "Основание выбора: throughput; baseline=100.0, preferred=105.0",
        "tolerance=1.0",
        "quality.sulfur_upper: пройдена",
        "replay",
    ):
        assert fact in text
    assert "экономия 0" not in text
    assert "не доказывает эффект вмешательства" in text
    assert Decision.model_validate_json(decision.model_dump_json()) == decision
    # Repeated unknown facts must remain visible for every scenario, not globally deduplicated.
    assert text.count("Будущие затраты: не оценено") == 4


def test_trace_references_all_actual_calls_and_selection_outputs(setup):
    decision = synthetic_example(setup)
    roles = [entry.role for entry in decision.trace]
    assert roles == [
        "snapshot_validation",
        "scenario_evaluator",
        "candidate_generation",
        "scenario_evaluator",
        "scenario_evaluator",
        "scenario_evaluator",
        "selection",
    ]
    calls = [entry for entry in decision.trace if entry.role == "scenario_evaluator"]
    assert len(calls) == 4
    assert len({entry.input_ids[1] for entry in calls}) == 4
    assert all(entry.input_ids[0] == decision.snapshot_id for entry in calls)
    selection = decision.trace[-1]
    assert len(selection.input_ids) == 4
    for evaluation_id in selection.input_ids:
        assert any(f"evaluation_id={evaluation_id}" in entry.output_summary for entry in calls)
    for evaluation in (decision.baseline, decision.preferred, *decision.alternatives):
        assert evaluation.evaluation_id in selection.input_ids
        call = next(entry for entry in calls if entry.input_ids[1] == evaluation.action.action_id)
        assert set(call.check_codes) == {check.code for check in evaluation.checks}
    assert f"preferred_evaluation_id={decision.preferred.evaluation_id}" in selection.output_summary
    assert "Основание выбора: throughput" in selection.output_summary
    assert "Системные candidates=3" in decision.trace[2].output_summary
    assert all(
        entry.role not in ("quality_agent", "reliability_agent", "llm") for entry in decision.trace
    )


def test_no_change_is_explained_without_inventing_benefit(setup):
    decision = Coordinator(evaluator_for(setup)).decide(ProcessSnapshot.model_validate(setup[1]))
    text = "\n".join(decision.explanation)
    assert decision.status is DecisionStatus.NO_CHANGE
    assert decision.preferred == decision.baseline
    assert "доказуемого преимущества изменения нет" in text
    assert "сравнение пропущено" in text
    assert "Сохранить настройки; процесс продолжает изменяться" in text
    assert "Основание выбора:" not in text


@pytest.mark.parametrize("insufficient", [False, True])
def test_refusal_explains_actual_failed_and_unknown_checks(setup, insufficient):
    evaluator = evaluator_for(setup)
    raw = setup[2]
    if insufficient:
        raw["constraints"]["required_inputs"].append(
            dict(signal_id="ht:missing", unit="synthetic", max_age_seconds=1200)
        )
    else:
        raw["constraints"].update(
            hard_check_inventory_verified=False, hard_check_inventory_evidence=None
        )
    evaluator = ScenarioEvaluator(
        evaluator.quality_agent,
        evaluator.reliability_agent,
        model_version=evaluator.model_version,
        policy=ScenarioPolicy.model_validate(raw),
    )
    decision = Coordinator(evaluator).decide(ProcessSnapshot.model_validate(setup[1]))
    assert decision.status is (
        DecisionStatus.INSUFFICIENT_DATA if insufficient else DecisionStatus.NO_FEASIBLE_OPTION
    )
    assert decision.preferred is None
    text = "\n".join(decision.explanation)
    assert "Совет не сформирован" in text
    assert "не оценена" in text
    assert "Основание выбора:" not in text
    assert all(e.admissibility.value == "not_assessable" for e in decision.rejected_evaluations)
    if insufficient:
        assert "Сера: не оценено; applicability=insufficient_data" in text
        assert "Сера: прогноз=" not in text
        assert evaluator.quality_agent.calls == []
    else:
        assert "reliability.hard_checks: не оценена" in text


def test_repair_does_not_claim_economic_advantage_or_transition_safety(setup):
    quality = setup[0].evaluation.quality

    class SyntheticQuality:
        def assess(self, snapshot, action, horizon_minutes):
            return quality if action.changes else quality.model_copy(update={"upper": 12.0})

    evaluator = ScenarioEvaluator(
        SyntheticQuality(),
        UnavailableReliabilityAgent(),
        model_version=quality.model_version,
        policy=ScenarioPolicy.model_validate(setup[2]),
    )
    decision = Coordinator(evaluator).decide(ProcessSnapshot.model_validate(setup[1]))
    assert decision.status is DecisionStatus.CHANGE_RECOMMENDED
    assert decision.baseline in decision.rejected_evaluations
    text = "\n".join(decision.explanation)
    assert "Baseline: rejected" in text
    assert "quality.sulfur_upper: нарушена" in text
    assert "не аварийная инструкция" in text
    assert "Будущие затраты: не оценено" in text
    assert "не доказывает эффект вмешательства" in text


def test_unverified_control_unit_is_not_inferred_from_raw_measurement(setup):
    raw = setup[2]
    raw["catalogue"]["controls"][0].update(
        available=False,
        unavailable_reason="synthetic unverified",
        unit_verified=False,
        canonical_unit=None,
    )
    policy = ScenarioPolicy.model_validate(raw)
    action = Action(
        action_id=uuid4(), origin=ActionOrigin.OPERATOR, label="unused", changes={"ht:P8": 155.0}
    )
    facts = " ".join(action_facts(ProcessSnapshot.model_validate(setup[1]), action, policy))
    assert "численная единица/шкала не подтверждена" in facts
    assert "raw_unit=synthetic-C" in facts


def test_unsupported_quality_has_no_numeric_forecast_in_explanation(setup):
    result = evaluator_for(setup).evaluate(
        ProcessSnapshot.model_validate(setup[1]),
        Action(
            action_id=uuid4(),
            origin=ActionOrigin.OPERATOR,
            label="synthetic",
            changes={"ht:P8": 999.0},
        ),
    )
    text = " ".join(evaluation_facts(result))
    assert result.quality.applicability is Applicability.UNSUPPORTED
    assert "Сера: не оценено" in text
    assert "Сера: прогноз=" not in text


def test_agent_mutations_do_not_change_snapshot_or_operator_payload(setup):
    class MutatingSyntheticQuality:
        def assess(self, snapshot, action, horizon_minutes):
            snapshot.values["ht:P8"] = snapshot.values["ht:P8"].model_copy(update={"value": 999.0})
            action.changes["ht:P8"] = 999.0
            return setup[0].evaluation.quality

    evaluator = ScenarioEvaluator(
        MutatingSyntheticQuality(),
        UnavailableReliabilityAgent(),
        model_version=setup[0].evaluation.model_version,
        policy=ScenarioPolicy.model_validate(setup[2]),
    )
    snapshot = ProcessSnapshot.model_validate(setup[1])
    before = snapshot.model_dump()
    operator = Action(
        action_id=uuid4(), origin=ActionOrigin.OPERATOR, label="unused", changes={"ht:P8": 155.0}
    )
    Coordinator(evaluator).decide(snapshot, operator)
    assert snapshot.model_dump() == before
    assert operator.changes == {"ht:P8": 155.0}
