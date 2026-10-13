"""The command line, end to end with the offline mock."""

from govlab.cli import main
from govlab.store import list_runs


def test_run_analyze_list_and_resume(tmp_path, capsys):
    assert (
        main(
            [
                "run",
                "--mock",
                "--games",
                "2",
                "--name",
                "cli test",
                "--concurrency",
                "4",
                "--runs",
                str(tmp_path),
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "4 conditions x 2 games = 8 games" in out and "completed: 8/8 valid games" in out

    (store,) = list_runs(tmp_path)
    for produced in (
        "manifest.json",
        "tables/games.csv",
        "analysis/report.md",
        "analysis/results.json",
        "analysis/figures/F1_win_rate.png",
        "analysis/figures/F5_detection.pdf",
    ):
        assert (store.path / produced).exists(), produced
    report = (store.path / "analysis" / "report.md").read_text()
    assert "Offline mock run" in report and "## Confirmatory tests" in report

    assert main(["analyze", str(store.path)]) == 0
    assert "# cli test" in capsys.readouterr().out
    assert main(["list", "--runs", str(tmp_path)]) == 0
    assert "cli-test" in capsys.readouterr().out
    assert main(["resume", str(store.path)]) == 0  # nothing left to play is not an error


def test_pilot_is_five_games_per_condition_and_settings_can_be_overridden(tmp_path, capsys):
    code = main(
        [
            "run",
            "--mock",
            "--pilot",
            "--thresholds",
            "plurality",
            "--protocols",
            "freeform",
            "--set",
            "max_timesteps=8",
            "--no-analysis",
            "--runs",
            str(tmp_path),
        ]
    )
    assert code == 0
    (store,) = list_runs(tmp_path)
    assert store.spec.name == "pilot" and store.spec.games_per_condition == 5
    assert store.spec.game["max_timesteps"] == 8 and len(store.schedule) == 5


def test_check_without_a_key_says_what_is_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "no-profile"))
    monkeypatch.setattr("govlab.cli.load_dotenv", lambda *a, **k: None)
    assert main(["check"]) == 1
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().out


def test_bad_arguments_are_reported_not_raised(tmp_path, capsys):
    assert main(["analyze", str(tmp_path / "missing")]) == 2
    assert "not a run directory" in capsys.readouterr().err
