"""app/router/task.py
任务接口
"""

from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from app.core.middleware import get_current_user, get_space_id
from app.core.response import ApiResponse, PageResponse
from app.db.session import get_session
from app.schema.task import ExecutionControlIn, TaskCreateIn, TaskOut
from app.service.task_service import TaskService
from app.engine.abstract_engine import AbstractExecutionEngine
from app.engine.registry import get_execution_engine

def add_legacy_task_deprecation_headers(response: Response) -> None:
    response.headers["Deprecation"] = "true"
    response.headers["Warning"] = (
        '299 - "Deprecated API: migrate to /api/v1/task-runs"'
    )
    response.headers["Link"] = '</api/v1/task-runs>; rel="successor-version"'


router = APIRouter(
    prefix="/api/v1/tasks",
    tags=["任务（旧版）"],
    dependencies=[Depends(add_legacy_task_deprecation_headers)],
    deprecated=True,
)


def get_task_service(
    session=Depends(get_session),
    engine: AbstractExecutionEngine = Depends(get_execution_engine),
) -> TaskService:
    return TaskService(session, engine)


@router.post("", response_model=ApiResponse[TaskOut])
async def create_task(
    payload: TaskCreateIn,
    request: Request,
    user=Depends(get_current_user),
    space_id=Depends(get_space_id),
    svc: TaskService = Depends(get_task_service),
    request_token: Optional[str] = Header(None, alias="X-Request-Token"),
):
    out = await svc.create(space_id, user["user_id"], payload, request_token)
    return ApiResponse.success(out.model_dump())


@router.get("/{task_id}", response_model=ApiResponse[TaskOut])
async def get_task(
    task_id: int,
    user=Depends(get_current_user),
    space_id=Depends(get_space_id),
    svc: TaskService = Depends(get_task_service),
):
    out = await svc.get(task_id, space_id)
    return ApiResponse.success(out.model_dump())


@router.get("", response_model=PageResponse)
async def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    user=Depends(get_current_user),
    space_id=Depends(get_space_id),
    svc: TaskService = Depends(get_task_service),
):
    items, total = await svc.list_by_space(space_id, page=page, page_size=page_size, status=status)
    return PageResponse.of(
        items=[i.model_dump() for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/{task_id}/control", response_model=ApiResponse)
async def control_task(
    task_id: int,
    payload: ExecutionControlIn,
    user=Depends(get_current_user),
    space_id=Depends(get_space_id),
    svc: TaskService = Depends(get_task_service),
):
    await svc.control(task_id, space_id, payload.action)
    return ApiResponse.success()


@router.get("/{task_id}/log", response_model=ApiResponse[list])
async def task_log(
    task_id: int,
    user=Depends(get_current_user),
    space_id=Depends(get_space_id),
    svc: TaskService = Depends(get_task_service),
):
    steps = await svc.get_log(task_id, space_id)
    return ApiResponse.success([s.model_dump() for s in steps])
