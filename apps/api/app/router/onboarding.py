"""Resumable onboarding endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.middleware import get_current_user, get_space_id
from app.core.response import ApiResponse
from app.db.session import get_session
from app.schema.onboarding import (
    OnboardingConfigOut,
    OnboardingConfigUpdate,
    OnboardingStateOut,
)
from app.service.onboarding_service import OnboardingService

router = APIRouter(prefix="/api/v1/onboarding", tags=["上手引导"])

SpaceId = Annotated[int, Depends(get_space_id)]
CurrentUser = Annotated[dict[str, Any], Depends(get_current_user)]
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/me", response_model=ApiResponse[OnboardingStateOut])
async def get_my_onboarding(
    space_id: SpaceId,
    user: CurrentUser,
    session: Session,
) -> ApiResponse[OnboardingStateOut]:
    data = await OnboardingService(session).get_state(user["user_id"], space_id)
    return ApiResponse.success(data.model_dump())


@router.post("/me/steps/{step_id}/complete", response_model=ApiResponse[OnboardingStateOut])
async def complete_onboarding_step(
    step_id: str,
    space_id: SpaceId,
    user: CurrentUser,
    session: Session,
) -> ApiResponse[OnboardingStateOut]:
    data = await OnboardingService(session).complete_step(user["user_id"], space_id, step_id)
    return ApiResponse.success(data.model_dump())


@router.post("/me/skip", response_model=ApiResponse[OnboardingStateOut])
async def skip_onboarding(
    space_id: SpaceId,
    user: CurrentUser,
    session: Session,
) -> ApiResponse[OnboardingStateOut]:
    data = await OnboardingService(session).skip(user["user_id"], space_id)
    return ApiResponse.success(data.model_dump())


@router.post("/me/replay", response_model=ApiResponse[OnboardingStateOut])
async def replay_onboarding(
    space_id: SpaceId,
    user: CurrentUser,
    session: Session,
) -> ApiResponse[OnboardingStateOut]:
    data = await OnboardingService(session).replay(user["user_id"], space_id)
    return ApiResponse.success(data.model_dump())


@router.get("/config", response_model=ApiResponse[OnboardingConfigOut])
async def get_onboarding_config(
    space_id: SpaceId,
    user: CurrentUser,
    session: Session,
) -> ApiResponse[OnboardingConfigOut]:
    data = await OnboardingService(session).get_config(user["user_id"], space_id)
    return ApiResponse.success(data.model_dump())


@router.put("/config", response_model=ApiResponse[OnboardingConfigOut])
async def update_onboarding_config(
    payload: OnboardingConfigUpdate,
    space_id: SpaceId,
    user: CurrentUser,
    session: Session,
) -> ApiResponse[OnboardingConfigOut]:
    data = await OnboardingService(session).update_config(
        user["user_id"], space_id, payload
    )
    return ApiResponse.success(data.model_dump())
