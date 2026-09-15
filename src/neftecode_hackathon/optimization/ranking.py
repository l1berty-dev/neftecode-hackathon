"""Hard feasibility before comparable metrics; no missing-value rewards."""

from datetime import timedelta
from decimal import Decimal

from neftecode_hackathon.contracts import (
    Admissibility,
    Applicability,
    DecisionStatus,
    EstimateBasis,
    ProcessSnapshot,
    ScenarioEvaluation,
)
from neftecode_hackathon.optimization.candidates import action_key
from neftecode_hackathon.scenarios.checks import admissibility, pre_model_checks
from neftecode_hackathon.scenarios.config import RankingPolicy, ScenarioPolicy


def select_evaluations(
    snapshot: ProcessSnapshot,
    evaluations: tuple[ScenarioEvaluation, ...],
    scenario_policy: ScenarioPolicy,
    ranking_policy: RankingPolicy,
):
    """Internal selection tuple, not a second public decision DTO. Baseline is first."""
    snapshot = ProcessSnapshot.model_validate(snapshot.model_dump())
    evaluations = tuple(ScenarioEvaluation.model_validate(e.model_dump()) for e in evaluations)
    scenario_policy = ScenarioPolicy.model_validate(scenario_policy.model_dump())
    ranking_policy = RankingPolicy.model_validate(ranking_policy.model_dump())
    if not evaluations or evaluations[0].action.changes:
        raise ValueError("First evaluation must be baseline")
    baseline = evaluations[0]
    for evaluation in evaluations:
        if (
            evaluation.snapshot_id != snapshot.snapshot_id
            or evaluation.model_version != baseline.model_version
            or evaluation.constraint_version != baseline.constraint_version
            or evaluation.horizon_minutes != baseline.horizon_minutes
            or evaluation.constraint_version != scenario_policy.constraints.constraint_version
            or evaluation.horizon_minutes != scenario_policy.constraints.horizon_minutes
        ):
            raise ValueError("Ranking requires one snapshot, horizon and version set")
        if evaluation.admissibility is Admissibility.ADMISSIBLE and (
            evaluation.quality.applicability is not Applicability.SUPPORTED
            or admissibility(pre_model_checks(snapshot, evaluation.action, scenario_policy))
            is not Admissibility.ADMISSIBLE
            or not scenario_policy.constraints.hard_check_inventory_verified
            or scenario_policy.constraints.minimum_interval_coverage is None
            or evaluation.quality.interval_coverage_target is None
            or evaluation.quality.interval_coverage_target
            < scenario_policy.constraints.minimum_interval_coverage
            or evaluation.quality.target != scenario_policy.constraints.target
            or evaluation.quality.unit != scenario_policy.constraints.unit
            or evaluation.quality.forecast_at
            != snapshot.as_of + timedelta(minutes=baseline.horizon_minutes)
            or evaluation.quality.model_version != baseline.model_version
            or evaluation.quality.upper > scenario_policy.constraints.sulfur_upper_limit
            or evaluation.quality.lower < 0
            or any(
                c.passed is not True and not c.message.startswith("Справочно (не hard check): ")
                for c in evaluation.checks
            )
        ):
            raise ValueError("Admissible evaluation contradicts its quality/checks")
    rejected = tuple(e for e in evaluations if e.admissibility is not Admissibility.ADMISSIBLE)
    feasible = []
    seen = set()
    for evaluation in evaluations:
        key = action_key(evaluation.action, snapshot)
        if evaluation.admissibility is Admissibility.ADMISSIBLE and key not in seen:
            seen.add(key)
            feasible.append(evaluation)
    explanations = [
        f"ranking policy={ranking_policy.version}; качество и hard checks проверены до ранжирования."
    ]
    if not feasible:
        status = (
            DecisionStatus.INSUFFICIENT_DATA
            if baseline.quality.applicability is Applicability.INSUFFICIENT_DATA
            else DecisionStatus.NO_FEASIBLE_OPTION
        )
        return status, None, (), rejected, tuple(explanations + list(baseline.reasons))
    dimensions = []
    tolerances = {t.metric: t for t in ranking_policy.tolerances}
    for metric, direction in (("throughput", -1), ("severity", 1), ("cost", 1)):
        tolerance = tolerances.get(metric)
        if tolerance is None or ranking_policy.model_version != baseline.model_version:
            explanations.append(
                f"{metric}: сравнение пропущено — нет обоснованного tolerance для модели."
            )
            continue
        source = tolerance.provenance
        if source.available_at > snapshot.as_of or (
            source.dataset_version is not None
            and source.dataset_version != snapshot.dataset_version
        ):
            explanations.append(
                f"{metric}: tolerance недоступен на время snapshot/для версии данных."
            )
            continue
        values = {}
        for evaluation in feasible:
            if metric == "severity":
                value, unit, basis = evaluation.reliability.severity_index, "1", EstimateBasis.PROXY
            else:
                estimate = getattr(evaluation, metric)
                value, unit, basis = estimate.value, estimate.unit, estimate.basis
            if value is None or unit != tolerance.unit or basis.value != tolerance.basis:
                break
            values[evaluation.evaluation_id] = direction * value
        else:
            dimensions.append((metric, tolerance.threshold, values))
            explanations.append(
                f"{metric}: tolerance={tolerance.threshold:g} {tolerance.unit}, basis={tolerance.basis}; evidence={tolerance.evidence}; provenance={source.model_dump(mode='json')}."
            )
            continue
        explanations.append(
            f"{metric}: сравнение пропущено — не все допустимые варианты сопоставимы."
        )

    controls = {c.signal_id: c for c in scenario_policy.catalogue.controls}

    def intervention(evaluation):
        total = Decimal(0)
        for signal, value in evaluation.action.changes.items():
            control = controls.get(signal)
            current = snapshot.values.get(signal)
            if control is None or control.step is None or current is None or current.value is None:
                raise ValueError("Admissible intervention lacks confirmed control/current/step")
            total += abs(Decimal(str(value)) - Decimal(str(current.value))) / Decimal(
                str(control.step)
            )
        return total

    def key(evaluation):
        return (
            *[values[evaluation.evaluation_id] for _, _, values in dimensions],
            intervention(evaluation),
            action_key(evaluation.action, snapshot),
        )

    if baseline.admissibility is Admissibility.ADMISSIBLE:
        improving = []
        improvement_metric = {}
        for candidate in feasible:
            if candidate is baseline:
                continue
            for metric, threshold, values in dimensions:
                advantage = Decimal(str(values[baseline.evaluation_id])) - Decimal(
                    str(values[candidate.evaluation_id])
                )
                if abs(advantage) > Decimal(str(threshold)):
                    if advantage > 0:
                        improving.append(candidate)
                        improvement_metric[candidate.evaluation_id] = metric
                    break
        preferred = min(improving, key=key) if improving else baseline
        status = DecisionStatus.CHANGE_RECOMMENDED if improving else DecisionStatus.NO_CHANGE
        explanations.append(
            "Есть преимущество выше tolerance."
            if improving
            else "Baseline допустим; доказуемого преимущества выше tolerance нет."
        )
        if improving:
            metric = improvement_metric[preferred.evaluation_id]
            tolerance = tolerances[metric]
            actual_baseline = (
                baseline.reliability.severity_index
                if metric == "severity"
                else getattr(baseline, metric).value
            )
            actual_preferred = (
                preferred.reliability.severity_index
                if metric == "severity"
                else getattr(preferred, metric).value
            )
            explanations.append(
                f"Основание выбора: {metric}; baseline={actual_baseline}, preferred={actual_preferred} {tolerance.unit}; разница строго выше tolerance={tolerance.threshold}; basis={tolerance.basis}. Это преимущество по модели/proxy, не доказательство промышленного эффекта."
            )
    else:
        preferred = min(feasible, key=key)
        status = DecisionStatus.CHANGE_RECOMMENDED
        explanations.append(
            "Baseline не прошёл обязательные проверки; выбран оценённый допустимый вариант. Это модельное устранение нарушения, не аварийная инструкция."
        )
    alternatives = tuple(
        e
        for e in sorted(feasible, key=key)
        if action_key(e.action, snapshot) != action_key(preferred.action, snapshot)
    )[:2]
    explanations.append(
        "Применённый порядок целей: "
        + (", ".join(metric for metric, _, _ in dimensions) or "сопоставимые цели отсутствуют")
        + "; затем меньшее вмешательство и канонический порядок signal_id/values."
    )
    for evaluation in (preferred, *alternatives):
        compared = (
            ", ".join(
                f"{metric}={evaluation.reliability.severity_index if metric == 'severity' else getattr(evaluation, metric).value}"
                for metric, _, _ in dimensions
            )
            or "численные цели не сравнивались"
        )
        explanations.append(
            f"Порядок evaluation_id={evaluation.evaluation_id}: {compared}; затем нормированное на подтверждённые шаги вмешательство и signal_id/values={action_key(evaluation.action, snapshot)}. Вмешательство не является физической стоимостью."
        )
    return status, preferred, alternatives, rejected, tuple(explanations)
