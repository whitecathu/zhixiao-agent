from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from zhixiao_agent.cli import app
from zhixiao_agent.extensions import McpConfigStore, expand_custom_command, load_hooks
from zhixiao_agent.settings import load_settings

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZHIXIAO_CONFIG_FILE", str(tmp_path / "user-config.toml"))
    monkeypatch.setenv("ZHIXIAO_STATE_DIR", str(tmp_path / "state"))


def test_run_accepts_positional_prompt_and_stable_json(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "检查 Unicode：你好",
            "--workspace",
            str(tmp_path),
            "--offline",
            "--output-format",
            "json",
            "--events",
            "none",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["schema_version"]
    assert payload["status"] == "succeeded"
    assert payload["verification"]["outcome"] == "skipped"
    assert payload["usage"]["model_turns"] >= 1


def test_root_positional_prompt_launches_tui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[str | None] = []
    monkeypatch.setattr(
        "zhixiao_agent.tui.launch",
        lambda initial_prompt=None, **kwargs: received.append(initial_prompt),
    )

    result = runner.invoke(app, ["fix", "the", "API"])

    assert result.exit_code == 0, result.output
    assert received == ["fix the API"]


def test_run_accepts_stdin_and_rejects_multiple_prompt_sources(tmp_path: Path) -> None:
    stdin = runner.invoke(
        app,
        ["run", "-", "--workspace", str(tmp_path), "--offline", "--json", "--events", "none"],
        input="review from stdin\n",
    )
    assert stdin.exit_code == 0
    assert json.loads(stdin.stdout)["status"] == "succeeded"

    invalid = runner.invoke(
        app,
        ["run", "one", "--prompt", "two", "--workspace", str(tmp_path), "--offline"],
    )
    assert invalid.exit_code == 2
    assert "exactly one prompt source" in invalid.output


def test_jsonl_last_line_is_result_and_stdout_is_machine_only(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "review this repository",
            "--workspace",
            str(tmp_path),
            "--offline",
            "--output-format",
            "jsonl",
        ],
    )

    assert result.exit_code == 0, result.output
    records = [json.loads(line) for line in result.stdout.splitlines()]
    assert records[-1]["event"] == "result"
    assert all(item["schema_version"] for item in records)
    assert [item["sequence"] for item in records[:-1]] == sorted(
        item["sequence"] for item in records[:-1]
    )


def test_untrusted_workspace_blocks_write_before_runtime(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "edit a file",
            "--workspace",
            str(tmp_path),
            "--permission",
            "edit",
            "--offline",
        ],
    )

    assert result.exit_code == 3
    assert "not trusted" in result.output


def test_layered_configuration_and_secret_redaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_config = tmp_path / "user-config.toml"
    user_config.write_text(
        'llm_model = "user-model"\nrunner_backend = "local"\n', encoding="utf-8"
    )
    workspace = tmp_path / "repo"
    (workspace / ".zhixiao").mkdir(parents=True)
    (workspace / ".zhixiao" / "config.toml").write_text(
        'llm_model = "project-model"\n', encoding="utf-8"
    )
    monkeypatch.setenv("ZHIXIAO_LLM_MODEL", "environment-model")
    monkeypatch.setenv("LLM_API_KEY", "super-secret")

    settings = load_settings(workspace, trusted_workspace=True)
    assert settings.llm_model == "environment-model"
    assert settings.redacted()["llm_api_key"] == "********"

    shown = runner.invoke(app, ["config", "show", "--workspace", str(workspace)])
    assert shown.exit_code == 0
    assert "super-secret" not in shown.stdout


def test_project_config_and_extensions_require_trust(tmp_path: Path) -> None:
    project = tmp_path / ".zhixiao"
    (project / "commands").mkdir(parents=True)
    (project / "commands" / "fix.md").write_text(
        "---\nname: fix\nmode: code\ntools: read_file,apply_patch\n---\nFix {{args}} safely.",
        encoding="utf-8",
    )
    (project / "hooks.toml").write_text(
        '[hooks]\nbefore_run = ["python verify.py"]\n', encoding="utf-8"
    )

    assert expand_custom_command("/fix bug", tmp_path, trusted=False) == "/fix bug"
    assert expand_custom_command("/fix bug", tmp_path, trusted=True) == "Fix bug safely."
    assert load_hooks(tmp_path, trusted=False) == {}
    assert load_hooks(tmp_path, trusted=True)["before_run"] == ["python verify.py"]


