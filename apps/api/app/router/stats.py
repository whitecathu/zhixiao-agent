"""app/router/stats.py
工作台 / 统计 / 链路回溯 接口
"""

from fastapi import APIRouter, Depends

from app.core.middleware import get_current_user, get_space_id
from app.core.response import ApiResponse
from app.db.session import get_session
from app.service.stats_service import StatsService

router = APIRouter(prefix="/api/v1/stats", tags=["统计与回溯"])


@router.get("/overview", response_model=ApiResponse)
async def overview(
    user=Depends(get_current_user), space_id=Depends(get_space_id), session=Depends(get_session)
):
    svc = StatsService(session)
    return ApiResponse.success(await svc.space_overview(space_id))


@router.get("/agents", response_model=ApiResponse[list])
async def agents(
    user=Depends(get_current_user), space_id=Depends(get_space_id), session=Depends(get_session)
):
    svc = StatsService(session)
    return ApiResponse.success(await svc.agent_dashboard(space_id))


@router.get("/recent-tasks", response_model=ApiResponse[list])
async def recent_tasks(
    user=Depends(get_current_user), space_id=Depends(get_space_id), session=Depends(get_session)
):
    svc = StatsService(session)
    return ApiResponse.success(await svc.recent_tasks(space_id))


@router.get("/tasks/{task_id}/replay", response_model=ApiResponse[list])
async def replay(
    task_id: int,
    user=Depends(get_current_user),
    space_id=Depends(get_space_id),
    session=Depends(get_session),
):
    svc = StatsService(session)
    return ApiResponse.success(await svc.task_log_replay(task_id))
