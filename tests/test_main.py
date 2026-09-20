from pathlib import Path

from neftecode_hackathon import cli, main
from neftecode_hackathon.api import service as api_service
from neftecode_hackathon.contracts import ContractExample


def test_main(capsys) -> None:
    main([])

    output = capsys.readouterr().out
    assert "prepare" in output
    assert "train" in output
    assert "evaluate" in output
    assert "serve" in output


def test_prepare_command_routes_to_pipeline(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "prepare_data",
        lambda **kwargs: {
            "dataset_version": "sha256:test",
            "outputs": {"telemetry_rows": 1, "analysis_rows": 2, "event_rows": 3},
        },
    )

    main(["prepare"])

    assert "Prepared dataset sha256:test" in capsys.readouterr().out


def test_train_command_routes_to_pipeline(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "train_forecast",
        lambda **kwargs: {
            "manifest": {
                "model_version": "forecast-v1:test",
                "selected_predictor": "persistence_baseline",
            },
            "metrics": {
                "validation": {"selected": {"mae": 1.0}},
                "test": {"selected": {"mae": 2.0}},
            },
        },
    )

    main(["train"])

    assert "Trained model forecast-v1:test" in capsys.readouterr().out


def test_evaluate_command_uses_shared_runtime(monkeypatch, capsys) -> None:
    example = ContractExample.model_validate_json(
        Path("examples/contract_v1.synthetic.json").read_text(encoding="utf-8")
    )

    class Runtime:
        def decide_at(self, at):
            assert at.isoformat() == "2026-08-06T21:00:00+00:00"
            return example.decision

    monkeypatch.setattr(api_service, "build_calculation_runtime", lambda: Runtime())

    main(["evaluate", "--at", "2026-08-06T21:00:00Z"])

    assert str(example.decision.decision_id) in capsys.readouterr().out
