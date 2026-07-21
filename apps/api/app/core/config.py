"""app/core/config.py
应用配置 - 基于 pydantic-settings v2，支持环境变量与 .env 文件加载。
所有敏感信息必须从环境变量注入，绝不硬编码。
"""

from functools import lru_cache
from typing import List, Union
from pydantic import AnyHttpUrl, Field, field_validator
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
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

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
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
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

    # CORS
    CORS_ORIGINS: Union[str, List[str]] = "http://localhost:5173"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_cors(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    # 业务
    REVIEW_MAX_ROUNDS: int = 2
    TASK_TOTAL_TIMEOUT_SEC: int = 1800  # 30min


@lru_cache
def get_settings() -> Settings:
    """单例配置"""
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
