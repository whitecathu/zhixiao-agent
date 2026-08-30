from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class RunManifest(BaseModel):
    schema_version: str = "1.1"
    run_id: str
    prompt: str
    workspace: str
    status: str
    mode: str = "ask"
    permission: str = "read_only"
    runner: str = "local"
    approval_policy: str = "on_request"
    budget: dict[str, Any] = Field(default_factory=dict)
    allow_unverified: str | None = None
    verification_commands: list[str] = Field(default_factory=list)
    command_timeout: int = 120
    ops_capabilities: list[str] = Field(default_factory=list)
    network_capabilities: list[str] = Field(default_factory=list)
    trusted_workspace: bool = False
    remote: bool = False
    api_url: str | None = None
    repository_id: int | None = None
    parent_run_id: str | None = None
    session_name: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    result: dict[str, Any] = Field(default_factory=dict)


class SessionStore:
    def __init__(self, state_dir: Path):
        self.root = state_dir.expanduser().resolve() / "runs"

    def save(self, manifest: RunManifest) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        manifest.updated_at = datetime.now(UTC)
        target = self.root / f"{manifest.run_id}.json"
        temporary = target.with_suffix(f".tmp-{os.getpid()}")
        temporary.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(target)
        return target

    def get(self, run_id: str) -> RunManifest | None:
        path = self.root / f"{run_id}.json"
        if not path.is_file():
            return None
        return RunManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[RunManifest]:
        if not self.root.is_dir():
            return []
        manifests: list[RunManifest] = []
        for path in self.root.glob("*.json"):
            try:
                manifests.append(RunManifest.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return sorted(manifests, key=lambda item: item.updated_at, reverse=True)

    def delete(self, run_id: str) -> bool:
        path = self.root / f"{run_id}.json"
        if not path.is_file():
            return False
        path.unlink()
        return True


def result_payload(result: Any) -> dict[str, Any]:
    if hasattr(result, "model_dump"):
        raw = result.model_dump(mode="json")
    elif isinstance(result, dict):
        raw = dict(result)
    else:
        raise TypeError("result must be a model or mapping")
    raw.setdefault("schema_version", "1.1")
    raw.setdefault("next_actions", [])
    raw.setdefault("termination_reason", None)
    raw.setdefault("usage", {})
    raw.setdefault("budgets", {})
    raw.setdefault("verification", _legacy_verification(raw))
    return dict(raw)


def _legacy_verification(raw: dict[str, Any]) -> dict[str, Any]:
    command = raw.get("test_command")
    exit_code = raw.get("test_exit_code")
    if command is None:
        return {"outcome": "skipped", "reason": "no verification command was selected"}
    return {
        "outcome": "passed" if exit_code == 0 else "failed",
        "command": command,
        "exit_code": exit_code,
    }
