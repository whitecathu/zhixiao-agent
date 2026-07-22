"""Prometheus scrape and authenticated space observability endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.core.error_codes import ErrorCode
from app.core.exceptions import BizException
from app.core.metrics import METRICS_REGISTRY
from app.core.middleware import get_current_user, get_space_id
from app.core.response import ApiResponse
from app.db.session import get_session
from app.schema.observability import ObservabilitySummary
from app.service.observability_service import ObservabilityService
from app.service.space_service import SpaceService

router = APIRouter(tags=["可观测性"])


SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserDep = Annotated[dict[str, Any], Depends(get_current_user)]
SpaceIdDep = Annotated[int, Depends(get_space_id)]


def service(session: SessionDep) -> ObservabilityService:
    return ObservabilityService(session)


async def require_observability_admin(
    user: CurrentUserDep,
    space_id: SpaceIdDep,
    session: SessionDep,
) -> dict[str, Any]:
    allowed = await SpaceService(session).has_role(
        space_id, user["user_id"], (SpaceService.SPACE_ADMIN, SpaceService.SUPER_ADMIN)
    )
    if not allowed:
        raise BizException(ErrorCode.AUTH_PERMISSION_DENIED, http_status=403)
    return user


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    return Response(content=generate_latest(METRICS_REGISTRY), media_type=CONTENT_TYPE_LATEST)


@router.get(
    "/api/v1/observability/summary",
    response_model=ApiResponse[ObservabilitySummary],
)
async def summary(
    user: Annotated[dict[str, Any], Depends(require_observability_admin)],
    space_id: SpaceIdDep,
    svc: Annotated[ObservabilityService, Depends(service)],
    window: Annotated[str, Query(pattern="^(1h|24h|7d|30d)$")] = "24h",
) -> ApiResponse[ObservabilitySummary]:
    del user
    return ApiResponse.success(await svc.summary(space_id, window))
