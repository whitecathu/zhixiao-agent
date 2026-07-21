"""app/core/redis_client.py
Redis 客户端单例 + 常用工具：限流、幂等、分布式锁、SSE 推送队列、任务运行态
"""

import asyncio
import json
import time
import uuid
from typing import Any, Optional

import redis.asyncio as redis
from redis.asyncio import Redis

from app.core.config import settings


class RedisClient:
    """全局异步 Redis 客户端单例"""

    _client: Any = None
    _lock = asyncio.Lock()

    @classmethod
    async def get(cls) -> Any:
        if cls._client is None:
            async with cls._lock:
                if cls._client is None:
                    if settings.APP_ENV == "test":
                        cls._client = MemoryRedis()
                    else:
                        cls._client = redis.from_url(
                            settings.redis_url,
                            decode_responses=True,
                            max_connections=settings.MYSQL_POOL_SIZE,
                        )
        return cls._client

    @classmethod
    async def close(cls) -> None:
        if cls._client is not None:
            await cls._client.close()
            cls._client = None


class MemoryRedis:
    """Small async Redis substitute used only by the isolated test profile."""

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}
        self._hashes: dict[str, dict[str, str]] = {}
        self._expires: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def _purge(self, key: str) -> None:
        expires = self._expires.get(key)
        if expires is not None and expires <= time.monotonic():
            self._values.pop(key, None)
            self._hashes.pop(key, None)
            self._expires.pop(key, None)

    async def get(self, key: str) -> Any:
        self._purge(key)
        return self._values.get(key)

    async def set(
        self, key: str, value: Any, *, nx: bool = False, ex: int | None = None
    ) -> bool | None:
        async with self._lock:
            self._purge(key)
            if nx and key in self._values:
                return None
            self._values[key] = str(value)
            if ex is not None:
                self._expires[key] = time.monotonic() + ex
            return True

    async def incr(self, key: str) -> int:
        async with self._lock:
            self._purge(key)
            value = int(self._values.get(key, 0)) + 1
            self._values[key] = str(value)
            return value

    async def expire(self, key: str, seconds: int) -> bool:
        self._expires[key] = time.monotonic() + seconds
        return True

    async def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            count += int(key in self._values or key in self._hashes)
            self._values.pop(key, None)
            self._hashes.pop(key, None)
            self._expires.pop(key, None)
        return count

    async def hset(self, key: str, *, mapping: dict[str, str]) -> int:
        self._hashes.setdefault(key, {}).update(mapping)
        return len(mapping)

    async def hgetall(self, key: str) -> dict[str, str]:
        self._purge(key)
        return dict(self._hashes.get(key, {}))

    async def eval(self, script: str, numkeys: int, key: str, holder: str) -> int:
        if await self.get(key) == holder:
            return await self.delete(key)
        return 0

    async def close(self) -> None:
        self._values.clear()
        self._hashes.clear()
        self._expires.clear()


# -------- 通用工具 --------
async def rate_limit(key: str, limit: int, window_sec: int) -> bool:
    """令牌桶 / 滑动窗口的简化：INCR + EXPIRE"""
    r = await RedisClient.get()
    cnt = await r.incr(key)
    if cnt == 1:
        await r.expire(key, window_sec)
    return cnt <= limit


async def idempotency_save(api: str, token: str, response: str, ttl: int = 86400) -> bool:
    """接口幂等：若 token 已存在返回 False，否则保存响应"""
    r = await RedisClient.get()
    key = f"idemp:{api}:{token}"
    ok = await r.set(key, response, nx=True, ex=ttl)
    return bool(ok)


async def idempotency_get(api: str, token: str) -> Optional[str]:
    r = await RedisClient.get()
    return await r.get(f"idemp:{api}:{token}")


async def acquire_lock(name: str, holder: Optional[str] = None, ttl: int = 30) -> Optional[str]:
    """分布式锁 - SET NX EX"""
    r = await RedisClient.get()
    holder = holder or uuid.uuid4().hex
    key = f"lock:{name}"
    ok = await r.set(key, holder, nx=True, ex=ttl)
    return holder if ok else None


async def release_lock(name: str, holder: str) -> bool:
    """解锁 - 校验持有者"""
    r = await RedisClient.get()
    key = f"lock:{name}"
    script = (
        "if redis.call('get', KEYS[1]) == ARGV[1] then "
        "  return redis.call('del', KEYS[1]) "
        "else return 0 end"
    )
    return bool(await r.eval(script, 1, key, holder))


# -------- 任务运行态 --------
async def task_state_set(task_id: str, **fields: Any) -> None:
    """写入任务运行态 Hash: status / execution_id / current_node / progress / last_event_ts"""
    r = await RedisClient.get()
    if not fields:
        return
    mapping = {
        k: json.dumps(v) if isinstance(v, (dict, list)) else str(v) for k, v in fields.items()
    }
    mapping["last_event_ts"] = str(int(time.time()))
    await r.hset(f"task:run:{task_id}", mapping=mapping)


async def task_state_get(task_id: str) -> dict:
    r = await RedisClient.get()
    raw = await r.hgetall(f"task:run:{task_id}")
    return (
        {k: json.loads(v) if v.startswith(("{", "[")) else v for k, v in raw.items()} if raw else {}
    )


async def task_control_set(task_id: str, cmd: str) -> None:
    """控制命令: stop / pause / resume"""
    r = await RedisClient.get()
    await r.set(f"task:run:{task_id}:control", cmd, ex=86400)


async def task_control_get(task_id: str) -> Optional[str]:
    r = await RedisClient.get()
    return await r.get(f"task:run:{task_id}:control")


async def task_control_clear(task_id: str) -> None:
    r = await RedisClient.get()
    await r.delete(f"task:run:{task_id}:control")


# -------- SSE 推送队列 --------
async def sse_publish(task_id: str, event: str, data: Any) -> None:
    """Compatibility publisher; new consumers read the Redis Stream by cursor."""
    from app.core.events import EventBroker

    normalized = data if isinstance(data, dict) else {"value": data}
    await EventBroker.default().publish(task_id, event, normalized)


async def sse_pop(task_id: str, block_sec: int = 5) -> Optional[dict]:
    """Compatibility one-shot read; prefer EventBroker.read with an explicit cursor."""
    from app.core.events import EventBroker

    events = await EventBroker.default().read(task_id, after="0-0", block_ms=block_sec * 1000)
    if not events:
        return None
    item = events[0]
    return {"id": item.id, "event": item.event, "data": item.data}
