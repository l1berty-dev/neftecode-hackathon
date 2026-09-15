"""Measured product flow is not a forecast; missing economic inputs stay unknown."""

from neftecode_hackathon.contracts import (
    Action,
    EstimateBasis,
    MetricEstimate,
    ProcessSnapshot,
)
from neftecode_hackathon.scenarios.checks import measurement_check
from neftecode_hackathon.scenarios.config import ThroughputPolicy, load_throughput_policy


def unavailable_metric(explanation: str, unit: str | None = None) -> MetricEstimate:
    return MetricEstimate(
        value=None, unit=unit, basis=EstimateBasis.UNAVAILABLE, explanation=explanation
    )


def current_throughput(
    snapshot: ProcessSnapshot, policy: ThroughputPolicy | None = None
) -> MetricEstimate:
    """Read the current outlet flow only; do not infer product flow from feed T11."""
    snapshot = ProcessSnapshot.model_validate(snapshot.model_dump())
    policy = ThroughputPolicy.model_validate((policy or load_throughput_policy()).model_dump())
    source = policy.provenance
    if (
        not policy.unit_verified
        or source is None
        or source.available_at > snapshot.as_of
        or (source.kind == "train" and source.dataset_version != snapshot.dataset_version)
    ):
        return unavailable_metric(
            "Текущий выпуск: численная единица/шкала не подтверждена на время снимка."
        )
    result = measurement_check(
        snapshot, policy.signal_id, policy.unit, policy.max_age_seconds, code="throughput.current"
    ).result
    if result.passed is not True:
        return unavailable_metric(result.message, policy.unit)
    value = snapshot.values[policy.signal_id].value
    if value < 0:
        return unavailable_metric(
            "Отрицательный расход продукта не интерпретируется как выпуск.", policy.unit
        )
    measurement = snapshot.values[policy.signal_id]
    return MetricEstimate(
        value=value,
        unit=policy.unit,
        basis=EstimateBasis.MEASURED,
        explanation=(
            f"Текущий расход продукта {policy.signal_id}, не прогноз и не накопленный выпуск. "
            f"measured_at={measurement.measured_at.isoformat()}; age={measurement.age_seconds:g} s; "
            f"policy={policy.version}; evidence={policy.evidence}; provenance={source.model_dump(mode='json')}"
        ),
    )


def scenario_efficiency(
    snapshot: ProcessSnapshot, action: Action, horizon_minutes: int
) -> tuple[MetricEstimate, MetricEstimate]:
    """No validated response/balance or prices exist in v1; baseline is also future."""
    ProcessSnapshot.model_validate(snapshot.model_dump())
    Action.model_validate(action.model_dump())
    if horizon_minutes != 60:
        raise ValueError("Неподдерживаемый горизонт прогноза эффективности")
    return (
        unavailable_metric(
            "Будущий выпуск через 60 минут не оценён: нет подтверждённой модели отклика/материального баланса. Текущий расход не переносится в прогноз, включая baseline."
        ),
        unavailable_metric(
            "Будущие затраты не оценены: для C=sum(q_i*p_i) нужны прогнозы расхода ресурсов q_i, подтверждённые единицы и цены p_i. Эти данные и модель не переданы; экономия не рассчитана."
        ),
    )
