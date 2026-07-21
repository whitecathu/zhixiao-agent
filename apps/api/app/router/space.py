"""app/router/space.py
团队空间接口
"""

from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, Query

from app.core.middleware import RequireRole, get_current_user, get_space_id
from app.core.response import ApiResponse, PageResponse
from app.db.session import get_session
from app.schema.space import MemberIn, SpaceIn, SpaceOut, SpaceUpdateIn
from app.service.space_service import SpaceService

router = APIRouter(prefix="/api/v1/spaces", tags=["团队空间"])


@router.post("", response_model=ApiResponse[SpaceOut])
async def create_space(
    payload: SpaceIn, user=Depends(get_current_user), session=Depends(get_session)
):
    svc = SpaceService(session)
    out = await svc.create(user["user_id"], payload)
    return ApiResponse.success(out.model_dump())


@router.get("/mine", response_model=ApiResponse[list])
async def my_spaces(user=Depends(get_current_user), session=Depends(get_session)):
    svc = SpaceService(session)
    items = await svc.list_user_spaces(user["user_id"])
    return ApiResponse.success([i.model_dump() for i in items])


@router.put("/{space_id}", response_model=ApiResponse[SpaceOut])
async def update_space(
    space_id: int,
    payload: SpaceUpdateIn,
    user=Depends(get_current_user),
    session=Depends(get_session),
):
    svc = SpaceService(session)
    out = await svc.update(space_id, user["user_id"], payload)
    return ApiResponse.success(out.model_dump())


@router.post("/{space_id}/members", response_model=ApiResponse)
async def add_member(
    space_id: int, payload: MemberIn, user=Depends(get_current_user), session=Depends(get_session)
):
    svc = SpaceService(session)
    member = await svc.add_member(space_id, user["user_id"], payload)
    return ApiResponse.success({"id": member.id, "user_id": member.user_id, "role": member.role})


@router.get("/{space_id}/members", response_model=ApiResponse[list])
async def list_members(space_id: int, user=Depends(get_current_user), session=Depends(get_session)):
    svc = SpaceService(session)
    members = await svc.list_members(space_id, user["user_id"])
    return ApiResponse.success(
        [{"id": m.id, "user_id": m.user_id, "role": m.role} for m in members]
    )


@router.delete("/{space_id}/members/{member_user_id}", response_model=ApiResponse)
async def remove_member(
    space_id: int, member_user_id: int, user=Depends(get_current_user), session=Depends(get_session)
):
    svc = SpaceService(session)
    await svc.remove_member(space_id, user["user_id"], member_user_id)
    return ApiResponse.success()
