"""Unified scenario evaluation with validated, versioned hard-check policy."""

from datetime import timedelta
from uuid import uuid4

from pydantic import ValidationError

from neftecode_hackathon.contracts import (
    Action,
    Admissibility,
    Applicability,
    CheckCategory,
    ProcessSnapshot,
    QualityAssessment,
    ReliabilityAssessment,
    ScenarioEvaluation,
)
from neftecode_hackathon.quality.base import QualityAgent
from neftecode_hackathon.reliability import ReliabilityAgent
from neftecode_hackathon.scenarios.checks import admissibility, check, pre_model_checks
from neftecode_hackathon.scenarios.config import ScenarioPolicy, load_policy
from neftecode_hackathon.scenarios.efficiency import scenario_efficiency


class ScenarioEvaluator:
    def __init__(
        self,
        quality_agent: QualityAgent,
        reliability_agent: ReliabilityAgent,
        *,
        model_version: str,
        policy: ScenarioPolicy | None = None,
        horizon_minutes: int = 60,
    ) -> None:
        self.policy = ScenarioPolicy.model_validate((policy or load_policy()).model_dump())
        if horizon_minutes != self.policy.constraints.horizon_minutes:
            raise ValueError("Неподдерживаемый горизонт прогноза")
        inputs_model = self.policy.constraints.model_version
        if self.policy.constraints.model_inputs_verified and inputs_model != model_version:
            raise ValueError("Manifest входов относится к другой модели")
        self.quality_agent = quality_agent
        self.reliability_agent = reliability_agent
        self.model_version = model_version
        self.constraint_version = self.policy.constraints.constraint_version
        self.horizon_minutes = horizon_minutes

    def evaluate(
        self, snapshot: ProcessSnapshot, action: Action, horizon_minutes: int = 60
    ) -> ScenarioEvaluation:
        if horizon_minutes != self.horizon_minutes:
            raise ValueError("Неподдерживаемый горизонт прогноза")
        # Frozen public models still contain mutable maps; validate/copy at the boundary.
        snapshot = ProcessSnapshot.model_validate(snapshot.model_dump())
        action = Action.model_validate(action.model_dump())
        policy = ScenarioPolicy.model_validate(self.policy.model_dump())
        constraints = policy.constraints
        forecast_at = snapshot.as_of + timedelta(minutes=horizon_minutes)
        checks = list(pre_model_checks(snapshot, action, policy))
        pre_admissibility = admissibility(tuple(checks))
        if pre_admissibility is not Admissibility.ADMISSIBLE:
            data_unknown = any(
                c.required and c.result.passed is None and c.result.category is CheckCategory.DATA
                for c in checks
            )
            quality = self._unavailable_quality(
                forecast_at,
                Applicability.INSUFFICIENT_DATA
                if data_unknown and pre_admissibility is not Admissibility.REJECTED
                else Applicability.UNSUPPORTED,
                tuple(
                    c.result.message for c in checks if c.required and c.result.passed is not True
                ),
            )
        else:
            raw_quality = self.quality_agent.assess(
                snapshot.model_copy(deep=True), action.model_copy(deep=True), horizon_minutes
            )
            try:
                quality = QualityAssessment.model_validate(raw_quality.model_dump())
            except ValidationError:
                checks.append(
                    check(
                        "quality.contract",
                        False,
                        CheckCategory.APPLICABILITY,
                        "Ответ модели не соответствует контракту; прогноз скрыт.",
                    )
                )
                quality = self._unavailable_quality(
                    forecast_at, Applicability.UNSUPPORTED, ("Некорректный ответ модели.",)
                )
        if quality.model_version != self.model_version:
            raise ValueError("Агент качества вернул другую версию модели")
        identity_ok = (
            quality.forecast_at == forecast_at
            and quality.target == constraints.target
            and quality.unit == constraints.unit
        )
        checks.append(
            check(
                "quality.identity",
                identity_ok,
                CheckCategory.APPLICABILITY,
                "Цель, единица и момент прогноза должны соответствовать общему циклу.",
            )
        )
        if not identity_ok:
            quality = self._unavailable_quality(
                forecast_at,
                Applicability.UNSUPPORTED,
                ("Прогноз для другой цели, единицы или времени скрыт.",),
            )
        supported = quality.applicability is Applicability.SUPPORTED
        checks.append(
            check(
                "quality.applicability",
                True if supported else None,
                CheckCategory.APPLICABILITY,
                "Требуется подтверждённая совместная поддержка состояния и действия.",
            )
        )
        coverage_ok = None
        if (
            supported
            and constraints.minimum_interval_coverage is not None
            and quality.interval_coverage_target is not None
        ):
            coverage_ok = quality.interval_coverage_target >= constraints.minimum_interval_coverage
        checks.append(
            check(
                "quality.uncertainty",
                coverage_ok,
                CheckCategory.QUALITY,
                "Интервал и его покрытие должны соответствовать утверждённой политике модели.",
            )
        )
        checks.append(
            check(
                "quality.sulfur_upper",
                quality.upper <= constraints.sulfur_upper_limit if supported else None,
                CheckCategory.QUALITY,
                "Верхняя оценка серы гидроочистки должна быть <=10 мг/кг.",
                actual=quality.upper,
                limit=constraints.sulfur_upper_limit,
                unit=constraints.unit,
            )
        )
        checks.append(
            check(
                "quality.nonnegative",
                quality.lower >= 0 if supported else None,
                CheckCategory.QUALITY,
                "Прогнозный интервал серы не должен содержать отрицательных значений.",
            )
        )
        checks.append(
            check(
                "reliability.hard_checks",
                True if constraints.hard_check_inventory_verified else None,
                CheckCategory.RELIABILITY,
                "Перечень обязательных технологических проверок должен быть утверждён; индекс тяжести их не заменяет.",
            )
        )
        if pre_admissibility is Admissibility.ADMISSIBLE:
            raw_reliability = self.reliability_agent.assess(
                snapshot.model_copy(deep=True), action.model_copy(deep=True)
            )
            reliability = ReliabilityAssessment.model_validate(raw_reliability.model_dump())
        else:
            reliability = ReliabilityAssessment(
                severity_index=None,
                factors=(),
                transition_assessed=False,
                limitations=(
                    "Оценка надёжности не запускалась: предварительные проверки не пройдены.",
                ),
            )
        checks.append(
            check(
                "reliability.transition",
                True if not action.changes else None,
                CheckCategory.RELIABILITY,
                "Для смены настроек результат проверки безопасности перехода не предоставлен; transition_assessed сам по себе не означает прохождение hard check.",
                required=constraints.transition_required,
            )
        )
        throughput, cost = scenario_efficiency(snapshot, action, horizon_minutes)
        return ScenarioEvaluation(
            evaluation_id=uuid4(),
            snapshot_id=snapshot.snapshot_id,
            horizon_minutes=horizon_minutes,
            action=action,
            quality=quality,
            reliability=reliability,
            throughput=throughput,
            cost=cost,
            checks=tuple(c.result for c in checks),
            admissibility=admissibility(tuple(checks)),
            reasons=tuple(c.result.message for c in checks if c.result.passed is not True)
            + quality.reasons
            + constraints.limitations
            + reliability.limitations,
            model_version=self.model_version,
            constraint_version=self.constraint_version,
        )

    def _unavailable_quality(self, forecast_at, applicability, reasons):
        return QualityAssessment(
            target=self.policy.constraints.target,
            forecast_at=forecast_at,
            prediction=None,
            lower=None,
            upper=None,
            unit=self.policy.constraints.unit,
            interval_coverage_target=None,
            applicability=applicability,
            reasons=reasons,
            model_version=self.model_version,
        )
