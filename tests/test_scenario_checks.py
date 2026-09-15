"""Stage B uses explicitly synthetic units/ranges/agents, never production fallbacks."""

from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from pydantic import ValidationError

from neftecode_hackathon.contracts import (
    Action,
    ActionOrigin,
    Admissibility,
    Applicability,
    ContractExample,
    MeasurementQuality,
    ProcessSnapshot,
)
from neftecode_hackathon.orchestration import Coordinator
from neftecode_hackathon.reliability import UnavailableReliabilityAgent
from neftecode_hackathon.scenarios import ScenarioEvaluator
from neftecode_hackathon.scenarios.config import ScenarioPolicy, load_policy


@pytest.fixture
def setup():
    example = ContractExample.model_validate_json(
        Path("examples/contract_v1.synthetic.json").read_text()
    )
    snapshot_data = example.snapshot.model_dump()
    raw = load_policy().model_dump()
    for c, unit, current, minimum, maximum, step in zip(
        raw["catalogue"]["controls"],
        ["synthetic-C", "synthetic-t/h", "synthetic-MPa"],
        [150.0, 250.0, 5.0],
        [100.0, 200.0, 1.0],
        [200.0, 300.0, 10.0],
        [1.0, 2.0, 0.1],
        strict=True,
    ):
        c.update(
            canonical_unit=unit,
            unit_verified=True,
            action_support_verified=True,
            support_model_version=example.evaluation.model_version,
            available=True,
            unavailable_reason=None,
            model_min=minimum,
            model_max=maximum,
            step=step,
            provenance=dict(
                kind="train",
                source="Synthetic train split only",
                dataset_version=example.snapshot.dataset_version,
                available_at=example.snapshot.as_of - timedelta(days=1),
                train_end=example.snapshot.as_of - timedelta(days=2),
            ),
        )
        m = example.snapshot.values["ht:F26"].model_dump()
        m.update(unit=unit, value=current)
        snapshot_data["values"][c["signal_id"]] = m
    raw["constraints"].update(
        model_inputs_verified=True,
        model_version=example.evaluation.model_version,
        required_inputs=[
            dict(signal_id="pak:ht.product_sulfur", unit="mg/kg", max_age_seconds=1200)
        ],
        hard_check_inventory_verified=True,
        hard_check_inventory_evidence="Synthetic test inventory",
        minimum_interval_coverage=0.9,
        limitations=[],
    )
    return example, snapshot_data, raw


class TestQualityAgent:
    __test__ = False

    def __init__(self, quality):
        self.quality = quality
        self.calls = []

    def assess(self, snapshot, action, horizon_minutes):
        self.calls.append((snapshot, action, horizon_minutes))
        return self.quality


class TestReliabilityAgent(UnavailableReliabilityAgent):
    __test__ = False

    def __init__(self):
        self.calls = 0

    def assess(self, snapshot, action):
        self.calls += 1
        return super().assess(snapshot, action)


def evaluate(
    setup, changes=None, *, raw=None, snapshot_data=None, quality=None, origin=ActionOrigin.SYSTEM
):
    example, snapshot, config = setup
    agent = TestQualityAgent(quality or example.evaluation.quality)
    reliability = TestReliabilityAgent()
    evaluator = ScenarioEvaluator(
        agent,
        reliability,
        model_version=example.evaluation.model_version,
        policy=ScenarioPolicy.model_validate(raw or config),
    )
    snapshot = ProcessSnapshot.model_validate(snapshot_data or snapshot)
    action = Action(
        action_id=uuid4(), label="Synthetic action", origin=origin, changes=changes or {}
    )
    before = snapshot.model_dump_json()
    result = evaluator.evaluate(snapshot, action)
    assert snapshot.model_dump_json() == before
    return result, agent, reliability


