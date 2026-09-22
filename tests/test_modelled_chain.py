from pathlib import Path

import pytest

from neftecode_hackathon.contracts import (
    Admissibility,
    DecisionStatus,
    ModelledControls,
)
from neftecode_hackathon.modelled import ModelledChainEngine, build_presets
from neftecode_hackathon.modelled.blending import optimise_blend
from neftecode_hackathon.modelled.vak import calculate_avt_cfpp, calculate_vak


@pytest.fixture
def engine() -> ModelledChainEngine:
    return ModelledChainEngine.from_path(Path("config/modelled.yaml"))


def test_corrected_vak_t90_scales_f15_by_2000() -> None:
    result = calculate_vak({"T12": 300, "F15": 2000, "W7": 0, "T23": 250, "F1": 100, "F26": 1000})

    assert result.t90_c == pytest.approx(
        162.998 + 0.12945 * 300 + 59.57 + 0.26366 * 250 - 424.72638 * 0.1
    )
    assert result.t50_c is None


def test_vak_and_avt_formula_fail_closed_on_division_by_zero() -> None:
    vak = calculate_vak({"T12": 300, "F15": 2000, "W7": 0, "T23": 250, "F1": 100, "F26": 0})
    avt_value, avt_reason = calculate_avt_cfpp(
        {"T33": 1, "P67": 1, "P4": 1, "F65": 1, "F32": 0, "F30": 1}
    )

    assert vak.t90_c is None
    assert "деление на ноль" in vak.reasons[0]
    assert avt_value is None
    assert "ноль" in str(avt_reason)


def test_all_editable_presets_recalculate_to_documented_status(engine: ModelledChainEngine) -> None:
    for preset in build_presets():
        result = engine.run(preset.request)
        assert result.status is preset.expected_status
        assert result.request == preset.request
        assert result.model_version == engine.config["version"]


def test_same_operator_and_system_controls_have_identical_numbers(
    engine: ModelledChainEngine,
) -> None:
    request = build_presets()[0].request
    system = engine._evaluate_action(request, request.controls, "system", "system")
    operator = engine._evaluate_action(request, request.controls, "operator", "operator")

    assert system.quality == operator.quality
    assert system.severity_proxy == operator.severity_proxy
    assert system.energy_cost_proxy == operator.energy_cost_proxy


def test_outside_joint_support_is_not_assessable(engine: ModelledChainEngine) -> None:
    request = build_presets()[0].request.model_copy(
        update={"controls": ModelledControls(p8=10, t11=10, f19=10)}
    )

    result = engine.run(request)

    assert result.status is DecisionStatus.INSUFFICIENT_DATA
    assert result.baseline.admissibility is Admissibility.NOT_ASSESSABLE


def test_blending_uses_conservative_additive_effect(engine: ModelledChainEngine) -> None:
    request = build_presets()[4].request
    additive = engine.config["additive"]
    recipe = optimise_blend(
        request.tanks,
        request.specification,
        1000,
        min_additive_ppm=additive["min_supported_ppm"],
        max_additive_ppm=additive["max_supported_ppm"],
        nominal_cetane_per_1000=additive["nominal_cetane_per_1000_ppm"],
        conservative_cetane_per_1000=additive["conservative_cetane_per_1000_ppm"],
        additive_relative_cost=additive["relative_cost_per_tonne"],
    )

    assert sum(share.fraction for share in recipe.shares) == pytest.approx(1)
    assert recipe.quality.cetane_number_nominal == pytest.approx(
        recipe.quality.cetane_number_conservative + 1
    )
    assert all(check.passed is True for check in recipe.checks)


def test_additive_above_3000_ppm_is_not_assessable(engine: ModelledChainEngine) -> None:
    request = build_presets()[0].request.model_copy(update={"additive_ppm": 3001})

    result = engine.run(request)

    assert result.status is DecisionStatus.NO_FEASIBLE_OPTION
    assert result.blend.admissibility is Admissibility.NOT_ASSESSABLE
