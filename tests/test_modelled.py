from pathlib import Path

import pytest

from neftecode_hackathon.contracts import ActionOrigin, DecisionStatus
from neftecode_hackathon.modelled import (
    ModelledChainEngine,
    build_presets,
    evaluate_avt_vak,
    evaluate_hydrotreating_vak,
    train_modelled_response,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def engine() -> ModelledChainEngine:
    return ModelledChainEngine.from_repository(ROOT)


def test_all_presets_produce_the_documented_status(engine: ModelledChainEngine) -> None:
    for preset in build_presets():
        assert engine.run(preset.request).status is preset.expected_status


def test_operator_option_uses_the_same_evaluation_path_and_can_win(
    engine: ModelledChainEngine,
) -> None:
    result = engine.run(build_presets()[2].request)

    assert result.status is DecisionStatus.CHANGE_RECOMMENDED
    assert result.preferred is not None
    assert result.preferred.origin is ActionOrigin.OPERATOR


def test_missing_required_fact_fails_closed(engine: ModelledChainEngine) -> None:
    result = engine.run(build_presets()[3].request)

    assert result.status is DecisionStatus.INSUFFICIENT_DATA
    assert result.baseline is not None
    assert result.baseline.admissibility.value == "not_assessable"
    assert any(check.passed is not True for check in result.hard_checks)


def test_baseline_and_operator_with_equal_controls_have_equal_numbers(
    engine: ModelledChainEngine,
) -> None:
    request = build_presets()[0].request.model_copy(
        update={"operator_controls": build_presets()[0].request.controls}
    )
    result = engine.run(request)
    operator = next(item for item in result.alternatives if item.origin is ActionOrigin.OPERATOR)

    assert result.baseline is not None
    assert operator.quality == result.baseline.quality
    assert operator.energy_cost_proxy == result.baseline.energy_cost_proxy


def test_corrected_vak_formulae_preserve_grouping_and_missingness() -> None:
    avt = evaluate_avt_vak({"T33": 350, "P67": 0.2, "P4": 0.3, "F65": 20, "F32": 100, "F30": 5})
    missing = evaluate_avt_vak({})
    ht = evaluate_hydrotreating_vak({"P13": 4, "F9": 250, "T6": 150})

    assert avt.cfpp_c == pytest.approx(6.24713)
    assert missing.cfpp_c is None
    assert ht.t50_c == pytest.approx(172.8171)
    assert ht.t90_c is None


def test_response_audit_is_explicitly_non_causal(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    manifest = train_modelled_response(ROOT)

    assert manifest["causal_claim"] is False
    assert manifest["coefficients"] == {"p8": 0.0, "t11": 0.0, "f19": 0.0}
    assert (tmp_path / "modelled_manifest.json").is_file()


def test_blending_hard_checks_cannot_be_bypassed(engine: ModelledChainEngine) -> None:
    original = build_presets()[0].request
    bad_tanks = tuple(
        tank.model_copy(
            update={
                "component_id": f"offspec_{index}",
                "sulfur_mg_kg": 100.0,
            }
        )
        for index, tank in enumerate(original.tanks)
    )
    request = original.model_copy(update={"tanks": bad_tanks})
    result = engine.run(request)

    assert result.status is DecisionStatus.NO_FEASIBLE_OPTION
    assert any(
        check.code == "product_sulfur" and check.passed is False for check in result.hard_checks
    )