def test_real_catalogue_confirmed_but_disabled(setup):
    policy = load_policy()
    assert {c.signal_id for c in policy.catalogue.controls} == {"ht:P8", "ht:T11", "ht:F19"}
    assert all(
        c.verification_status == "confirmed" and not c.available for c in policy.catalogue.controls
    )
    example = setup[0]
    agent = TestQualityAgent(
        example.evaluation.quality.model_copy(
            update={"model_version": policy.constraints.model_version}
        )
    )
    evaluator = ScenarioEvaluator(
        agent,
        UnavailableReliabilityAgent(),
        model_version=policy.constraints.model_version,
        policy=policy,
    )
    baseline = example.action.model_copy(update={"changes": {}})
    result = evaluator.evaluate(example.snapshot, baseline)
    assert result.admissibility is Admissibility.NOT_ASSESSABLE
    assert result.quality.applicability is Applicability.SUPPORTED
    assert len(agent.calls) == 1
    changed = baseline.model_copy(update={"changes": {"ht:P8": 0.2}})
    assert evaluator.evaluate(example.snapshot, changed).admissibility is Admissibility.REJECTED
    assert len(agent.calls) == 1


@pytest.mark.parametrize(
    "changes",
    [{}, {"ht:P8": 100.0}, {"ht:P8": 200.0}, {"ht:F19": 5.1}, {"ht:P8": 151.0, "ht:T11": 252.0}],
)
def test_valid_boundaries_and_absolute_changes(setup, changes):
    result, agent, _ = evaluate(setup, changes)
    assert result.admissibility is Admissibility.ADMISSIBLE
    assert len(agent.calls) == 1
    assert agent.calls[0][1].changes == changes
    assert agent.calls[0][0].values["ht:P8"].value == 150.0
    assert result.cost.value is None and result.throughput.value is None
    assert not result.reliability.transition_assessed


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"ht:unknown": 1.0}, "controls.unknown.ht:unknown"),
        ({"ht:F26": 252.0}, "controls.unknown.ht:F26"),
        ({"ht:P8": 99.0}, "controls.range.ht:P8"),
        ({"ht:P8": 201.0}, "controls.range.ht:P8"),
        ({"ht:T11": 251.0}, "controls.step.ht:T11"),
    ],
)
def test_invalid_candidate_never_calls_agents(setup, changes, code):
    result, agent, reliability = evaluate(setup, changes)
    assert result.admissibility is Admissibility.REJECTED
    assert any(c.code == code and c.passed is False for c in result.checks)
    assert not agent.calls and reliability.calls == 0
    assert result.quality.prediction is None


def test_baseline_outside_range_is_rejected(setup):
    snapshot = deepcopy(setup[1])
    snapshot["values"]["ht:P8"]["value"] = 500.0
    result, agent, _ = evaluate(setup, snapshot_data=snapshot)
    assert result.admissibility is Admissibility.REJECTED
    assert not agent.calls


@pytest.mark.parametrize("problem", ["missing", "null", "suspect", "unit", "stale", "false_age"])
def test_required_input_failure_stops_model(setup, problem):
    snapshot = deepcopy(setup[1])
    signal = "pak:ht.product_sulfur"
    m = snapshot["values"][signal]
    if problem == "missing":
        del snapshot["values"][signal]
    elif problem == "null":
        m.update(value=None, quality=MeasurementQuality.MISSING)
    elif problem == "suspect":
        m["quality"] = MeasurementQuality.SUSPECT
    elif problem == "unit":
        m["unit"] = "unknown"
    elif problem == "stale":
        m.update(measured_at=snapshot["as_of"] - timedelta(seconds=1201), age_seconds=1201)
    else:
        m["age_seconds"] = 0
    result, agent, _ = evaluate(setup, snapshot_data=snapshot)
    assert result.admissibility is Admissibility.NOT_ASSESSABLE
    assert result.quality.applicability is Applicability.INSUFFICIENT_DATA
    assert not agent.calls


def test_freshness_exact_boundary(setup):
    snapshot = deepcopy(setup[1])
    snapshot["values"]["pak:ht.product_sulfur"].update(
        measured_at=snapshot["as_of"] - timedelta(seconds=1200), age_seconds=1200
    )
    assert evaluate(setup, snapshot_data=snapshot)[0].admissibility is Admissibility.ADMISSIBLE


