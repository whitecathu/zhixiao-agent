from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class ModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = "deepseek"
    model: str = "deepseek-chat"
    api_base: str = "https://api.deepseek.com/v1"
    api_key_env: str = "LLM_API_KEY"


class AgentSettings(BaseModel):
    """Effective CLI settings. Secrets are resolved from environment variables only."""

    model_config = ConfigDict(extra="forbid")

    profile: str = "default"
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-chat"
    llm_api_base: str = "https://api.deepseek.com/v1"
    llm_api_key_env: str = "LLM_API_KEY"
    llm_fallback_provider: str = ""
    llm_fallback_model: str = ""
    llm_fallback_api_base: str = ""
    llm_fallback_api_key_env: str = "LLM_FALLBACK_API_KEY"
    runner_backend: str = "local"
    command_timeout_seconds: int = Field(default=120, ge=1)
    api_url: str = ""
    api_token_env: str = "ZHIXIAO_API_TOKEN"  # noqa: S105 - environment variable name
    space_id: int = Field(default=1, ge=1)
    state_dir: Path = Field(default_factory=lambda: Path.home() / ".zhixiao")
    trusted_workspaces: list[Path] = Field(default_factory=list)
    profiles: dict[str, ModelSettings] = Field(default_factory=dict)

    @field_validator("runner_backend")
    @classmethod
    def validate_runner(cls, value: str) -> str:
        if value not in {"local", "docker", "bubblewrap"}:
            raise ValueError("runner_backend must be local, docker, or bubblewrap")
        return value

    @property
    def llm_api_key(self) -> str:
        return os.environ.get(self.llm_api_key_env, "")

    @property
    def llm_fallback_api_key(self) -> str:
        return os.environ.get(self.llm_fallback_api_key_env, "")

    @property
    def api_token(self) -> str:
        return os.environ.get(self.api_token_env, "")

    def redacted(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload["llm_api_key"] = "********" if self.llm_api_key else ""
        payload["llm_fallback_api_key"] = "********" if self.llm_fallback_api_key else ""
        payload["api_token"] = "********" if self.api_token else ""
        return payload


_ALLOWED_TOP_LEVEL = set(AgentSettings.model_fields)
_SECRET_KEYS = {"llm_api_key", "llm_fallback_api_key", "api_token", "token", "api_key"}


def user_config_path() -> Path:
    override = os.environ.get("ZHIXIAO_CONFIG_FILE")
    return Path(override).expanduser() if override else Path.home() / ".zhixiao" / "config.toml"


def project_config_path(workspace: Path) -> Path:
    return workspace.resolve() / ".zhixiao" / "config.toml"


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    forbidden = _SECRET_KEYS & set(payload)
    if forbidden:
        names = ", ".join(sorted(forbidden))
        raise ValueError(f"secrets are not allowed in {path}: {names}; use *_env references")
    unknown = set(payload) - _ALLOWED_TOP_LEVEL
    if unknown:
        raise ValueError(f"unknown settings in {path}: {', '.join(sorted(unknown))}")
    return payload


def _merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def _environment_values() -> dict[str, Any]:
    values: dict[str, Any] = {}
    legacy = {
        "LLM_PROVIDER": "llm_provider",
        "LLM_MODEL": "llm_model",
        "LLM_API_BASE": "llm_api_base",
        "LLM_FALLBACK_PROVIDER": "llm_fallback_provider",
        "LLM_FALLBACK_MODEL": "llm_fallback_model",
        "LLM_FALLBACK_API_BASE": "llm_fallback_api_base",
    }
    for field_name in AgentSettings.model_fields:
        env_name = f"ZHIXIAO_{field_name.upper()}"
        if env_name in os.environ and field_name not in {"profiles", "trusted_workspaces"}:
            values[field_name] = os.environ[env_name]
    for env_name, field_name in legacy.items():
        if env_name in os.environ and f"ZHIXIAO_{field_name.upper()}" not in os.environ:
            values[field_name] = os.environ[env_name]
    return values


def load_settings(
    workspace: Path | None = None,
    *,
    trusted_workspace: bool = False,
    profile: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> AgentSettings:
    values = _read_toml(user_config_path())
    if workspace is not None and trusted_workspace:
        values = _merge(values, _read_toml(project_config_path(workspace)))
    values = _merge(values, _environment_values())
    selected_profile = profile or str(values.get("profile", "default"))
    profiles = values.get("profiles", {})
    if selected_profile != "default" and selected_profile not in profiles:
        raise ValueError(f"unknown model profile: {selected_profile}")
    if selected_profile in profiles:
        selected = profiles[selected_profile]
        values = _merge(
            values,
            {
                "profile": selected_profile,
                "llm_provider": selected.get("provider", values.get("llm_provider")),
                "llm_model": selected.get("model", values.get("llm_model")),
                "llm_api_base": selected.get("api_base", values.get("llm_api_base")),
                "llm_api_key_env": selected.get(
                    "api_key_env", values.get("llm_api_key_env", "LLM_API_KEY")
                ),
            },
        )
    if overrides:
        values = _merge(
            values,
            {key: value for key, value in overrides.items() if value is not None},
        )
    try:
        return AgentSettings.model_validate(values)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def is_workspace_trusted(workspace: Path, settings: AgentSettings) -> bool:
    resolved = workspace.resolve()
    for configured in settings.trusted_workspaces:
        try:
            resolved.relative_to(configured.expanduser().resolve())
            return True
        except ValueError:
            continue
    return False


@lru_cache
def get_settings() -> AgentSettings:
    """Backward-compatible environment/user configuration accessor."""
    return load_settings()
