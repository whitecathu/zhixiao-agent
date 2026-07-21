"""app/core/middleware.py
链路追踪 trace_id 中间件 + 限流中间件 + 鉴权依赖
"""

import time
import uuid
from typing import Callable, Optional

from fastapi import Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.config import settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import BizException
from app.core.redis_client import rate_limit
from app.core.security import decode_access_token


class TraceIdMiddleware(BaseHTTPMiddleware):
    """为每个请求注入 trace_id；若 Header 已携带则沿用"""

    async def dispatch(self, request, call_next):
        trace_id = request.headers.get("X-Trace-Id") or uuid.uuid4().hex[:16]
        request.state.trace_id = trace_id
        start = time.perf_counter()
        response: Response = await call_next(request)
        duration_ms = int((time.perf_counter() - start) * 1000)
        response.headers["X-Trace-Id"] = trace_id
        response.headers["X-Duration-Ms"] = str(duration_ms)
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """简单接口限流（按路径 + IP）"""

    async def dispatch(self, request, call_next):
        path = request.url.path
        # 仅限动态接口；SSE/静态放行
        if path.startswith("/api"):
            ip = request.client.host if request.client else "anon"
            key = f"ratelimit:{path}:{ip}"
            ok = await rate_limit(key, limit=120, window_sec=60)
            if not ok:
                raise BizException(ErrorCode.RATE_LIMITED, http_status=429)
        return await call_next(request)


bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request, cred: Optional[HTTPAuthorizationCredentials] = Security(bearer)
) -> dict:
    """JWT 鉴权依赖；返回 {user_id, jti, payload}"""
    if not cred or cred.scheme.lower() != "bearer":
        raise BizException(ErrorCode.AUTH_TOKEN_MISSING, http_status=401)
    payload = decode_access_token(cred.credentials)
    # 黑名单校验（登出后的 access token）
    from app.core.redis_client import RedisClient

    r = await RedisClient.get()
    in_blacklist = await r.get(f"auth:blacklist:{payload['jti']}")
    if in_blacklist:
        raise BizException(ErrorCode.AUTH_TOKEN_INVALID, http_status=401)
    return {
        "user_id": int(payload["sub"]),
        "jti": payload["jti"],
        "payload": payload,
    }


async def get_space_id(request: Request, user: dict = Depends(get_current_user)) -> int:
    """空间隔离依赖：业务接口强制要求 X-Space-Id Header"""
    space_header = request.headers.get("X-Space-Id")
    if not space_header:
        raise BizException(ErrorCode.SPACE_NOT_FOUND, http_status=400)
    try:
        space_id = int(space_header)
    except ValueError:
        raise BizException(ErrorCode.PARAM_INVALID, http_status=400)
    # 实际项目中需校验该用户是否为该空间成员（在 service 层进行）
    request.state.space_id = space_id
    return space_id


class RequireRole:
    """RBAC 权限注解依赖"""

    def __init__(self, roles: tuple[str, ...]):
        self.roles = roles

    async def __call__(self, user: dict = Depends(get_current_user)) -> dict:
        role = user.get("payload", {}).get("role")
        if role not in self.roles:
            raise BizException(ErrorCode.AUTH_PERMISSION_DENIED, http_status=403)
        return user
