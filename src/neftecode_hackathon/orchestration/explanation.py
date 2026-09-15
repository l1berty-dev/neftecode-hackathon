"""Deterministic presentation of computed facts, not a second decision maker."""

from neftecode_hackathon.contracts import (
    Action,
    Applicability,
    DecisionStatus,
    MetricEstimate,
    ProcessSnapshot,
    ScenarioEvaluation,
    SnapshotMode,
    TraceEntry,
)
from neftecode_hackathon.scenarios.config import ScenarioPolicy


def _unique(messages):
    return tuple(dict.fromkeys(message for message in messages if message))


def _metric(name: str, estimate: MetricEstimate) -> str:
    value = "не оценено" if estimate.value is None else str(estimate.value)
    unit = estimate.unit or "единица не установлена"
    interval = (
        f"; интервал=[{estimate.lower}, {estimate.upper}]" if estimate.lower is not None else ""
    )
    return (
        f"{name}: {value} ({unit}); basis={estimate.basis.value}{interval}. {estimate.explanation}"
    )


def evaluation_facts(evaluation: ScenarioEvaluation) -> tuple[str, ...]:
    quality = evaluation.quality
    if quality.applicability is Applicability.SUPPORTED:
        sulfur = (
            f"Сера: прогноз={quality.prediction}, интервал=[{quality.lower}, {quality.upper}] "
            f"{quality.unit}; basis=predicted; forecast_at={quality.forecast_at.isoformat()}; "
            f"coverage_target={quality.interval_coverage_target}."
        )
    else:
        sulfur = f"Сера: не оценено; applicability={quality.applicability.value}. " + " ".join(
            quality.reasons
        )
    severity = evaluation.reliability.severity_index
    severity_basis = "proxy" if severity is not None else "unavailable"
    return (
        sulfur,
        _metric("Будущий выпуск", evaluation.throughput),
        f"Тяжесть режима: {severity if severity is not None else 'не оценено'}; basis={severity_basis}; статический proxy, не вероятность аварии и не ресурс катализатора.",
        _metric("Будущие затраты", evaluation.cost),
        f"transition_assessed={str(evaluation.reliability.transition_assessed).lower()}; это поле не заменяет проверки безопасности перехода.",
    )


def action_facts(
    snapshot: ProcessSnapshot, action: Action, policy: ScenarioPolicy
) -> tuple[str, ...]:
    if not action.changes:
        return ("Сохранить настройки; процесс продолжает изменяться, это не заморозка процесса.",)
    controls = {c.signal_id: c for c in policy.catalogue.controls}
    lines = []
    for signal, requested in sorted(action.changes.items()):
        control, measured = controls.get(signal), snapshot.values.get(signal)
        current = (
            "нет пригодного измерения"
            if measured is None or measured.value is None
            else str(measured.value)
        )
        unit = control.canonical_unit if control and control.unit_verified else None
        unit_text = unit or "численная единица/шкала не подтверждена"
        name = control.name if control else "неизвестное управление"
        metadata = (
            f"; measured_at={measured.measured_at.isoformat()}; available_at={measured.available_at.isoformat()}; "
            f"age_seconds={measured.age_seconds}; quality={measured.quality.value}; source={measured.source}; raw_unit={measured.unit}"
            if measured
            else ""
        )
        lines.append(f"{signal} ({name}): {current} → {requested} ({unit_text}){metadata}.")
    return tuple(lines)


def check_facts(evaluation: ScenarioEvaluation) -> tuple[str, ...]:
    result = []
    for check in evaluation.checks:
        state = (
            "пройдена"
            if check.passed is True
            else "нарушена"
            if check.passed is False
            else "не оценена"
        )
        numbers = (
            f"; actual={check.actual}; limit={check.limit}; unit={check.unit}"
            if check.actual is not None or check.limit is not None
            else ""
        )
        result.append(f"{check.code}: {state}{numbers}. {check.message}")
    return tuple(result)