def test_forbidden_combination_stops_model(setup):
    raw = deepcopy(setup[2])
    raw["constraints"]["forbidden_combinations"] = [
        dict(
            code="policy.combination",
            signals=["ht:P8", "ht:T11"],
            evidence="Synthetic combination restriction",
        )
    ]
    result, agent, _ = evaluate(setup, {"ht:P8": 151.0, "ht:T11": 252.0}, raw=raw)
    assert result.admissibility is Admissibility.REJECTED
    assert not agent.calls


def limit(required=True):
    return dict(
        code="policy.pressure",
        signal_id="ht:F19",
        unit="synthetic-MPa",
        maximum=4.0,
        max_age_seconds=1200,
        required=required,
        category="reliability",
        evidence="Synthetic limit, not an industrial boundary",
    )


@pytest.mark.parametrize("required", [True, False])
def test_required_limit_vs_informative_failure(setup, required):
    raw = deepcopy(setup[2])
    raw["constraints"]["signal_limits"] = [limit(required)]
    result, agent, _ = evaluate(setup, raw=raw)
    assert result.admissibility is (
        Admissibility.REJECTED if required else Admissibility.ADMISSIBLE
    )
    assert bool(agent.calls) is not required
    assert any(c.code == "policy.pressure" and c.passed is False for c in result.checks)


def test_unknown_required_check_cannot_pass(setup):
    raw = deepcopy(setup[2])
    raw["constraints"]["signal_limits"] = [limit() | {"signal_id": "ht:missing"}]
    result, agent, _ = evaluate(setup, raw=raw)
    assert result.admissibility is Admissibility.NOT_ASSESSABLE
    assert not agent.calls


@pytest.mark.parametrize("required", [True, False])
def test_transition_policy_not_confused_with_severity(setup, required):
    raw = deepcopy(setup[2])
    raw["constraints"].update(
        transition_required=required, transition_evidence="Synthetic transition requirement"
    )
    result, _, _ = evaluate(setup, {"ht:P8": 151.0}, raw=raw)
    assert result.admissibility is (
        Admissibility.NOT_ASSESSABLE if required else Admissibility.ADMISSIBLE
    )
    assert result.reliability.severity_index is None


@pytest.mark.parametrize(
    "minutes,expected",
    [
        (None, Admissibility.NOT_ASSESSABLE),
        (2.0, Admissibility.REJECTED),
        (10.0, Admissibility.ADMISSIBLE),
    ],
)
def test_confirmed_ramp_uses_transition_duration_not_horizon(setup, minutes, expected):
    raw = deepcopy(setup[2])
    raw["catalogue"]["controls"][0].update(
        max_change_per_minute=1.0, ramp_evidence="Synthetic confirmed ramp"
    )
    raw["constraints"]["transition_minutes"] = minutes
    result, agent, _ = evaluate(setup, {"ht:P8": 154.0}, raw=raw)
    assert result.admissibility is expected
    assert bool(agent.calls) is (expected is Admissibility.ADMISSIBLE)


@pytest.mark.parametrize("field", ["available_at", "train_end"])
def test_future_range_is_not_used_for_replay(setup, field):
    raw = deepcopy(setup[2])
    provenance = raw["catalogue"]["controls"][0]["provenance"]
    provenance["available_at"] = setup[0].snapshot.as_of + timedelta(days=2)
    if field == "train_end":
        provenance[field] = setup[0].snapshot.as_of + timedelta(days=1)
    result, agent, _ = evaluate(setup, raw=raw)
    assert result.admissibility is Admissibility.REJECTED
    assert not agent.calls


@pytest.mark.parametrize("changes", [{}, {"ht:P8": 151.0}, {"ht:P8": 999.0}])
def test_origin_does_not_affect_checks_or_metrics(setup, changes):
    left = evaluate(setup, changes)[0]
    right = evaluate(setup, changes, origin=ActionOrigin.OPERATOR)[0]
    assert left.model_dump(exclude={"evaluation_id", "action"}) == right.model_dump(
        exclude={"evaluation_id", "action"}
    )


