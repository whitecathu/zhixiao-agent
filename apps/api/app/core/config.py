"""app/core/config.py
应用配置 - 基于 pydantic-settings v2，支持环境变量与 .env 文件加载。
所有敏感信息必须从环境变量注入，绝不硬编码。
"""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 应用
    APP_NAME: str = "zhixiao-backend"
    APP_ENV: str = Field("dev", pattern="^(dev|test|prod)$")
    APP_HOST: str = "0.0.0.0"  # noqa: S104 - intentional service bind default
    APP_PORT: int = 8000
    APP_DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    # Empty means stdout-only, which is safe for read-only containers. Operators
    # may opt in with a writable absolute path such as /tmp/zhixiao-api.log.
    LOG_FILE: str = ""

    # MySQL
    MYSQL_HOST: str
    MYSQL_PORT: int = 3306
    MYSQL_USER: str
    MYSQL_PASSWORD: str
    MYSQL_DATABASE: str
    MYSQL_POOL_SIZE: int = 10
    MYSQL_MAX_OVERFLOW: int = 20
    MYSQL_POOL_RECYCLE: int = 3600

    @property
    def mysql_dsn(self) -> str:
        """异步 MySQL DSN: asyncmy 驱动"""
        return (
            f"mysql+asyncmy://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}?charset=utf8mb4"
        )

    # Redis
    REDIS_HOST: str
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0

    @property
    def redis_url(self) -> str:
        auth = f":{quote(self.REDIS_PASSWORD, safe='')}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # Chroma
    CHROMA_HOST: str = "chroma"
    CHROMA_PORT: int = 8000
    CHROMA_COLLECTION: str = "knowledge_vectors"
    VECTOR_DIM: int = 1024

    # JWT
    JWT_SECRET: str
    JWT_ISSUER: str = "zhixiao"
    JWT_ACCESS_TTL_MIN: int = 30
    JWT_REFRESH_TTL_DAY: int = 30

    # 限流
    RATE_LIMIT_LOGIN_FAIL: int = 5
    RATE_LIMIT_TASK_CREATE_PER_MIN: int = 30

    # AI 引擎
    AI_ENGINE_BASE_URL: str = "http://localhost:8001"
    AI_ENGINE_TIMEOUT: int = 120
    WORKER_CALLBACK_TOKEN: str = ""
    WORKER_JOB_SIGNING_SECRET: str = ""
    RUNNER_ROOT: str = "/workspace/runs"
    WORKSPACE_SOURCE_ROOTS: str = ""
    LLM_PROVIDER: str = "deepseek"

    # CORS
    CORS_ORIGINS: str | list[str] = "http://localhost:5173"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_cors(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> Settings:
        if self.APP_ENV != "prod":
            return self
        weak_markers = {"change_me", "please_change_me_in_prod", "replace"}
        if len(self.JWT_SECRET) < 32 or any(marker in self.JWT_SECRET for marker in weak_markers):
            raise ValueError("JWT_SECRET must be a high-entropy production secret")
        if len(self.WORKER_CALLBACK_TOKEN) < 32:
            raise ValueError("WORKER_CALLBACK_TOKEN must be at least 32 characters in prod")
        if len(self.WORKER_JOB_SIGNING_SECRET) < 32:
            raise ValueError("WORKER_JOB_SIGNING_SECRET must be at least 32 characters in prod")
        if not self.REDIS_PASSWORD:
            raise ValueError("REDIS_PASSWORD is required in prod")
        return self

    # 业务
    REVIEW_MAX_ROUNDS: int = 2
    TASK_TOTAL_TIMEOUT_SEC: int = 1800  # 30min

    # 可观测性与 SLO。这里只保存聚合阈值，不接受用户、仓库或提示词作为标签。
    OBSERVABILITY_WINDOW_DAYS: int = Field(30, ge=1, le=365)
    SLO_TASK_SUCCESS_RATE_TARGET: float = Field(0.80, ge=0, le=1)
    SLO_FIRST_PASS_RATE_TARGET: float = Field(0.60, ge=0, le=1)
    SLO_P95_DURATION_SECONDS_TARGET: float = Field(1800.0, gt=0)
    SLO_MONTHLY_COST_BUDGET_USD: float = Field(50.0, ge=0)


@lru_cache
def get_settings() -> Settings:
    """单例配置 — required fields are filled from env / .env at runtime."""
    return Settings()


settings = get_settings()
