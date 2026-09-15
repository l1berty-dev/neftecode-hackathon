"""Baseline/operator cycle for handoff A; no unverified candidate generation."""

from uuid import uuid4

from neftecode_hackathon.contracts import (
    Action,
    ActionOrigin,
    Admissibility,
    Applicability,
    Decision,
    DecisionStatus,
    ProcessSnapshot,
    TraceEntry,
)
from neftecode_hackathon.scenarios import ScenarioEvaluator


class Coordinator:
    def __init__(self, evaluator: ScenarioEvaluator) -> None:
        self.evaluator = evaluator

    def decide(
        self,
        snapshot: ProcessSnapshot,
        operator_action: Action | None = None,
        horizon_minutes: int = 60,
    ) -> Decision:
        baseline = Action(
            action_id=uuid4(),
            label="Сохранить настройки",
            origin=ActionOrigin.BASELINE,
            changes={},
        )
        evaluations = [self.evaluator.evaluate(snapshot, baseline, horizon_minutes)]
        if operator_action is not None:
            evaluations.append(self.evaluator.evaluate(snapshot, operator_action, horizon_minutes))
        if any(e.admissibility is Admissibility.ADMISSIBLE for e in evaluations):
            raise NotImplementedError(
                "Ранжирование допустимых вариантов требует этапов C–E; используйте ScenarioEvaluator.evaluate для этапа B"
            )
        status = (
            DecisionStatus.INSUFFICIENT_DATA
            if evaluations[0].quality.applicability is Applicability.INSUFFICIENT_DATA
            else DecisionStatus.NO_FEASIBLE_OPTION
        )
        return Decision(
            decision_id=uuid4(),
            snapshot_id=snapshot.snapshot_id,
            horizon_minutes=horizon_minutes,
            status=status,
            baseline=evaluations[0],
            preferred=None,
            alternatives=(),
            rejected_evaluations=tuple(evaluations),
            explanation=(
                "Подготовительный контур: надёжная рекомендация пока недоступна.",
                *evaluations[0].reasons,
                "Каталог управлений не утверждён; системные изменения не генерируются.",
            ),
            trace=tuple(
                TraceEntry(
                    role="scenario_evaluator",
                    input_ids=(snapshot.snapshot_id, e.action.action_id),
                    output_summary=f"Оценка: {e.admissibility}",
                    check_codes=tuple(c.code for c in e.checks),
                )
                for e in evaluations
            ),
            dataset_version=snapshot.dataset_version,
            model_version=self.evaluator.model_version,
            constraint_version=self.evaluator.constraint_version,
        )
