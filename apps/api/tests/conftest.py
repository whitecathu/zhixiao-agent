"""tests/conftest.py
pytest 配置：SQLite 异步 in-memory + Redis 模拟；为单测提供 client/session
"""
import asyncio
import os
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# 在创建 app 之前覆盖配置
os.environ.setdefault("JWT_SECRET", "test_secret_for_pytest_only")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("MYSQL_HOST", "localhost")
os.environ.setdefault("MYSQL_USER", "u")
os.environ.setdefault("MYSQL_PASSWORD", "p")
os.environ.setdefault("MYSQL_DATABASE", "d")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("WORKER_CALLBACK_TOKEN", "test-worker-token")

from app.db import session as session_mod  # noqa: E402
from app.db.session import Base  # noqa: E402
import app.model.user  # noqa: F401,E402
import app.model.task  # noqa: F401,E402
import app.model.knowledge  # noqa: F401,E402
import app.model.platform  # noqa: F401,E402


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncIterator:
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        yield s


@pytest_asyncio.fixture
async def client(engine) -> AsyncIterator[AsyncClient]:
    # 替换 get_session 依赖为内存引擎
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def _get_session():
        async with factory() as s:
            yield s

    from app.main import app
    from app.db.session import get_session as original
    app.dependency_overrides[original] = _get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    from app.core.events import EventBroker
    from app.core.redis_client import RedisClient
    await RedisClient.close()
    EventBroker._default = None
    from app.core.jobs import RunQueue
    RunQueue._default = None