@pytest.mark.parametrize(
    "updates,expected",
    [
        ({"upper": 10.0}, Admissibility.ADMISSIBLE),
        ({"upper": 10.01}, Admissibility.REJECTED),
        ({"interval_coverage_target": None}, Admissibility.NOT_ASSESSABLE),
        ({"interval_coverage_target": 0.8}, Admissibility.REJECTED),
        ({"lower": -0.1}, Admissibility.REJECTED),
        ({"lower": None, "upper": None}, Admissibility.REJECTED),
        ({"prediction": float("nan")}, Admissibility.REJECTED),
    ],
)
def test_quality_policy_cannot_be_bypassed(setup, updates, expected):
    quality = setup[0].evaluation.quality.model_copy(update=updates)
    result = evaluate(setup, quality=quality)[0]
    assert result.admissibility is expected


def test_joint_model_support_failure_has_no_numbers(setup):
    quality = setup[0].evaluation.quality.model_copy(
        update=dict(
            applicability=Applicability.UNSUPPORTED,
            prediction=None,
            lower=None,
            upper=None,
            reasons=("Synthetic joint support failure",),
        )
    )
    result = evaluate(setup, {"ht:P8": 151.0}, quality=quality)[0]
    assert result.admissibility is Admissibility.NOT_ASSESSABLE
    assert result.quality.prediction is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_even_unvalidated_action_numbers_fail_at_boundary(setup, value):
    example = setup[0]
    agent = TestQualityAgent(example.evaluation.quality)
    evaluator = ScenarioEvaluator(
        agent,
        UnavailableReliabilityAgent(),
        model_version=example.evaluation.model_version,
        policy=ScenarioPolicy.model_validate(setup[2]),
    )
    action = example.action.model_copy(update={"changes": {"ht:P8": value}})
    with pytest.raises(ValidationError):
        evaluator.evaluate(ProcessSnapshot.model_validate(setup[1]), action)
    assert not agent.calls


@pytest.mark.parametrize(
    "damage", ["unit", "range", "step", "train_end", "version", "support", "ramp", "unknown_key"]
)
def test_invalid_configuration_is_rejected(setup, damage):
    raw = deepcopy(setup[2])
    c = raw["catalogue"]["controls"][0]
    if damage == "unit":
        c["canonical_unit"] = None
    elif damage == "range":
        c["model_min"] = 300.0
    elif damage == "step":
        c["step"] = 0
    elif damage == "train_end":
        c["provenance"]["train_end"] = None
    elif damage == "version":
        raw["catalogue"]["constraint_version"] = "wrong"
    elif damage == "support":
        c["action_support_verified"] = False
    elif damage == "ramp":
        c["max_change_per_minute"] = 1.0
    else:
        raw["constraints"]["ignore_quality"] = True
    with pytest.raises(ValidationError):
        ScenarioPolicy.model_validate(raw)


