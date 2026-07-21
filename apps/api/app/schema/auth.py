"""app/schema/auth.py
认证模块的请求/响应 Pydantic 模型
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, ConfigDict


# ---- 请求 ----
class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    nickname: Optional[str] = Field(None, max_length=64)


class LoginIn(BaseModel):
    username: str = Field(..., description="用户名或邮箱")
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class LogoutIn(BaseModel):
    """登出可选传 access_token（由依赖自动取），refresh_token 必传"""

    refresh_token: str


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8, max_length=128)


# ---- 响应 ----
class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    email: str
    nickname: Optional[str]
    avatar_url: Optional[str]
    last_login_at: Optional[datetime]


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int  # 秒
    user: UserOut
