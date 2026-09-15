"""Bounded candidate evaluation and deterministic selection on one snapshot."""

from uuid import uuid4

from neftecode_hackathon.contracts import (
    Action,
    Decision,
    ProcessSnapshot,
    TraceEntry,
)
from neftecode_hackathon.optimization.candidates import (
    action_key,
    baseline_action,
    generate_candidates,
)
from neftecode_hackathon.optimization.ranking import select_evaluations
from neftecode_hackathon.orchestration.explanation import build_explanation, evaluation_trace
from neftecode_hackathon.scenarios import ScenarioEvaluator
from neftecode_hackathon.scenarios.config import RankingPolicy, ScenarioPolicy, load_ranking_policy


class Coordinator:
    def __init__(
        self, evaluator: ScenarioEvaluator, *, ranking_policy: RankingPolicy | None = None
    ) -> None:
        self.evaluator = evaluator
        self.ranking_policy = RankingPolicy.model_validate(
            (ranking_policy or load_ranking_policy()).model_dump()
        )

    def decide(
        self,
        snapshot: ProcessSnapshot,
        operator_action: Action | None = None,
        horizon_minutes: int = 60,
    ) -> Decision:
        snapshot = ProcessSnapshot.model_validate(snapshot.model_dump())
        policy = ScenarioPolicy.model_validate(self.evaluator.policy.model_dump())
        ranking_policy = RankingPolicy.model_validate(self.ranking_policy.model_dump())
        baseline = self.evaluator.evaluate(snapshot, baseline_action(snapshot), horizon_minutes)
        actions = list(generate_candidates(snapshot, policy))
        system_count = len(actions)
        replaced = 0
        if operator_action is not None:
            operator_action = Action.model_validate(operator_action.model_dump())
            # Replace an identical non-baseline system action, without changing operator payload.
            replaced = sum(
                bool(a.changes) and action_key(a) == action_key(operator_action) for a in actions
            )
            actions = [
                a for a in actions if not a.changes or action_key(a) != action_key(operator_action)
            ]
            actions.append(operator_action)
        evaluations = (
            baseline,
            *(self.evaluator.evaluate(snapshot, a, horizon_minutes) for a in actions[1:]),
        )
        status, preferred, alternatives, rejected, explanations = select_evaluations(
            snapshot,
            evaluations,
            policy,
            ranking_policy,
        )
        return Decision(
            decision_id=uuid4(),
            snapshot_id=snapshot.snapshot_id,
            horizon_minutes=horizon_minutes,
            status=status,
            baseline=evaluations[0],
            preferred=preferred,
            alternatives=alternatives,
            rejected_evaluations=rejected,
            explanation=build_explanation(
                snapshot, status, evaluations, preferred, alternatives, explanations, policy
            ),
            trace=(
                TraceEntry(
                    role="snapshot_validation",
                    input_ids=(snapshot.snapshot_id,),
                    output_summary=f"Snapshot/конфигурация валидированы; as_of={snapshot.as_of.isoformat()}; mode={snapshot.mode.value}; completeness={snapshot.completeness}; dataset={snapshot.dataset_version}; model={self.evaluator.model_version}; constraints={policy.constraints.constraint_version}; ranking={ranking_policy.version}; issues={snapshot.issues}.",
                ),
                evaluation_trace(snapshot, baseline),
                TraceEntry(
                    role="candidate_generation",
                    input_ids=(snapshot.snapshot_id,),
                    output_summary=f"Системные candidates={system_count}; после включения оператора={len(actions)}; заменено дублей={replaced}; action_ids={[str(a.action_id) for a in actions]}; baseline сохранён.",
                ),
                *(evaluation_trace(snapshot, e) for e in evaluations[1:]),
                TraceEntry(
                    role="selection",
                    input_ids=tuple(e.evaluation_id for e in evaluations),
                    output_summary=f"status={status.value}; preferred_evaluation_id={preferred.evaluation_id if preferred else None}; alternative_ids={[str(e.evaluation_id) for e in alternatives]}; rejected_ids={[str(e.evaluation_id) for e in rejected]}. "
                    + " ".join(explanations),
                ),
            ),
            dataset_version=snapshot.dataset_version,
            model_version=self.evaluator.model_version,
            constraint_version=self.evaluator.constraint_version,
        )
