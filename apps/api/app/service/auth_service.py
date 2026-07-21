"""app/service/auth_service.py
认证业务：注册 / 登录 / 登出 / 刷新令牌 / 修改密码
- refresh token 单次轮换；登出撤销；登录失败次数保护
"""

from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import BizException
from app.core.redis_client import (
    RedisClient,
    acquire_lock,
    rate_limit,
    release_lock,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from app.dao.user_dao import RefreshTokenDAO, UserDAO
from app.model.user import RefreshToken, User
from app.schema.auth import (
    ChangePasswordIn,
    LoginIn,
    RefreshIn,
    RegisterIn,
    TokenOut,
    UserOut,
)


class AuthService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.user_dao = UserDAO(session)
        self.rt_dao = RefreshTokenDAO(session)

    async def register(self, payload: RegisterIn) -> UserOut:
        if await self.user_dao.get_by_username(payload.username):
            raise BizException(ErrorCode.USER_EXISTS)
        if await self.user_dao.get_by_email(payload.email):
            raise BizException(ErrorCode.USER_EXISTS)
        if not _is_password_strong(payload.password):
            raise BizException(ErrorCode.USER_PASSWORD_WEAK)
        user = await self.user_dao.create(
            {
                "username": payload.username,
                "email": payload.email,
                "password_hash": hash_password(payload.password),
                "nickname": payload.nickname or payload.username,
            }
        )
        await self.session.commit()
        return UserOut.model_validate(user)

    async def login(self, payload: LoginIn) -> TokenOut:
        r = await RedisClient.get()
        # 锁定保护
        lock_value = await r.get(f"auth:lock:{payload.username}")
        if lock_value:
            raise BizException(ErrorCode.AUTH_USER_LOCKED, http_status=429)

        user = await self.user_dao.get_by_username(
            payload.username
        ) or await self.user_dao.get_by_email(payload.username)
        if not user or not verify_password(payload.password, user.password_hash):
            # 失败计数
            key = f"auth:fail:{payload.username}"
            ok = await rate_limit(key, settings.RATE_LIMIT_LOGIN_FAIL, 900)
            if not ok:
                await r.set(f"auth:lock:{payload.username}", "1", ex=900)
                raise BizException(ErrorCode.AUTH_USER_LOCKED, http_status=429)
            raise BizException(ErrorCode.AUTH_LOGIN_FAIL, http_status=401)
        if user.status != 1:
            raise BizException(ErrorCode.AUTH_USER_NOT_FOUND, http_status=403)

        # 颁发双令牌
        access, jti = create_access_token(user.id)
        refresh, rjti, exp = create_refresh_token(user.id)
        await self.rt_dao.create(
            {
                "user_id": user.id,
                "jti": rjti,
                "expires_at": exp,
            }
        )
        await self.user_dao.update_last_login(user.id)
        await self.session.commit()
        await r.delete(f"auth:fail:{payload.username}", f"auth:lock:{payload.username}")

        return TokenOut(
            access_token=access,
            refresh_token=refresh,
            expires_in=settings.JWT_ACCESS_TTL_MIN * 60,
            user=UserOut.model_validate(user),
        )

    async def refresh(self, payload: RefreshIn) -> TokenOut:
        decoded = decode_refresh_token(payload.refresh_token)
        rt = await self.rt_dao.get_by_jti(decoded["jti"])
        if not rt or rt.revoked:
            raise BizException(ErrorCode.AUTH_REFRESH_INVALID, http_status=401)
        if rt.expires_at < datetime.utcnow():
            raise BizException(ErrorCode.AUTH_REFRESH_EXPIRED, http_status=401)

        user = await self.user_dao.get(int(decoded["sub"]))
        if not user or user.status != 1:
            raise BizException(ErrorCode.AUTH_USER_NOT_FOUND, http_status=401)

        # 轮换：旧 rt 撤销，颁发新对
        access, _ = create_access_token(user.id)
        new_refresh, new_jti, exp = create_refresh_token(user.id)
        rt.revoked = 1
        await self.rt_dao.create(
            {
                "user_id": user.id,
                "jti": new_jti,
                "expires_at": exp,
            }
        )
        await self.session.commit()
        return TokenOut(
            access_token=access,
            refresh_token=new_refresh,
            expires_in=settings.JWT_ACCESS_TTL_MIN * 60,
            user=UserOut.model_validate(user),
        )

    async def logout(self, refresh_token: str, access_jti: str) -> None:
        decoded = decode_refresh_token(refresh_token)
        rt = await self.rt_dao.get_by_jti(decoded["jti"])
        if rt:
            rt.revoked = 1
        r = await RedisClient.get()
        await r.set(f"auth:blacklist:{access_jti}", "1", ex=settings.JWT_ACCESS_TTL_MIN * 60)
        await self.session.commit()

    async def change_password(self, user_id: int, payload: ChangePasswordIn) -> None:
        user = await self.user_dao.get(user_id)
        if not user or not verify_password(payload.old_password, user.password_hash):
            raise BizException(ErrorCode.AUTH_LOGIN_FAIL, http_status=401)
        if not _is_password_strong(payload.new_password):
            raise BizException(ErrorCode.USER_PASSWORD_WEAK)
        await self.user_dao.update(user_id, {"password_hash": hash_password(payload.new_password)})
        await self.session.commit()


def _is_password_strong(p: str) -> bool:
    if len(p) < 8:
        return False
    has_alpha = any(c.isalpha() for c in p)
    has_digit = any(c.isdigit() for c in p)
    return bool(has_alpha and has_digit)
