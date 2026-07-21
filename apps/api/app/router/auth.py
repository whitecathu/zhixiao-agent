"""app/router/auth.py
认证接口：注册 / 登录 / 登出 / 刷新 / 修改密码
"""

from typing import Optional

from fastapi import APIRouter, Depends, Header, Request

from app.core.middleware import get_current_user
from app.core.response import ApiResponse
from app.db.session import get_session
from app.schema.auth import (
    ChangePasswordIn,
    LoginIn,
    RefreshIn,
    RegisterIn,
    TokenOut,
    UserOut,
)
from app.service.auth_service import AuthService

router = APIRouter(prefix="/api/v1/auth", tags=["认证"])


@router.post("/register", response_model=ApiResponse[UserOut])
async def register(payload: RegisterIn, session=Depends(get_session)):
    """用户注册"""
    svc = AuthService(session)
    out = await svc.register(payload)
    return ApiResponse.success(out.model_dump())


@router.post("/login", response_model=ApiResponse[TokenOut])
async def login(payload: LoginIn, session=Depends(get_session)):
    """用户登录，返回双令牌"""
    svc = AuthService(session)
    out = await svc.login(payload)
    return ApiResponse.success(out.model_dump())


@router.post("/refresh", response_model=ApiResponse[TokenOut])
async def refresh(payload: RefreshIn, session=Depends(get_session)):
    """刷新令牌（轮换）"""
    svc = AuthService(session)
    out = await svc.refresh(payload)
    return ApiResponse.success(out.model_dump())


@router.post("/logout", response_model=ApiResponse)
async def logout(
    payload: RefreshIn, user: dict = Depends(get_current_user), session=Depends(get_session)
):
    """登出 - 同时撤销 refresh + access 黑名单"""
    svc = AuthService(session)
    await svc.logout(payload.refresh_token, access_jti=user["jti"])
    return ApiResponse.success()


@router.put("/password", response_model=ApiResponse)
async def change_password(
    payload: ChangePasswordIn, user: dict = Depends(get_current_user), session=Depends(get_session)
):
    svc = AuthService(session)
    await svc.change_password(user["user_id"], payload)
    return ApiResponse.success()


@router.get("/me", response_model=ApiResponse)
async def me(user: dict = Depends(get_current_user), session=Depends(get_session)):
    """当前用户信息"""
    from app.dao.user_dao import UserDAO

    u = await UserDAO(session).get(user["user_id"])
    return ApiResponse.success(UserOut.model_validate(u).model_dump() if u else None)
