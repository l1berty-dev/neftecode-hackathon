"""Static endpoint severity proxy; never a safety or intervention forecast."""

from typing import TYPE_CHECKING

from neftecode_hackathon.contracts import (
    Action,
    ProcessSnapshot,
    ReliabilityAssessment,
    ReliabilityFactor,
)

if TYPE_CHECKING:
    from neftecode_hackathon.scenarios.config import SeverityPolicy


class SeverityProxyAgent:
    def __init__(self, policy: SeverityPolicy | None = None) -> None:
        # Deferred import keeps the reliability protocol independent of evaluator imports.
        from neftecode_hackathon.scenarios.config import SeverityPolicy, load_severity_policy

        self.policy = SeverityPolicy.model_validate((policy or load_severity_policy()).model_dump())

    def assess(self, snapshot: ProcessSnapshot, action: Action) -> ReliabilityAssessment:
        from neftecode_hackathon.scenarios.checks import measurement_check
        from neftecode_hackathon.scenarios.config import SeverityPolicy

        snapshot = ProcessSnapshot.model_validate(snapshot.model_dump())
        action = Action.model_validate(action.model_dump())
        policy = SeverityPolicy.model_validate(self.policy.model_dump())
        limitations = [
            f"severity policy={policy.version}; фиксированные веса — модельное допущение.",
            "Статический индекс тяжести, не вероятность аварии, не ресурс катализатора и не гарантия безопасности.",
            "Предложенные значения описывают конечные настройки, не прогноз достижения режима.",
            "Безопасность и динамика перехода не оценены; transition_assessed=false.",
        ]
        factors = []
        complete = True
        unknown = set(action.changes) - {f.signal_id for f in policy.factors}
        if unknown:
            complete = False
            limitations.append("Неизвестные изменения для proxy: " + ", ".join(sorted(unknown)))
        for factor in policy.factors:
            source = factor.provenance
            if (
                not factor.unit_verified
                or factor.minimum is None
                or source is None
                or source.available_at > snapshot.as_of
                or (source.kind == "train" and source.dataset_version != snapshot.dataset_version)
            ):
                complete = False
                raw = snapshot.values.get(factor.signal_id)
                limitations.append(
                    f"{factor.signal_id}: единица/нормировка не подтверждена или недоступна на время snapshot. "
                    f"raw_current={raw.value if raw else None}, raw_unit={raw.unit if raw else None}; "
                    f"requested_absolute={action.changes.get(factor.signal_id)}; "
                    f"z=(x-min)/(max-min), weight={factor.weight:.12g}; contribution=null. "
                    + factor.equipment_relation
                )
                continue
            result = measurement_check(
                snapshot,
                factor.signal_id,
                factor.unit,
                factor.max_age_seconds,
                code="severity.input",
            ).result
            if result.passed is not True:
                complete = False
                limitations.append(result.message)
                continue
            current = snapshot.values[factor.signal_id].value
            scenario = action.changes.get(factor.signal_id, current)
            if not (
                factor.minimum <= current <= factor.maximum
                and factor.minimum <= scenario <= factor.maximum
            ):
                complete = False
                limitations.append(
                    f"{factor.signal_id}: вне нормировки; экстраполяция и clipping запрещены."
                )
                continue
            current_z = (current - factor.minimum) / (factor.maximum - factor.minimum)
            scenario_z = (scenario - factor.minimum) / (factor.maximum - factor.minimum)
            contribution = factor.weight * scenario_z
            factors.append(
                ReliabilityFactor(
                    name=factor.name,
                    contribution=contribution,
                    explanation=(
                        f"{factor.signal_id}: current={current:g}, scenario={scenario:g} {factor.unit}; "
                        f"z=(x-{factor.minimum:g})/({factor.maximum:g}-{factor.minimum:g}); "
                        f"current_z={current_z:.12g}, scenario_z={scenario_z:.12g}; "
                        f"weight={factor.weight:.12g}; current_contribution={factor.weight * current_z:.12g}; "
                        f"scenario_contribution={contribution:.12g}. "
                        f"normalization={source.model_dump(mode='json')}; evidence={factor.evidence}. "
                        + factor.equipment_relation
                    ),
                )
            )
        if not complete:
            limitations.append(
                "Итоговый индекс неизвестен: частичные вклады не суммируются в полный индекс."
            )
        return ReliabilityAssessment(
            severity_index=sum(f.contribution for f in factors) if complete else None,
            factors=tuple(factors),
            transition_assessed=False,
            limitations=tuple(limitations),
        )
