from typer.testing import CliRunner

from zhixiao_agent.cli import app


def test_doctor_command() -> None:
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "Python 3.11+" in result.stdout


def test_offline_readonly_run(tmp_path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "run",
            "--prompt",
            "review this repository",
            "--workspace",
            str(tmp_path),
            "--offline",
        ],
    )
    assert result.exit_code == 0
    assert "succeeded" in result.stdout
