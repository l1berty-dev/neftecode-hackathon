"""Pure, deterministic hard checks. Unknown required results never pass."""

from dataclasses import dataclass
from decimal import Decimal

from neftecode_hackathon.contracts import (
    Action,
    Admissibility,
    CheckCategory,
    CheckResult,
    MeasurementQuality,
    ProcessSnapshot,
)
from neftecode_hackathon.scenarios.config import ScenarioPolicy


@dataclass(frozen=True)
class PolicyCheck:
    result: CheckResult
    required: bool = True


def check(code, passed, category, message, *, required=True, actual=None, limit=None, unit=None):
    if not required:
        message = "Справочно (не hard check): " + message
    return PolicyCheck(
        CheckResult(
            code=code,
            passed=passed,
            category=category,
            message=message,
            actual=actual,
            limit=limit,
            unit=unit,
        ),
        required,
    )


def admissibility(checks: tuple[PolicyCheck, ...]) -> Admissibility:
    required = [c.result.passed for c in checks if c.required]
    if False in required:
        return Admissibility.REJECTED
    if not required or None in required:
        return Admissibility.NOT_ASSESSABLE
    return Admissibility.ADMISSIBLE


def measurement_check(snapshot, signal_id, unit, max_age_seconds, *, code, required=True):
    measurement = snapshot.values.get(signal_id)
    if measurement is None or measurement.value is None:
        return check(
            code, None, CheckCategory.DATA, f"{signal_id}: значение отсутствует.", required=required
        )
    age = (snapshot.as_of - measurement.measured_at).total_seconds()
    valid = (
        measurement.quality is MeasurementQuality.VALID
        and measurement.unit == unit
        and measurement.available_at <= snapshot.as_of
        and 0 <= age <= max_age_seconds
        and abs(measurement.age_seconds - age) <= 1
    )
    return check(
        code,
        True if valid else None,
        CheckCategory.DATA,
        f"{signal_id}: требуются valid, единица {unit}, возраст <= {max_age_seconds:g} с и согласованное время.",
        required=required,
        actual=age,
        limit=max_age_seconds,
        unit="s",
    )


def pre_model_checks(
    snapshot: ProcessSnapshot, action: Action, policy: ScenarioPolicy
) -> tuple[PolicyCheck, ...]:
    controls = {c.signal_id: c for c in policy.catalogue.controls}
    constraints = policy.constraints
    results = []
    signal_ids = set(action.changes) | {c.signal_id for c in controls.values() if c.available}
    for signal_id in sorted(signal_ids):
        current = snapshot.values.get(signal_id)
        value = action.changes.get(signal_id, current.value if current else None)
        control = controls.get(signal_id)
        if control is None:
            results.append(
                check(
                    f"controls.unknown.{signal_id}",
                    False,
                    CheckCategory.CONTROL,
                    f"{signal_id}: неизвестное управление.",
                )
            )
            continue
        if not control.available:
            results.append(
                check(
                    f"controls.unavailable.{signal_id}",
                    False,
                    CheckCategory.CONTROL,
                    f"{signal_id}: {control.unavailable_reason}",
                )
            )
            continue
        results.append(
            measurement_check(
                snapshot,
                signal_id,
                control.canonical_unit,
                control.max_age_seconds,
                code=f"controls.current.{signal_id}",
            )
        )
        provenance = control.provenance
        provenance_ok = (
            provenance.available_at <= snapshot.as_of
            and (provenance.train_end is None or provenance.train_end <= snapshot.as_of)
            and (
                provenance.dataset_version is None
                or provenance.dataset_version == snapshot.dataset_version
            )
        )
        results.append(
            check(
                f"controls.provenance.{signal_id}",
                provenance_ok,
                CheckCategory.APPLICABILITY,
                f"{signal_id}: диапазон/обучение должны быть доступны к моменту снимка.",
            )
        )
        results.append(
            check(
                f"controls.range.{signal_id}",
                control.model_min <= value <= control.model_max if value is not None else None,
                CheckCategory.CONTROL,
                f"{signal_id}: экспериментальный диапазон [{control.model_min:g}, {control.model_max:g}] {control.canonical_unit}; {provenance.source}.",
                actual=value,
                unit=control.canonical_unit,
            )
        )
        # Absolute-value grid is anchored at model_min; do not use float modulo.
        if signal_id in action.changes:
            steps = (Decimal(str(value)) - Decimal(str(control.model_min))) / Decimal(
                str(control.step)
            )
            on_grid = abs(steps - steps.to_integral_value()) <= Decimal("1e-9")
            results.append(
                check(
                    f"controls.step.{signal_id}",
                    on_grid,
                    CheckCategory.CONTROL,
                    f"{signal_id}: шаг {control.step:g} от нижней границы диапазона.",
                    actual=value,
                    unit=control.canonical_unit,
                )
            )
        if control.max_change_per_minute is not None and signal_id in action.changes:
            current = snapshot.values.get(signal_id)
            rate = None
            if current is not None and current.value is not None and constraints.transition_minutes:
                rate = abs(value - current.value) / constraints.transition_minutes
            results.append(
                check(
                    f"controls.ramp.{signal_id}",
                    rate <= control.max_change_per_minute if rate is not None else None,
                    CheckCategory.CONTROL,
                    f"{signal_id}: ramp limit; {control.ramp_evidence}. Длительность перехода задаётся отдельно от горизонта.",
                    actual=rate,
                    limit=control.max_change_per_minute,
                )
            )
    for combination in constraints.forbidden_combinations:
        violated = set(combination.signals) <= set(action.changes)
        results.append(
            check(
                combination.code,
                not violated,
                CheckCategory.CONTROL,
                f"Запрещено совместное изменение {', '.join(combination.signals)}; {combination.evidence}.",
            )
        )
    results.append(
        check(
            "data.input_manifest",
            True if constraints.model_inputs_verified else None,
            CheckCategory.DATA,
            "Обязательные входы и свежесть должны быть переданы в manifest модели.",
        )
    )
    for required_input in constraints.required_inputs:
        results.append(
            measurement_check(
                snapshot,
                required_input.signal_id,
                required_input.unit,
                required_input.max_age_seconds,
                code=f"data.required.{required_input.signal_id}",
            )
        )
    for signal_limit in constraints.signal_limits:
        available = measurement_check(
            snapshot,
            signal_limit.signal_id,
            signal_limit.unit,
            signal_limit.max_age_seconds,
            code=signal_limit.code + ".data",
            required=signal_limit.required,
        )
        results.append(available)
        measured = snapshot.values.get(signal_limit.signal_id)
        value = action.changes.get(signal_limit.signal_id, measured.value if measured else None)
        passed = None
        if available.result.passed is True and value is not None:
            passed = (signal_limit.minimum is None or value >= signal_limit.minimum) and (
                signal_limit.maximum is None or value <= signal_limit.maximum
            )
        results.append(
            check(
                signal_limit.code,
                passed,
                signal_limit.category,
                f"{signal_limit.signal_id}: предел [{signal_limit.minimum}, {signal_limit.maximum}] {signal_limit.unit}; {signal_limit.evidence}.",
                required=signal_limit.required,
                actual=value,
                unit=signal_limit.unit,
            )
        )
    return tuple(results)
