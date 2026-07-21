"""app/core/security.py
JWT 双令牌鉴权 + bcrypt 密码工具
- access  token: 短期 (默认 30 min)，业务接口鉴权
- refresh token: 长期 (默认 30 day)，仅 /auth/refresh 接口可用，单次轮换
- jti 唯一标识；登出加入黑名单；轮换时旧 refresh 撤销
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

import bcrypt
import jwt
from jwt import PyJWTError

from app.core.config import settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import BizException


ALGO = "HS256"


def hash_password(plain: str) -> str:
    """bcrypt 加密；自动带 salt"""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(user_id: int, extra: Optional[dict] = None) -> tuple[str, str]:
    """返回 (access_token, jti)"""
    jti = uuid.uuid4().hex
    payload = {
        "sub": str(user_id),
        "iss": settings.JWT_ISSUER,
        "iat": _now(),
        "exp": _now() + timedelta(minutes=settings.JWT_ACCESS_TTL_MIN),
        "type": "access",
        "jti": jti,
    }
    if extra:
        payload.update(extra)
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGO)
    return token, jti


def create_refresh_token(user_id: int) -> tuple[str, str, datetime]:
    """返回 (refresh_token, jti, expires_at)"""
    jti = uuid.uuid4().hex
    exp = _now() + timedelta(days=settings.JWT_REFRESH_TTL_DAY)
    payload = {
        "sub": str(user_id),
        "iss": settings.JWT_ISSUER,
        "iat": _now(),
        "exp": exp,
        "type": "refresh",
        "jti": jti,
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGO)
    return token, jti, exp


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGO], issuer=settings.JWT_ISSUER)
    except jwt.ExpiredSignatureError:
        raise BizException(ErrorCode.AUTH_TOKEN_EXPIRED, http_status=401)
    except PyJWTError:
        raise BizException(ErrorCode.AUTH_TOKEN_INVALID, http_status=401)


def decode_access_token(token: str) -> dict:
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise BizException(ErrorCode.AUTH_TOKEN_INVALID, http_status=401)
    return payload


def decode_refresh_token(token: str) -> dict:
    payload = decode_token(token)
    if payload.get("type") != "refresh":
        raise BizException(ErrorCode.AUTH_REFRESH_INVALID, http_status=401)
    return payload
