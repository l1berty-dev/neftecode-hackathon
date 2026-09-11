from neftecode_hackathon import cli, main


def test_main(capsys) -> None:
    main([])

    assert "prepare" in capsys.readouterr().out


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
