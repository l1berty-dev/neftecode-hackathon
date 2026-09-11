import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from neftecode_hackathon.contracts import ContractExample, Decision, ProcessSnapshot

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = ROOT / "examples" / "contract_v1.synthetic.json"
SCHEMA_PATH = ROOT / "examples" / "contract_v1.schema.json"


@pytest.fixture
def example_payload() -> dict:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def test_common_example_round_trips_without_information_loss(example_payload: dict) -> None:
    example = ContractExample.model_validate(example_payload)

    restored = ContractExample.model_validate_json(example.model_dump_json())

    assert restored == example
    assert restored.synthetic is True


def test_checked_in_schema_matches_contract(example_payload: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert schema == ContractExample.model_json_schema()
    assert example_payload["contract_version"] == 1


def test_snapshot_rejects_information_from_the_future(example_payload: dict) -> None:
    snapshot = example_payload["snapshot"]
    snapshot["values"]["ht:F26"]["available_at"] = "2026-01-15T09:01:00Z"

    with pytest.raises(ValidationError, match="information from the future"):
        ProcessSnapshot.model_validate(snapshot)


def test_decision_rejects_mixed_snapshots(example_payload: dict) -> None:
    decision = example_payload["decision"]
    decision["preferred"]["snapshot_id"] = "99999999-9999-4999-8999-999999999999"

    with pytest.raises(ValidationError, match="decision snapshot_id"):
        Decision.model_validate(decision)


def test_nan_is_rejected(example_payload: dict) -> None:
    example_payload["action"]["changes"]["ht:F26"] = float("nan")

    with pytest.raises(ValidationError):
        ContractExample.model_validate(example_payload)