def test_mcp_crud_keeps_secret_values_out_of_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "state"
    monkeypatch.setenv("ZHIXIAO_STATE_DIR", str(state))
    added = runner.invoke(
        app,
        [
            "mcp",
            "add",
            "local",
            "--command",
            "python",
            "--env",
            "TOKEN=MCP_TOKEN",
            "--allow-tool",
            "search",
        ],
    )
    assert added.exit_code == 0, added.output
    payload = McpConfigStore(state).path.read_text(encoding="utf-8")
    assert "MCP_TOKEN" in payload
    assert "actual-secret" not in payload
    listed = runner.invoke(app, ["mcp", "list"])
    assert json.loads(listed.stdout)["local"]["env"] == {"TOKEN": "MCP_TOKEN"}
    removed = runner.invoke(app, ["mcp", "remove", "local"])
    assert removed.exit_code == 0
    assert McpConfigStore(state).load() == {}


def test_runs_list_and_show_use_persisted_manifest(tmp_path: Path) -> None:
    created = runner.invoke(
        app,
        [
            "run",
            "review persisted run",
            "--workspace",
            str(tmp_path),
            "--offline",
            "--json",
            "--events",
            "none",
        ],
    )
    run_id = json.loads(created.stdout)["run_id"]
    listed = runner.invoke(app, ["runs", "list", "--output-format", "json"])
    assert run_id in listed.stdout
    shown = runner.invoke(app, ["runs", "show", run_id])
    payload = json.loads(shown.stdout)
    assert payload["run_id"] == run_id
    assert payload["mode"] == "code"


def test_run_mode_ask_is_recorded_on_manifest(tmp_path: Path) -> None:
    created = runner.invoke(
        app,
        [
            "run",
            "ask-only inspection",
            "--workspace",
            str(tmp_path),
            "--offline",
            "--mode",
            "ask",
            "--json",
            "--events",
            "none",
        ],
    )
    assert created.exit_code == 0, created.output
    run_id = json.loads(created.stdout)["run_id"]
    shown = json.loads(runner.invoke(app, ["runs", "show", run_id]).stdout)
    assert shown["mode"] == "ask"


def test_doctor_json_uses_stable_envelope(tmp_path: Path) -> None:
    result = runner.invoke(app, ["doctor", "--workspace", str(tmp_path), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert any(item["name"] == "State directory" for item in payload["checks"])


def test_verbose_json_keeps_stdout_parseable(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "review this repository",
            "--workspace",
            str(tmp_path),
            "--offline",
            "--json",
            "--events",
            "none",
            "--verbose",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "succeeded"
    stderr = result.stderr or ""
    assert str(tmp_path.resolve()) in stderr
    assert "permission=read_only" in stderr
    assert "mode=code" in stderr
    assert "trusted=" in stderr
    assert "offline=True" in stderr


def test_interrupt_local_run_without_api_url(tmp_path: Path) -> None:
    created = runner.invoke(
        app,
        [
            "run",
            "review for interrupt",
            "--workspace",
            str(tmp_path),
            "--offline",
            "--json",
            "--events",
            "none",
        ],
    )
    assert created.exit_code == 0, created.output
    run_id = json.loads(created.stdout)["run_id"]

    interrupted = runner.invoke(app, ["interrupt", run_id])
    assert interrupted.exit_code == 0, interrupted.output
    payload = json.loads(interrupted.stdout)
    assert payload["schema_version"] == "1.1"
    assert payload["status"] == "interrupted"
    assert payload["run_id"] == run_id
    assert any("zhixiao resume" in action for action in payload["next_actions"])

    shown = json.loads(runner.invoke(app, ["runs", "show", run_id]).stdout)
    assert shown["schema_version"] == "1.1"
    assert shown["status"] == "interrupted"