def build_explanation(
    snapshot: ProcessSnapshot,
    status: DecisionStatus,
    evaluations: tuple[ScenarioEvaluation, ...],
    preferred: ScenarioEvaluation | None,
    alternatives: tuple[ScenarioEvaluation, ...],
    selection_reasons: tuple[str, ...],
    policy: ScenarioPolicy,
) -> tuple[str, ...]:
    headlines = {
        DecisionStatus.CHANGE_RECOMMENDED: "Рекомендовано модельное изменение настроек; система не исполняет команды оборудования.",
        DecisionStatus.NO_CHANGE: "Сохранить настройки: baseline допустим, доказуемого преимущества изменения нет.",
        DecisionStatus.INSUFFICIENT_DATA: "Совет не сформирован: исходных данных для оценки состояния недостаточно.",
        DecisionStatus.NO_FEASIBLE_OPTION: "Совет не сформирован: нет оценённого допустимого варианта; недопустимый baseline не рекомендован.",
    }
    baseline = evaluations[0]
    lines = [
        headlines[status],
        "Режим: воспроизведение истории (replay), не подключение к реальному производству."
        if snapshot.mode is SnapshotMode.REPLAY
        else "Режим: manual; исполнение команд оборудования не предусмотрено.",
        f"Снимок {snapshot.snapshot_id}, as_of={snapshot.as_of.isoformat()}; dataset={snapshot.dataset_version}; model={baseline.model_version}; constraints={baseline.constraint_version}.",
        f"Baseline: {baseline.admissibility.value}.",
        *evaluation_facts(baseline),
        *selection_reasons,
    ]
    if preferred is not None:
        lines.extend(
            [
                f"Предпочтительный вариант: evaluation_id={preferred.evaluation_id}; {preferred.admissibility.value}.",
                *action_facts(snapshot, preferred.action, policy),
                *evaluation_facts(preferred),
                "Результаты проверок предпочтительного варианта:",
                *check_facts(preferred),
            ]
        )
        if preferred.action.changes:
            lines.append(
                "Модельная оценка альтернативы не доказывает эффект вмешательства на реальном производстве."
            )
    for alternative in alternatives:
        lines.extend(
            [
                f"Допустимая альтернатива evaluation_id={alternative.evaluation_id}, не выбрана:",
                *action_facts(snapshot, alternative.action, policy),
                *evaluation_facts(alternative),
            ]
        )
    if alternatives:
        lines.append(
            "Выбор между допустимыми вариантами следует критериям отбора выше; при равенстве используется меньшее вмешательство и детерминированный порядок. Не утверждается выигрыш по пропущенным метрикам."
        )
    rejected = [e for e in evaluations if e.admissibility.value != "admissible"]
    if rejected:
        lines.append(
            f"Отклонено/не удалось оценить вариантов: {len(rejected)}; индивидуальные результаты сохранены в rejected_evaluations и trace."
        )
    warnings = _unique(
        [
            *snapshot.issues,
            *(c.unavailable_reason for c in policy.catalogue.controls if not c.available),
            *(
                reason
                for e in evaluations
                for reason in (*e.reasons, *e.quality.reasons, *e.reliability.limitations)
            ),
            *(
                fact
                for e in rejected
                for check, fact in zip(e.checks, check_facts(e), strict=True)
                if check.passed is not True
            ),
        ]
    )
    if warnings:
        lines.extend(["Ограничения и неизвестное:", *warnings])
    return tuple(lines)


def evaluation_trace(snapshot: ProcessSnapshot, evaluation: ScenarioEvaluation) -> TraceEntry:
    return TraceEntry(
        role="scenario_evaluator",
        input_ids=(snapshot.snapshot_id, evaluation.action.action_id),
        output_summary=" ".join(
            [
                f"evaluation_id={evaluation.evaluation_id}; admissibility={evaluation.admissibility.value}; changes={dict(sorted(evaluation.action.changes.items()))}.",
                *evaluation_facts(evaluation),
                *check_facts(evaluation),
                *(
                    f"Фактор {factor.name}, contribution={factor.contribution}: {factor.explanation}"
                    for factor in evaluation.reliability.factors
                ),
                *evaluation.reasons,
                *evaluation.quality.reasons,
                *evaluation.reliability.limitations,
            ]
        ),
        check_codes=tuple(c.code for c in evaluation.checks),
    )
