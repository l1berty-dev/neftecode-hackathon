"""Deterministic and auditable modelled full-chain scenario engine."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from neftecode_hackathon.contracts import (
    ActionOrigin,
    Admissibility,
    BlendComponent,
    CheckCategory,
    CheckResult,
    DecisionStatus,
    ModelledActionEvaluation,
    ModelledChainRequest,
    ModelledChainResult,
    ModelledControls,
    ModelledProductQuality,
)

from .blending import optimise_blend
from .vak import calculate_vak


@dataclass(frozen=True)
class ControlRange:
    p05: float
    median: float
    p95: float

    @property
    def width(self) -> float:
        return self.p95 - self.p05


class ModelledChainEngine:
    """Evaluate editable what-if inputs without presenting them as plant setpoints."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.ranges = {
            name: ControlRange(
                p05=float(values["p05"]),
                median=float(values["median"]),
                p95=float(values["p95"]),
            )
            for name, values in config["controls"].items()
        }

    @classmethod
    def from_path(cls, path: Path) -> ModelledChainEngine:
        return cls(yaml.safe_load(path.read_text(encoding="utf-8")))

    @classmethod
    def from_repository(cls, root: Path) -> ModelledChainEngine:
        config = yaml.safe_load((root / "config/modelled.yaml").read_text(encoding="utf-8"))
        manifest_path = root / "artifacts/modelled_manifest.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            config["version"] = manifest["model_version"]
            config["response"]["validation_q90_mg_kg"] = manifest["validation_q90_mg_kg"]
            lag = int(manifest["selected_lag_minutes"])
            config["response"]["selected_lag_minutes"] = {
                "p8": lag,
                "t11": lag,
                "f19": lag,
                "feed_sulfur": 180,
            }
        return cls(config)

    def _normalised(self, name: str, value: float) -> float:
        control_range = self.ranges[name]
        return (value - control_range.median) / control_range.width

    def _support_checks(self, controls: ModelledControls) -> tuple[CheckResult, ...]:
        checks: list[CheckResult] = []
        squared_distance = 0.0
        for name, value in (("p8", controls.p8), ("t11", controls.t11), ("f19", controls.f19)):
            control_range = self.ranges[name]
            passed = control_range.p05 <= value <= control_range.p95
            checks.append(
                CheckResult(
                    code=f"model_range_{name}",
                    passed=passed,
                    category=CheckCategory.APPLICABILITY,
                    message="Значение входит в экспериментальную train p5–p95 область.",
                    actual=value,
                    unit="raw dataset scale",
                )
            )
            squared_distance += self._normalised(name, value) ** 2
        checks.append(
            CheckResult(
                code="joint_support",
                passed=squared_distance <= 3.0,
                category=CheckCategory.APPLICABILITY,
                message="Совместная точка не выходит за эллипсоид поддержки train p5–p95.",
                actual=squared_distance,
                limit=3.0,
                unit="normalised squared distance",
            )
        )
        return tuple(checks)

    def _evaluate_action(
        self,
        request: ModelledChainRequest,
        controls: ModelledControls,
        origin: ActionOrigin,
        label: str,
    ) -> ModelledActionEvaluation:
        support_checks = self._support_checks(controls)
        feed = request.feed
        data_checks = (
            CheckResult(
                code="feed_sulfur_available",
                passed=True if feed.straight_run_sulfur_mass_pct is not None else None,
                category=CheckCategory.DATA,
                message="Доступна сера прямогонного дизельного топлива.",
                actual=feed.straight_run_sulfur_mass_pct,
                unit="mass %",
            ),
            CheckResult(
                code="feed_t95_available",
                passed=True if feed.t95_c is not None else None,
                category=CheckCategory.DATA,
                message="Доступен T95 сырья.",
                actual=feed.t95_c,
                unit="°C",
            ),
            CheckResult(
                code="feed_cetane_available",
                passed=True if feed.cetane_number is not None else None,
                category=CheckCategory.DATA,
                message="Доступно цетановое число сырья.",
                actual=feed.cetane_number,
                unit="index",
            ),
            CheckResult(
                code="feed_freshness",
                passed=(
                    None
                    if feed.age_minutes is None
                    else feed.age_minutes <= float(self.config["max_feed_age_minutes"])
                ),
                category=CheckCategory.DATA,
                message="Возраст входного анализа не превышает модельный предел свежести.",
                actual=feed.age_minutes,
                limit=float(self.config["max_feed_age_minutes"]),
                unit="min",
            ),
        )
        checks = (*support_checks, *data_checks)
        if any(check.passed is not True for check in checks):
            return ModelledActionEvaluation(
                label=label,
                origin=origin,
                controls=controls,
                quality=ModelledProductQuality(
                    sulfur_mg_kg=None,
                    sulfur_lower_mg_kg=None,
                    sulfur_upper_mg_kg=None,
                    t95_c=None,
                    cetane_number_nominal=None,
                    cetane_number_conservative=None,
                ),
                severity_proxy=None,
                throughput_proxy=None,
                energy_cost_proxy=None,
                checks=checks,
                admissibility=Admissibility.NOT_ASSESSABLE,
                reasons=(
                    "Недостаточно свежих данных или действие вне совместной области поддержки.",
                ),
            )

        response = self.config["response"]
        p8_n = self._normalised("p8", controls.p8)
        t11_n = self._normalised("t11", controls.t11)
        f19_n = self._normalised("f19", controls.f19)
        sulfur = (
            float(response["intercept_mg_kg"])
            + float(response["feed_coefficient"])
            * (float(feed.straight_run_sulfur_mass_pct) - float(response["feed_center_mass_pct"]))
            + float(response["p8_coefficient"]) * p8_n
            + float(response["t11_coefficient"]) * t11_n
            + float(response["f19_coefficient"]) * f19_n
        )
        sulfur = max(0.0, sulfur)
        q90 = float(response["validation_q90_mg_kg"])
        t95 = float(feed.t95_c) + float(response["t95_offset_c"])
        cetane = float(feed.cetane_number) + float(response["cetane_gain"])
        quality = ModelledProductQuality(
            sulfur_mg_kg=sulfur,
            sulfur_lower_mg_kg=max(0.0, sulfur - q90),
            sulfur_upper_mg_kg=sulfur + q90,
            t95_c=t95,
            cetane_number_nominal=cetane,
            cetane_number_conservative=cetane,
        )
        severity = (
            sum(
                (value - self.ranges[name].p05) / self.ranges[name].width
                for name, value in (
                    ("p8", controls.p8),
                    ("t11", controls.t11),
                    ("f19", controls.f19),
                )
            )
            / 3
        )
        throughput = controls.t11 / self.ranges["t11"].median
        pressure_temperature_load = (
            (controls.p8 - self.ranges["p8"].p05) / self.ranges["p8"].width
            + (controls.f19 - self.ranges["f19"].p05) / self.ranges["f19"].width
        ) / 2
        energy = pressure_temperature_load / max(throughput, 0.01)
        sulfur_check = CheckResult(
            code="hydrotreated_sulfur",
            passed=sulfur <= request.specification.sulfur_max_mg_kg,
            category=CheckCategory.QUALITY,
            message="Прогноз серы после гидроочистки сравнивается с пределом сценария.",
            actual=sulfur,
            limit=request.specification.sulfur_max_mg_kg,
            unit="mg/kg",
        )
        return ModelledActionEvaluation(
            label=label,
            origin=origin,
            controls=controls,
            quality=quality,
            severity_proxy=severity,
            throughput_proxy=throughput,
            energy_cost_proxy=energy,
            checks=(*checks, sulfur_check),
            admissibility=Admissibility.ADMISSIBLE,
            reasons=(
                "Эффект рассчитан sign-constrained response model на горизонте 180 минут.",
                "Интервал q90 откалиброван отдельно на validation и не заимствован у persistence.",
            ),
        )

    def _candidates(self, controls: ModelledControls) -> tuple[ModelledControls, ...]:
        values: list[tuple[float, ...]] = []
        step_fraction = float(self.config["candidate_step_fraction"])
        for name in ("p8", "t11", "f19"):
            control_range = self.ranges[name]
            step = step_fraction * control_range.width
            current = getattr(controls, name)
            values.append(
                tuple(
                    sorted(
                        {
                            min(control_range.p95, max(control_range.p05, current - step)),
                            min(control_range.p95, max(control_range.p05, current)),
                            min(control_range.p95, max(control_range.p05, current + step)),
                        }
                    )
                )
            )
        candidates = tuple(
            ModelledControls(p8=p8, t11=t11, f19=f19) for p8, t11, f19 in product(*values)
        )
        return candidates[: int(self.config["max_candidates"])]

    def _components_for_action(
        self, request: ModelledChainRequest, evaluation: ModelledActionEvaluation
    ) -> tuple[BlendComponent, ...]:
        result: list[BlendComponent] = []
        for component in request.tanks:
            if (
                component.component_id == "fresh_product"
                and evaluation.quality.sulfur_mg_kg is not None
            ):
                result.append(
                    component.model_copy(
                        update={
                            "sulfur_mg_kg": evaluation.quality.sulfur_mg_kg,
                            "t95_c": evaluation.quality.t95_c,
                            "cetane_number": evaluation.quality.cetane_number_conservative,
                        }
                    )
                )
            else:
                result.append(component)
        return tuple(result)

    def _blend(self, request: ModelledChainRequest, evaluation: ModelledActionEvaluation):  # noqa: ANN202
        additive = self.config["additive"]
        return optimise_blend(
            self._components_for_action(request, evaluation),
            request.specification,
            request.additive_ppm,
            min_additive_ppm=float(additive["min_supported_ppm"]),
            max_additive_ppm=float(additive["max_supported_ppm"]),
            nominal_cetane_per_1000=float(additive["nominal_cetane_per_1000_ppm"]),
            conservative_cetane_per_1000=float(additive["conservative_cetane_per_1000_ppm"]),
            additive_relative_cost=float(additive["relative_cost_per_tonne"]),
        )

    @staticmethod
    def _score(request: ModelledChainRequest, evaluation: ModelledActionEvaluation, blend) -> float:  # noqa: ANN001
        """Rank only feasible options and penalise an interval crossing the sulfur limit."""

        uncertainty_excess = max(
            0.0,
            float(evaluation.quality.sulfur_upper_mg_kg or 0)
            - request.specification.sulfur_max_mg_kg,
        )
        return (
            float(evaluation.energy_cost_proxy or 0)
            + float(blend.relative_cost_proxy or 0)
            + 2.0 * uncertainty_excess
        )

    def run(self, request: ModelledChainRequest) -> ModelledChainResult:
        avt = calculate_vak(request.avt_inputs)
        baseline = self._evaluate_action(
            request, request.controls, ActionOrigin.BASELINE, "Сохранить режим"
        )
        if baseline.admissibility is Admissibility.NOT_ASSESSABLE:
            return self._result(
                request,
                avt,
                DecisionStatus.INSUFFICIENT_DATA,
                baseline,
                None,
                (),
                None,
                baseline.checks,
                ("Дополните свежие обязательные входы перед расчётом рекомендации.",),
            )

        evaluations = [
            self._evaluate_action(request, item, ActionOrigin.SYSTEM, "Системный вариант")
            for item in self._candidates(request.controls)
        ]
        if request.operator_controls is not None:
            evaluations.append(
                self._evaluate_action(
                    request, request.operator_controls, ActionOrigin.OPERATOR, "Вариант оператора"
                )
            )

        feasible: list[tuple[float, ModelledActionEvaluation, Any]] = []
        baseline_blend = self._blend(request, baseline)
        if baseline_blend.admissibility is Admissibility.ADMISSIBLE:
            feasible.append(
                (
                    self._score(request, baseline, baseline_blend),
                    baseline,
                    baseline_blend,
                )
            )
        for evaluation in evaluations:
            if evaluation.admissibility is not Admissibility.ADMISSIBLE:
                continue
            blend = self._blend(request, evaluation)
            if blend.admissibility is Admissibility.ADMISSIBLE:
                score = self._score(request, evaluation, blend)
                feasible.append((score, evaluation, blend))

        if not feasible:
            checks = baseline_blend.checks or baseline.checks
            return self._result(
                request,
                avt,
                DecisionStatus.NO_FEASIBLE_OPTION,
                baseline,
                None,
                tuple(evaluations[:2]),
                baseline_blend,
                checks,
                ("Ни один вариант не проходит все обязательные ограничения качества.",),
            )

        feasible.sort(key=lambda item: item[0])
        selected = feasible[0]
        baseline_option = next(
            (item for item in feasible if item[1].origin is ActionOrigin.BASELINE), None
        )
        if (
            baseline_option is not None
            and selected[1].origin is not ActionOrigin.BASELINE
            and baseline_option[0] - selected[0] < 0.1
        ):
            selected = baseline_option
        _, preferred, blend = selected
        same_controls = preferred.controls == baseline.controls
        status = DecisionStatus.NO_CHANGE if same_controls else DecisionStatus.CHANGE_RECOMMENDED
        alternative_items = [item[1] for item in feasible if item[1] is not preferred]
        operator_items = [
            item for item in alternative_items if item.origin is ActionOrigin.OPERATOR
        ]
        alternatives = tuple(
            operator_items
            + [item for item in alternative_items if item.origin is not ActionOrigin.OPERATOR]
        )[:2]
        if status is DecisionStatus.NO_CHANGE:
            recommendation = (
                "Сохранить текущие модельные параметры: значимого выигрыша не найдено.",
            )
        else:
            recommendation = (
                f"Модельный вариант: P8={preferred.controls.p8:.4g}, "
                f"T11={preferred.controls.t11:.4g}, F19={preferred.controls.f19:.4g}.",
                "Перед применением требуется инженерная проверка перехода и физических единиц.",
            )
        return self._result(
            request,
            avt,
            status,
            baseline,
            preferred,
            alternatives,
            blend,
            blend.checks,
            recommendation,
        )

    def _result(
        self,
        request: ModelledChainRequest,
        avt,
        status: DecisionStatus,
        baseline,
        preferred,
        alternatives,
        blend,
        hard_checks,
        recommendation,
    ) -> ModelledChainResult:
        return ModelledChainResult(
            run_id=uuid4(),
            created_at=datetime.now(UTC),
            status=status,
            request=request,
            avt=avt,
            baseline=baseline,
            preferred=preferred,
            alternatives=alternatives,
            blend=blend,
            hard_checks=hard_checks,
            recommendation=recommendation,
            assumptions=(
                "Это модельный what-if, а не промышленная уставка и не команда оборудованию.",
                "P8/T11/F19 показаны в исходной шкале датасета: физические единицы не подтверждены.",
                "Диапазоны — train p5–p95, а не технологические или безопасностные пределы.",
                "Cost, severity и throughput являются относительными proxy.",
                "Задержки response model выбираются в диапазоне 0–180 минут; шаг совета — 60 минут.",
                "Эффект 2-EHN: номинально +5, консервативно +4 цетановых единицы на 1000 ppm.",
            ),
            trace=(
                "VAK: исправленные формулы организаторов и явная проверка входов.",
                "Hydrotreating: sign-constrained response, отдельный validation q90.",
                "Blending: сетка 5%, массовый баланс серы/цетана и линейный T95 proxy.",
                "Hard constraints проверены до ранжирования стоимости.",
            ),
            model_version=str(self.config["version"]),
            constraint_version=str(self.config["constraint_version"]),
        )
