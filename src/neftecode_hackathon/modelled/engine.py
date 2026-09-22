"""Deterministic, editable AVT -> hydrotreating -> blending demonstration."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml

from neftecode_hackathon.contracts import (
    ActionOrigin,
    Admissibility,
    BlendComponent,
    BlendRecipe,
    BlendShare,
    CheckCategory,
    CheckResult,
    DecisionStatus,
    ModelledActionEvaluation,
    ModelledChainRequest,
    ModelledChainResult,
    ModelledControls,
    ModelledFeedQuality,
    ModelledPreset,
    ModelledProductQuality,
    ProductSpecification,
    ProductSpecProfile,
)

from .vak import evaluate_avt_vak

ASSUMPTIONS = (
    "Это модельный what-if, а не подключение к производству и не команда оборудованию.",
    "Единицы P8/T11/F19 не подтверждены; значения показаны в сырой шкале набора данных.",
    "История не подтвердила причинный эффект управлений; отклик задаётся видимыми экспериментальными коэффициентами.",
    "T95 смеси рассчитан линейно; цетановая присадка использует консервативную модель, а не паспорт поставщика.",
    "Доступность резервуаров показана, но размер партии не задан, поэтому тоннаж не ограничивает доли рецепта.",
)


class ModelledChainEngine:
    def __init__(self, config: dict) -> None:
        self.config = config

    @classmethod
    def from_repository(cls, root: Path) -> ModelledChainEngine:
        config = yaml.safe_load((root / "config/modelled.yaml").read_text(encoding="utf-8"))
        return cls(config)

    def run(self, request: ModelledChainRequest) -> ModelledChainResult:
        avt = evaluate_avt_vak(request.avt_inputs)
        missing = self._missing_reasons(request)
        if missing:
            checks = tuple(
                self._check(f"data_{index}", None, CheckCategory.DATA, reason)
                for index, reason in enumerate(missing, 1)
            )
            return ModelledChainResult(
                run_id=uuid4(),
                created_at=datetime.now(UTC),
                status=DecisionStatus.INSUFFICIENT_DATA,
                request=request,
                avt=avt,
                baseline=None,
                preferred=None,
                alternatives=(),
                blend=None,
                hard_checks=checks,
                recommendation=("Расчёт остановлен: заполните обязательные факты.", *missing),
                assumptions=ASSUMPTIONS,
                trace=("input validation: insufficient_data",),
                model_version=self.config["model_version"],
                constraint_version=self.config["constraint_version"],
            )

        evaluations = [
            self._evaluate("Сохранить настройки", ActionOrigin.BASELINE, request.controls, request)
        ]
        for label, controls in self._system_candidates(request.controls):
            evaluations.append(self._evaluate(label, ActionOrigin.SYSTEM, controls, request))
        if request.operator_controls is not None:
            evaluations.append(
                self._evaluate(
                    "Вариант оператора", ActionOrigin.OPERATOR, request.operator_controls, request
                )
            )

        baseline = evaluations[0]
        feasible = [item for item in evaluations if item.admissibility is Admissibility.ADMISSIBLE]
        preferred = min(feasible, key=self._rank) if feasible else None
        alternatives = tuple(
            item for item in sorted(feasible, key=self._rank) if item != preferred
        )[:2]
        blend = self._best_blend(request)
        hard_checks = blend.checks if blend else ()
        if (
            preferred is None
            or blend is None
            or blend.admissibility is not Admissibility.ADMISSIBLE
        ):
            status = DecisionStatus.NO_FEASIBLE_OPTION
            recommendation = (
                "Нет варианта, одновременно проходящего обязательные проверки качества.",
            )
        elif preferred.origin is ActionOrigin.BASELINE:
            status = DecisionStatus.NO_CHANGE
            recommendation = (
                "Сохранить текущие настройки: обязательные проверки пройдены, значимого выигрыша нет.",
            )
        else:
            status = DecisionStatus.CHANGE_RECOMMENDED
            recommendation = (
                f"Предпочтителен модельный вариант «{preferred.label}».",
                "Перед применением требуется инженерная проверка единиц, перехода и допустимых диапазонов.",
            )
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
            assumptions=ASSUMPTIONS,
            trace=(
                "validated editable inputs and freshness",
                f"evaluated {len(evaluations)} actions through one response function",
                "filtered hard quality checks before ranking proxies",
                "enumerated blend shares on a 5% grid",
            ),
            model_version=self.config["model_version"],
            constraint_version=self.config["constraint_version"],
        )

    def _missing_reasons(self, request: ModelledChainRequest) -> list[str]:
        reasons = []
        feed = request.feed
        for value, label in (
            (feed.straight_run_sulfur_mass_pct, "сера прямогонного компонента"),
            (feed.t95_c, "T95 сырья"),
            (feed.cetane_number, "цетановое число сырья"),
        ):
            if value is None:
                reasons.append(f"Не задан обязательный показатель: {label}.")
        if feed.age_minutes is None or feed.age_minutes > 240:
            reasons.append("Данные сырья старше 240 минут или их свежесть неизвестна.")
        for tank in request.tanks:
            if None in (tank.sulfur_mg_kg, tank.t95_c, tank.cetane_number):
                reasons.append(
                    f"Для резервуара «{tank.name}» заполнены не все показатели качества."
                )
        return reasons

    def _system_candidates(self, current: ModelledControls):
        bounds = self.config["controls"]

        def clamp(name: str, value: float) -> float:
            return max(bounds[name]["minimum"], min(bounds[name]["maximum"], value))

        yield (
            "Усилить очистку",
            ModelledControls(
                p8=clamp("p8", current.p8 + 2 * bounds["p8"]["step"]),
                t11=clamp("t11", current.t11 - bounds["t11"]["step"]),
                f19=clamp("f19", current.f19 + bounds["f19"]["step"]),
            ),
        )
        yield (
            "Поддержать выпуск",
            ModelledControls(
                p8=current.p8,
                t11=clamp("t11", current.t11 + bounds["t11"]["step"]),
                f19=current.f19,
            ),
        )
        yield (
            "Снизить тяжесть режима",
            ModelledControls(
                p8=clamp("p8", current.p8 - bounds["p8"]["step"]),
                t11=current.t11,
                f19=clamp("f19", current.f19 - bounds["f19"]["step"]),
            ),
        )

    def _evaluate(self, label, origin, controls, request) -> ModelledActionEvaluation:
        bounds = self.config["controls"]
        response = self.config["response"]
        feed = request.feed
        sulfur = (
            feed.straight_run_sulfur_mass_pct * response["feed_sulfur_factor"]
            + (feed.t95_c - 350) * response["feed_t95_factor"]
            + (controls.p8 - bounds["p8"]["reference"]) * response["p8_factor"]
            + (controls.t11 - bounds["t11"]["reference"]) * response["t11_factor"]
            + (controls.f19 - bounds["f19"]["reference"]) * response["f19_factor"]
        )
        sulfur = max(0.0, sulfur)
        half = response["interval_half_width_mg_kg"]
        quality = ModelledProductQuality(
            sulfur_mg_kg=sulfur,
            sulfur_lower_mg_kg=max(0.0, sulfur - half),
            sulfur_upper_mg_kg=sulfur + half,
            t95_c=feed.t95_c,
            cetane_number_nominal=feed.cetane_number,
            cetane_number_conservative=feed.cetane_number,
        )
        checks = []
        in_range = True
        for name in ("p8", "t11", "f19"):
            value = getattr(controls, name)
            passed = bounds[name]["minimum"] <= value <= bounds[name]["maximum"]
            in_range &= passed
            checks.append(
                self._check(
                    f"control_{name}_model_range",
                    passed,
                    CheckCategory.CONTROL,
                    f"{name.upper()} находится в экспериментальном train-only диапазоне.",
                    value,
                )
            )
        sulfur_ok = sulfur + half <= request.specification.sulfur_max_mg_kg
        checks.append(
            self._check(
                "product_sulfur_upper",
                sulfur_ok,
                CheckCategory.QUALITY,
                "Верхняя граница серы не превышает лимит.",
                sulfur + half,
                request.specification.sulfur_max_mg_kg,
                "mg/kg",
            )
        )
        admissibility = (
            Admissibility.ADMISSIBLE if in_range and sulfur_ok else Admissibility.REJECTED
        )
        severity = (
            (controls.p8 - bounds["p8"]["minimum"])
            / (bounds["p8"]["maximum"] - bounds["p8"]["minimum"])
            + (controls.f19 - bounds["f19"]["minimum"])
            / (bounds["f19"]["maximum"] - bounds["f19"]["minimum"])
        ) / 2
        energy = (
            1
            + max(0.0, controls.p8 - bounds["p8"]["reference"]) * 4
            + max(0.0, controls.f19 - bounds["f19"]["reference"]) / 300
        )
        return ModelledActionEvaluation(
            label=label,
            origin=origin,
            controls=controls,
            quality=quality,
            severity_proxy=severity,
            throughput_proxy=controls.t11,
            energy_cost_proxy=energy,
            checks=tuple(checks),
            admissibility=admissibility,
            reasons=("Оценка использует экспериментальный отклик; причинность не доказана.",),
        )

    @staticmethod
    def _rank(item: ModelledActionEvaluation):
        origin_priority = {
            ActionOrigin.BASELINE: 0,
            ActionOrigin.OPERATOR: 1,
            ActionOrigin.SYSTEM: 2,
        }
        return (
            item.energy_cost_proxy,
            item.quality.sulfur_mg_kg,
            origin_priority[item.origin],
            item.label,
        )

    def _best_blend(self, request: ModelledChainRequest) -> BlendRecipe | None:
        step = self.config["blending"]["grid_step"]
        units = round(1 / step)
        candidates = []
        for parts in _compositions(units, len(request.tanks)):
            fractions = [part / units for part in parts]
            candidates.append(self._blend_recipe(request, fractions))
        feasible = [item for item in candidates if item.admissibility is Admissibility.ADMISSIBLE]
        return (
            min(
                feasible,
                key=lambda item: (item.relative_cost_proxy, tuple(s.fraction for s in item.shares)),
            )
            if feasible
            else min(
                candidates,
                key=lambda item: sum(check.passed is False for check in item.checks),
                default=None,
            )
        )

    def _blend_recipe(self, request, fractions) -> BlendRecipe:
        blend = self.config["blending"]
        sulfur = sum(
            f * tank.sulfur_mg_kg for f, tank in zip(fractions, request.tanks, strict=True)
        )
        t95 = sum(f * tank.t95_c for f, tank in zip(fractions, request.tanks, strict=True))
        cetane = sum(
            f * tank.cetane_number for f, tank in zip(fractions, request.tanks, strict=True)
        )
        gain = request.additive_ppm / 1000 * blend["cetane_gain_per_1000_ppm"]
        nominal, conservative = cetane + gain, cetane + gain * blend["conservative_gain_fraction"]
        values = (
            (
                "blend_sulfur",
                sulfur <= request.specification.sulfur_max_mg_kg,
                sulfur,
                request.specification.sulfur_max_mg_kg,
                "mg/kg",
            ),
            (
                "blend_t95",
                t95 <= request.specification.t95_max_c,
                t95,
                request.specification.t95_max_c,
                "°C",
            ),
            (
                "blend_cetane",
                conservative >= request.specification.cetane_min,
                conservative,
                request.specification.cetane_min,
                "cetane number",
            ),
            (
                "additive_limit",
                request.additive_ppm <= blend["additive_max_ppm"],
                request.additive_ppm,
                blend["additive_max_ppm"],
                "ppm",
            ),
        )
        checks = tuple(
            self._check(
                code,
                passed,
                CheckCategory.QUALITY,
                "Обязательная проверка товарного качества.",
                actual,
                limit,
                unit,
            )
            for code, passed, actual, limit, unit in values
        )
        quality = ModelledProductQuality(
            sulfur_mg_kg=sulfur,
            sulfur_lower_mg_kg=None,
            sulfur_upper_mg_kg=None,
            t95_c=t95,
            cetane_number_nominal=nominal,
            cetane_number_conservative=conservative,
        )
        cost = (
            sum(f * t.relative_cost for f, t in zip(fractions, request.tanks, strict=True))
            + request.additive_ppm / 1_000_000 * blend["additive_relative_cost"]
        )
        return BlendRecipe(
            shares=tuple(
                BlendShare(component_id=t.component_id, fraction=f)
                for f, t in zip(fractions, request.tanks, strict=True)
            ),
            additive_ppm=request.additive_ppm,
            quality=quality,
            relative_cost_proxy=cost,
            admissibility=Admissibility.ADMISSIBLE
            if all(c.passed for c in checks)
            else Admissibility.REJECTED,
            checks=checks,
            limitations=(ASSUMPTIONS[3], ASSUMPTIONS[4]),
        )

    @staticmethod
    def _check(code, passed, category, message, actual=None, limit=None, unit=None):
        return CheckResult(
            code=code,
            passed=passed,
            category=category,
            message=message,
            actual=actual,
            limit=limit,
            unit=unit,
        )


def _compositions(total: int, parts: int):
    if parts == 1:
        yield (total,)
        return
    for first in range(total + 1):
        for rest in _compositions(total - first, parts - 1):
            yield (first, *rest)


def _tank(component_id, name, sulfur, t95, cetane, cost=1.0):
    return BlendComponent(
        component_id=component_id,
        name=name,
        available_tonnes=1000,
        sulfur_mg_kg=sulfur,
        t95_c=t95,
        cetane_number=cetane,
        relative_cost=cost,
    )


def _request(preset_id, sulfur=0.28, operator=None, missing=False, additive=0.0):
    return ModelledChainRequest(
        preset_id=preset_id,
        avt_inputs={"T33": 350, "P67": 0.2, "P4": 0.3, "F65": 20, "F32": 100, "F30": 5},
        feed=ModelledFeedQuality(
            straight_run_sulfur_mass_pct=None if missing else sulfur,
            t95_c=350,
            cetane_number=49,
            age_minutes=0,
        ),
        controls=ModelledControls(p8=0.1569, t11=362.88, f19=212.04),
        operator_controls=operator,
        specification=ProductSpecification(
            profile=ProductSpecProfile.K5_SUMMER, sulfur_max_mg_kg=10, t95_max_c=360, cetane_min=51
        ),
        tanks=(
            _tank("clean", "Чистый компонент", 6, 350, 52, 1.08),
            _tank("economy", "Экономичный компонент", 9, 355, 50.5, 0.96),
        ),
        additive_ppm=additive,
    )


def build_presets() -> tuple[ModelledPreset, ...]:
    specs = (
        (
            "stable_k5",
            "Стабильный К5",
            "Текущая схема проходит ограничения.",
            DecisionStatus.NO_CHANGE,
            _request("stable_k5"),
        ),
        (
            "feed_sulfur_rise",
            "Рост серы сырья",
            "Проверка компенсации ухудшения сырья.",
            DecisionStatus.CHANGE_RECOMMENDED,
            _request("feed_sulfur_rise", 0.46),
        ),
        (
            "operator_option",
            "Вариант оператора",
            "Оператор оценивается тем же путём и может победить.",
            DecisionStatus.CHANGE_RECOMMENDED,
            _request(
                "operator_option",
                0.46,
                ModelledControls(p8=0.195, t11=340, f19=212.04),
            ),
        ),
        (
            "missing_data",
            "Недостаточно данных",
            "Обязательный показатель отсутствует.",
            DecisionStatus.INSUFFICIENT_DATA,
            _request("missing_data", missing=True),
        ),
        (
            "blend_additive",
            "Блендинг + 2-EHN",
            "Подбор рецепта с модельной присадкой.",
            DecisionStatus.NO_CHANGE,
            _request("blend_additive", additive=5000),
        ),
    )
    return tuple(
        ModelledPreset(preset_id=i, name=n, description=d, expected_status=s, request=r)
        for i, n, d, s, r in specs
    )