def test_loader_rejects_duplicate_keys_and_unsafe_yaml(tmp_path):
    controls = tmp_path / "controls.yaml"
    constraints = tmp_path / "constraints.yaml"
    constraints.write_text(
        Path("config/constraints.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    controls.write_text(
        "constraint_version: a\nconstraint_version: b\ncontrols: []\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="Duplicate YAML key"):
        load_policy(controls, constraints)
    controls.write_text("!!python/object/apply:os.system ['false']", encoding="utf-8")
    with pytest.raises(yaml.constructor.ConstructorError):
        load_policy(controls, constraints)


def test_loader_reads_utf8_policy_on_windows(tmp_path):
    controls = tmp_path / "controls.yaml"
    constraints = tmp_path / "constraints.yaml"
    controls.write_text(Path("config/controls.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    constraints.write_text(
        Path("config/constraints.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )

    policy = load_policy(controls, constraints)

    assert policy.catalogue.controls[0].name == "Полисеп. Р-202. Температура ГСС на входе"


@pytest.mark.parametrize(
    "problem", ["dataset", "support_model", "duplicate", "false_boolean", "relax_sulfur"]
)
def test_version_and_configuration_bypass_protection(setup, problem):
    raw = deepcopy(setup[2])
    if problem == "dataset":
        raw["catalogue"]["controls"][0]["provenance"]["dataset_version"] = "future-data"
        result, agent, _ = evaluate(setup, raw=raw)
        assert result.admissibility is Admissibility.REJECTED
        assert not agent.calls
        return
    if problem == "support_model":
        raw["catalogue"]["controls"][0]["support_model_version"] = "other-model"
    elif problem == "duplicate":
        raw["catalogue"]["controls"] = (
            *raw["catalogue"]["controls"],
            raw["catalogue"]["controls"][0],
        )
    elif problem == "false_boolean":
        raw["catalogue"]["controls"][0]["available"] = "false"
    else:
        raw["constraints"]["sulfur_upper_limit"] = 11
    with pytest.raises(ValidationError):
        ScenarioPolicy.model_validate(raw)


def test_assessed_transition_is_not_a_safety_result(setup):
    example = setup[0]
    raw = deepcopy(setup[2])
    raw["constraints"].update(transition_required=True, transition_evidence="Synthetic requirement")

    class AssessedReliability(UnavailableReliabilityAgent):
        def assess(self, snapshot, action):
            return super().assess(snapshot, action).model_copy(update={"transition_assessed": True})

    evaluator = ScenarioEvaluator(
        TestQualityAgent(example.evaluation.quality),
        AssessedReliability(),
        model_version=example.evaluation.model_version,
        policy=ScenarioPolicy.model_validate(raw),
    )
    action = example.action.model_copy(update={"changes": {"ht:P8": 151.0}})
    result = evaluator.evaluate(ProcessSnapshot.model_validate(setup[1]), action)
    assert result.admissibility is Admissibility.NOT_ASSESSABLE
    assert result.reliability.transition_assessed is True


def test_coordinator_does_not_mislabel_feasible_options(setup):
    example = setup[0]
    evaluator = ScenarioEvaluator(
        TestQualityAgent(example.evaluation.quality),
        UnavailableReliabilityAgent(),
        model_version=example.evaluation.model_version,
        policy=ScenarioPolicy.model_validate(setup[2]),
    )
    with pytest.raises(NotImplementedError, match="D–E"):
        Coordinator(evaluator).decide(ProcessSnapshot.model_validate(setup[1]))


def test_c_proxy_integrates_without_fabricating_efficiency(setup):
    from neftecode_hackathon.reliability import SeverityProxyAgent
    from neftecode_hackathon.scenarios.config import SeverityPolicy, load_severity_policy

    severity = load_severity_policy().model_dump()
    for factor, control in zip(severity["factors"], setup[2]["catalogue"]["controls"], strict=True):
        factor.update(
            unit=control["canonical_unit"],
            unit_verified=True,
            minimum=control["model_min"],
            maximum=control["model_max"],
            provenance=control["provenance"],
        )
    evaluator = ScenarioEvaluator(
        TestQualityAgent(setup[0].evaluation.quality),
        SeverityProxyAgent(SeverityPolicy.model_validate(severity)),
        model_version=setup[0].evaluation.model_version,
        policy=ScenarioPolicy.model_validate(setup[2]),
    )
    candidate = setup[0].action.model_copy(update={"changes": {"ht:P8": 160.0}})
    result = evaluator.evaluate(ProcessSnapshot.model_validate(setup[1]), candidate)
    assert result.reliability.severity_index is not None
    assert len(result.reliability.factors) == 3
    assert not result.reliability.transition_assessed
    assert result.throughput.value is result.cost.value is None
    assert result.admissibility is Admissibility.ADMISSIBLE


def test_future_measurement_in_unvalidated_snapshot_is_rejected(setup):
    example = setup[0]
    snapshot = ProcessSnapshot.model_validate(setup[1])
    measurement = snapshot.values["ht:P8"].model_copy(
        update={
            "available_at": snapshot.as_of + timedelta(seconds=1),
        }
    )
    snapshot.values["ht:P8"] = measurement
    agent = TestQualityAgent(example.evaluation.quality)
    evaluator = ScenarioEvaluator(
        agent,
        UnavailableReliabilityAgent(),
        model_version=example.evaluation.model_version,
        policy=ScenarioPolicy.model_validate(setup[2]),
    )
    with pytest.raises(ValidationError):
        evaluator.evaluate(snapshot, example.action)
    assert not agent.calls
