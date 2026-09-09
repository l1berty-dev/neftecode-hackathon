from neftecode_hackathon import main


def test_main(capsys) -> None:
    main()

    assert capsys.readouterr().out == "Neftecode Hackathon\n"
