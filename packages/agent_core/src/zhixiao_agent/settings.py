from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-chat"
    llm_api_base: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_fallback_provider: str = ""
    llm_fallback_model: str = ""
    llm_fallback_api_base: str = ""
    llm_fallback_api_key: str = ""
    runner_backend: str = "local"
    command_timeout_seconds: int = 120


@lru_cache
def get_settings() -> AgentSettings:
    return AgentSettings()
