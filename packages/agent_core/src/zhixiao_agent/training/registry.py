from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RegisteredModel:
    name: str
    version: int
    adapter_path: str
    metrics: dict[str, float]
    base_model: str = ""
    created_at: str = ""


RegisteredModels = list[RegisteredModel]
RegistryEntries = list[dict[str, Any]]


class FileModelRegistry:
    """Small auditable registry for local and CI training workflows."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def register(
        self,
        name: str,
        adapter_path: str | Path,
        metrics: dict[str, float],
        *,
        base_model: str = "",
    ) -> RegisteredModel:
        if not name.strip():
            raise ValueError("Model name must not be empty")
        entries = self._load()
        version = 1 + max(
            (int(entry["version"]) for entry in entries if entry["name"] == name), default=0
        )
        model = RegisteredModel(
            name=name,
            version=version,
            adapter_path=str(adapter_path),
            metrics=dict(metrics),
            base_model=base_model,
            created_at=datetime.now(UTC).isoformat(),
        )
        entries.append(asdict(model))
        self._atomic_write(entries)
        return model

    def latest(self, name: str) -> RegisteredModel | None:
        candidates = [entry for entry in self._load() if entry["name"] == name]
        if not candidates:
            return None
        return RegisteredModel(**max(candidates, key=lambda item: int(item["version"])))

    def list(self, name: str | None = None) -> RegisteredModels:
        return [
            RegisteredModel(**entry)
            for entry in self._load()
            if name is None or entry["name"] == name
        ]

    def _load(self) -> RegistryEntries:
        try:
            content = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        try:
            value = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid model registry: {self.path}") from exc
        if not isinstance(value, list):
            raise ValueError(f"Invalid model registry: {self.path}")
        return value

    def _atomic_write(self, entries: RegistryEntries) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
