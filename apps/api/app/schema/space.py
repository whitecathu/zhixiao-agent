"""app/schema/space.py
团队空间请求/响应模型
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SpaceIn(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    description: Optional[str] = Field(None, max_length=255)


class SpaceUpdateIn(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=64)
    description: Optional[str] = None


class SpaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str]
    owner_id: int


class MemberIn(BaseModel):
    user_id: int
    role: str = Field("member", pattern="^(super_admin|space_admin|member)$")


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    space_id: int
    user_id: int
    role: str
