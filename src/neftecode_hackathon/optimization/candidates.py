"""Bounded, deterministic absolute actions, never fictional control permissions."""

import json
from decimal import Decimal
from itertools import product
from math import isfinite
from uuid import NAMESPACE_URL, uuid5

from neftecode_hackathon.contracts import Action, ActionOrigin, ProcessSnapshot
from neftecode_hackathon.scenarios.checks import measurement_check
from neftecode_hackathon.scenarios.config import ScenarioPolicy


def action_key(
    action: Action, snapshot: ProcessSnapshot | None = None
) -> tuple[tuple[str, float], ...]:
    return tuple(
        sorted(
            (signal, value)
            for signal, value in action.changes.items()
            if snapshot is None
            or signal not in snapshot.values
            or value != snapshot.values[signal].value
        )
    )


def _make_action(snapshot: ProcessSnapshot, values: dict[str, float]) -> Action:
    identity = json.dumps(
        [str(snapshot.snapshot_id), sorted(values.items())], separators=(",", ":")
    )
    return Action(
        action_id=uuid5(NAMESPACE_URL, identity),
        origin=ActionOrigin.SYSTEM if values else ActionOrigin.BASELINE,
        label="Системный вариант" if values else "Сохранить настройки",
        changes=values,
    )


def baseline_action(snapshot: ProcessSnapshot) -> Action:
    return _make_action(snapshot, {})


def generate_candidates(snapshot: ProcessSnapshot, policy: ScenarioPolicy) -> tuple[Action, ...]:
    snapshot = ProcessSnapshot.model_validate(snapshot.model_dump())
    policy = ScenarioPolicy.model_validate(policy.model_dump())
    dimensions = []
    for control in sorted(policy.catalogue.controls, key=lambda c: c.signal_id):
        if not control.available:
            continue
        source = control.provenance
        if source.available_at > snapshot.as_of or (
            source.dataset_version is not None
            and source.dataset_version != snapshot.dataset_version
        ):
            continue
        if (
            measurement_check(
                snapshot,
                control.signal_id,
                control.canonical_unit,
                control.max_age_seconds,
                code="candidates.input",
            ).result.passed
            is not True
        ):
            continue
        current = Decimal(str(snapshot.values[control.signal_id].value))
        step, minimum, maximum = map(
            Decimal, map(str, (control.step, control.model_min, control.model_max))
        )
        choices = [None]  # current: omit unchanged values from the absolute action.
        for value in (current - step, current + step):
            position = (value - minimum) / step
            if minimum <= value <= maximum and abs(
                position - position.to_integral_value()
            ) <= Decimal("1e-9"):
                numeric = float(value)
                if isfinite(numeric) and numeric != float(current):
                    choices.append((control.signal_id, numeric))
        dimensions.append(choices)
    changes = {(): {}}
    for combination in product(*dimensions):
        values = dict(item for item in combination if item is not None)
        changes[tuple(sorted(values.items()))] = values
    return tuple(
        _make_action(snapshot, changes[key]) for key in sorted(changes, key=lambda k: (bool(k), k))
    )
