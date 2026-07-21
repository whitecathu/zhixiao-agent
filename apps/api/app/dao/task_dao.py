"""app/dao/task_dao.py"""

from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dao.base import BaseDAO
from app.model.task import Task, AgentStep, ExecutionCheckpoint


class TaskDAO(BaseDAO[Task]):
    model = Task

    async def list_by_space(
        self, space_id: int, *, offset: int = 0, limit: int = 20, status: Optional[str] = None
    ) -> tuple[list[Task], int]:
        filters = [Task.space_id == space_id]
        if status:
            filters.append(Task.status == status)
        return await self.list(offset=offset, limit=limit, filters=filters)


class AgentStepDAO(BaseDAO[AgentStep]):
    model = AgentStep

    async def list_by_task(self, task_id: int) -> list[AgentStep]:
        res = await self.session.execute(
            select(AgentStep).where(AgentStep.task_id == task_id).order_by(AgentStep.step_index)
        )
        return list(res.scalars().all())

    async def last_step_index(self, task_id: int) -> int:
        from sqlalchemy import func

        res = await self.session.scalar(
            select(func.max(AgentStep.step_index)).where(AgentStep.task_id == task_id)
        )
        return int(res or 0)


class CheckpointDAO(BaseDAO[ExecutionCheckpoint]):
    model = ExecutionCheckpoint

    async def latest(self, task_id: int) -> Optional[ExecutionCheckpoint]:
        res = await self.session.execute(
            select(ExecutionCheckpoint)
            .where(ExecutionCheckpoint.task_id == task_id)
            .order_by(ExecutionCheckpoint.id.desc())
            .limit(1)
        )
        return res.scalar_one_or_none()
