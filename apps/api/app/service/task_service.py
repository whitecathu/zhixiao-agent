"""app/service/task_service.py
任务业务：创建 / 查询 / 状态流转 / 控制指令 / 成果导出
- 创建同时调用 AI 引擎 submit()
- 幂等校验：客户端提供 request_token 或 X-Request-Token header
- 限流：每分钟每空间 30 个
"""

import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import BizException
from app.core.redis_client import (
    RedisClient,
    idempotency_get,
    idempotency_save,
    rate_limit,
    task_control_clear,
    task_control_set,
    task_state_get,
    task_state_set,
)
from app.dao.task_dao import AgentStepDAO, TaskDAO
from app.engine.abstract_engine import AbstractExecutionEngine
from app.schema.task import TaskCreateIn, TaskOut


TASK_RUNNING_STATES = {"pending", "running", "interrupted"}


class TaskService:
    def __init__(self, session: AsyncSession, engine: AbstractExecutionEngine | None = None):
        self.session = session
        self.engine = engine
        self.task_dao = TaskDAO(session)
        self.step_dao = AgentStepDAO(session)

    async def create(
        self,
        space_id: int,
        user_id: int,
        payload: TaskCreateIn,
        request_token: Optional[str] = None,
    ) -> TaskOut:
        # 限流
        ok = await rate_limit(
            f"ratelimit:task:create:{space_id}",
            settings.RATE_LIMIT_TASK_CREATE_PER_MIN,
            60,
        )
        if not ok:
            raise BizException(ErrorCode.SYSTEM_BUSY, http_status=429)

        # 幂等
        token = request_token or payload.request_token or uuid.uuid4().hex
        cached = await idempotency_get("task:create", token)
        if cached:
            from app.schema.task import TaskOut as _Out

            return _Out.model_validate_json(cached)

        task = await self.task_dao.create(
            {
                "space_id": space_id,
                "user_id": user_id,
                "title": payload.title,
                "goal": payload.goal,
                "attachments": payload.attachments,
                "priority": payload.priority,
                "template_id": payload.template_id,
                "status": "pending",
            }
        )

        # 异步调度
        from app.engine.registry import get_engine

        engine = self.engine or get_engine()
        execution_id = await engine.submit(
            task_id=str(task.id),
            goal=task.goal,
            context={
                "space_id": space_id,
                "user_id": user_id,
                "title": task.title,
                "task_id": task.id,
            },
        )
        await task_state_set(
            str(task.id),
            status="running",
            execution_id=execution_id,
            current_node="START",
            progress=0,
        )
        task.status = "running"
        await self.session.commit()

        out = TaskOut.model_validate(task)
        await idempotency_save("task:create", token, out.model_dump_json())
        return out

    async def get(self, task_id: int, space_id: int) -> TaskOut:
        task = await self.task_dao.get(task_id)
        if not task or task.space_id != space_id:
            raise BizException(ErrorCode.TASK_NOT_FOUND, http_status=404)
        return TaskOut.model_validate(task)

    async def list_by_space(
        self, space_id: int, *, page: int = 1, page_size: int = 20, status: Optional[str] = None
    ) -> tuple[list[TaskOut], int]:
        items, total = await self.task_dao.list_by_space(
            space_id,
            offset=(page - 1) * page_size,
            limit=page_size,
            status=status,
        )
        return [TaskOut.model_validate(t) for t in items], total

    async def control(self, task_id: int, space_id: int, action: str) -> None:
        task = await self.task_dao.get(task_id)
        if not task or task.space_id != space_id:
            raise BizException(ErrorCode.TASK_NOT_FOUND, http_status=404)
        if action == "interrupt" and task.status != "running":
            raise BizException(ErrorCode.TASK_STATE_INVALID)
        if action == "resume" and task.status != "interrupted":
            raise BizException(ErrorCode.TASK_STATE_INVALID)

        state = await task_state_get(str(task.id))
        execution_id = state.get("execution_id") if state else None
        if not execution_id:
            raise BizException(ErrorCode.EXECUTION_NOT_RUNNING, http_status=400)

        from app.engine.registry import get_engine

        engine = self.engine or get_engine()
        if action == "interrupt":
            ok = await engine.interrupt(execution_id)
            if not ok:
                raise BizException(ErrorCode.EXECUTION_INTERRUPT_FAIL)
            await task_control_set(str(task.id), "stop")
            task.status = "interrupted"
        elif action == "resume":
            ok = await engine.resume(execution_id)
            if not ok:
                raise BizException(ErrorCode.EXECUTION_RESUME_FAIL)
            await task_control_clear(str(task.id))
            task.status = "running"
        await self.session.commit()

    async def get_log(self, task_id: int, space_id: int) -> list:
        task = await self.task_dao.get(task_id)
        if not task or task.space_id != space_id:
            raise BizException(ErrorCode.TASK_NOT_FOUND, http_status=404)
        steps = await self.step_dao.list_by_task(task_id)
        from app.schema.task import AgentStepOut

        return [AgentStepOut.model_validate(s) for s in steps]
