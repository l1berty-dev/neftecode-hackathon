"""Editable demo inputs; every response is recalculated by the engine."""

from __future__ import annotations

from neftecode_hackathon.contracts import (
    BlendComponent,
    DecisionStatus,
    ModelledChainRequest,
    ModelledControls,
    ModelledFeedQuality,
    ModelledPreset,
    ProductSpecification,
    ProductSpecProfile,
)


def _avt() -> dict[str, float]:
    return {
        "T12": 300.0,
        "F15": 2200.0,
        "W7": 0.45,
        "T23": 260.0,
        "F1": 120.0,
        "F26": 900.0,
        "P13": 0.35,
        "F9": 1450.0,
        "T6": 300.0,
        "F22": 1000.0,
        "F25": 13000.0,
        "T16": 250.0,
        "P8": 0.17,
        "P24": 0.3,
        "F2": 1000.0,
        "LIMS_T95": 350.0,
    }


def _spec(profile: ProductSpecProfile = ProductSpecProfile.K5_SUMMER) -> ProductSpecification:
    return ProductSpecification(
        profile=profile,
        sulfur_max_mg_kg=10,
        t95_max_c=360,
        cetane_min=47 if profile is ProductSpecProfile.K5_WINTER else 51,
    )


def _fresh() -> BlendComponent:
    return BlendComponent(
        component_id="fresh_product",
        name="Свежий гидроочищенный ДТ",
        available_tonnes=1000,
        sulfur_mg_kg=8.3,
        t95_c=345,
        cetane_number=52,
        relative_cost=1,
    )


def build_presets() -> tuple[ModelledPreset, ...]:
    controls = ModelledControls(p8=0.181302, t11=363.832687, f19=218.003944)
    stable = ModelledChainRequest(
        preset_id="stable-k5",
        avt_inputs=_avt(),
        feed=ModelledFeedQuality(
            straight_run_sulfur_mass_pct=0.90, t95_c=350, cetane_number=50, age_minutes=45
        ),
        controls=controls,
        specification=_spec(),
        tanks=(_fresh(),),
    )
    sulfur_shock = stable.model_copy(
        update={
            "preset_id": "sulfur-shock",
            "feed": stable.feed.model_copy(update={"straight_run_sulfur_mass_pct": 1.08}),
        }
    )
    operator = sulfur_shock.model_copy(
        update={
            "preset_id": "operator-wins",
            "operator_controls": ModelledControls(p8=0.210010, t11=348.371910, f19=248.724499),
        }
    )
    missing = stable.model_copy(
        update={
            "preset_id": "missing-data",
            "feed": stable.feed.model_copy(
                update={"straight_run_sulfur_mass_pct": None, "age_minutes": 500}
            ),
        }
    )
    blend = stable.model_copy(
        update={
            "preset_id": "cetane-blending",
            "feed": stable.feed.model_copy(update={"cetane_number": 44}),
            "tanks": (
                _fresh(),
                BlendComponent(
                    component_id="cetane_stock",
                    name="Резервуар с повышенным ЦЧ",
                    available_tonnes=400,
                    sulfur_mg_kg=6,
                    t95_c=342,
                    cetane_number=52,
                    relative_cost=1.08,
                ),
            ),
            "additive_ppm": 1000.0,
        }
    )
    return (
        ModelledPreset(
            preset_id="stable-k5",
            name="Стабильный K5",
            description="Качество проходит ограничения; изменение режима не требуется.",
            expected_status=DecisionStatus.NO_CHANGE,
            request=stable,
        ),
        ModelledPreset(
            preset_id="sulfur-shock",
            name="Рост серы прямогонного ДТ",
            description="Изменение сырья требует компенсирующего режима гидроочистки.",
            expected_status=DecisionStatus.CHANGE_RECOMMENDED,
            request=sulfur_shock,
        ),
        ModelledPreset(
            preset_id="operator-wins",
            name="Вариант оператора",
            description="Операторский вариант оценивается тем же путём и может победить.",
            expected_status=DecisionStatus.CHANGE_RECOMMENDED,
            request=operator,
        ),
        ModelledPreset(
            preset_id="missing-data",
            name="Нет свежих данных",
            description="Обязательный вход отсутствует или старше четырёх часов.",
            expected_status=DecisionStatus.INSUFFICIENT_DATA,
            request=missing,
        ),
        ModelledPreset(
            preset_id="cetane-blending",
            name="Блендинг и 2-EHN",
            description="Низкое цетановое число корректируется резервуаром и присадкой.",
            expected_status=DecisionStatus.NO_CHANGE,
            request=blend,
        ),
    )
