from neftecode_hackathon import cli, main


def test_main(capsys) -> None:
    main([])

    output = capsys.readouterr().out
    assert "prepare" in output
    assert "train" in output


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
