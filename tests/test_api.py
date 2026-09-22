import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from neftecode_hackathon.api import create_app
from neftecode_hackathon.api.models import (
    ControlResponse,
    ControlsResponse,
    DecisionResponse,
    EpisodeResponse,
    EpisodesResponse,
)
from neftecode_hackathon.api.service import RequestError
from neftecode_hackathon.contracts import ContractExample


def _example() -> ContractExample:
    return ContractExample.model_validate_json(
        Path("examples/contract_v1.synthetic.json").read_text(encoding="utf-8")
    )


class StubService:
    def __init__(self) -> None:
        self.example = _example()
        self.last_decision_request = None

    def controls(self) -> ControlsResponse:
        return ControlsResponse(
            constraint_version="constraints:test",
            controls=(
                ControlResponse(
                    signal_id="ht:P8",
                    label="Test control",
                    available=False,
                    reason="Not verified",
                    unit=None,
                    min=None,
                    max=None,
                    step=None,
                    source="test",
                ),
            ),
            review_issues=(),
        )

    def episodes(self) -> EpisodesResponse:
        snapshot = self.example.snapshot
        return EpisodesResponse(
            version="replay:test",
            episodes=(
                EpisodeResponse(
                    episode_id="test-episode",
                    name="Test",
                    start=snapshot.as_of,
                    end=snapshot.as_of,
                    step_minutes=10,
                    synthetic=True,
                    limitations=("test only",),
                ),
            ),
        )

    def create_decision(self, snapshot_id, changes, label) -> DecisionResponse:
        self.last_decision_request = (snapshot_id, changes, label)
        if changes and set(changes) - {"ht:P8"}:
            raise RequestError("Unknown control signal IDs.", {"signal_ids": ["ht:UNKNOWN"]})
        return DecisionResponse(
            decision=self.example.decision,
            current_snapshot_id=self.example.snapshot.snapshot_id,
            stale=False,
        )


def test_openapi_contains_the_shared_http_contract() -> None:
    schema = create_app(StubService()).openapi()
    paths = set(schema["paths"])

    assert paths == {
        "/api/v1/health",
        "/api/v1/controls",
        "/api/v1/episodes",
        "/api/v1/replay/start",
        "/api/v1/replay/advance",
        "/api/v1/snapshots/current",
        "/api/v1/snapshots/{snapshot_id}",
        "/api/v1/decisions",
        "/api/v1/decisions/{decision_id}",
        "/api/v1/decisions/{decision_id}/save",
        "/api/v1/scenarios/evaluate",
        "/api/v1/modelled-presets",
        "/api/v1/modelled-runs",
        "/api/v1/modelled-runs/{run_id}",
    }


def test_checked_in_openapi_matches_application() -> None:
    checked_in = json.loads(Path("examples/openapi.v1.json").read_text(encoding="utf-8"))

    assert checked_in == create_app().openapi()


def test_health_and_controls_are_explicit_about_readiness() -> None:
    with TestClient(create_app(StubService())) as client:
        health = client.get("/api/v1/health")
        controls = client.get("/api/v1/controls")

    assert health.status_code == 200
    assert health.json() == {
        "ready": True,
        "model_ready": True,
        "data_ready": True,
        "database_ready": True,
        "issues": [],
    }
    assert controls.status_code == 200
    assert controls.json()["controls"][0]["available"] is False


def test_decision_request_uses_server_owned_action_metadata() -> None:
    service = StubService()
    snapshot_id = service.example.snapshot.snapshot_id
    with TestClient(create_app(service)) as client:
        response = client.post(
            "/api/v1/decisions",
            json={
                "snapshot_id": str(snapshot_id),
                "horizon_minutes": 60,
                "operator_action": {"label": "Мой вариант", "changes": {"ht:P8": 1.0}},
            },
        )

    assert response.status_code == 200
    assert service.last_decision_request == (snapshot_id, {"ht:P8": 1.0}, "Мой вариант")
    assert response.json()["stale"] is False


def test_invalid_horizon_and_unknown_fields_return_structured_422() -> None:
    with TestClient(create_app(StubService())) as client:
        response = client.post(
            "/api/v1/decisions",
            json={
                "snapshot_id": str(uuid4()),
                "horizon_minutes": 30,
                "operator_action": None,
                "model_path": "forbidden",
            },
        )

    assert response.status_code == 422
    assert response.json()["code"] == "request_validation"


def test_unknown_signal_error_has_no_internal_details() -> None:
    service = StubService()
    with TestClient(create_app(service)) as client:
        response = client.post(
            "/api/v1/decisions",
            json={
                "snapshot_id": str(service.example.snapshot.snapshot_id),
                "operator_action": {"changes": {"ht:UNKNOWN": 1.0}},
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_request",
        "message": "Unknown control signal IDs.",
        "details": {"signal_ids": ["ht:UNKNOWN"]},
    }
