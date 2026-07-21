"""app/service/stats_service.py
工作台首页统计、复用率、Agent 画像
"""

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.dao.knowledge_dao import StatsDAO
from app.model.knowledge import AgentMetric, KnowledgeItem, ToolInvocation, TaskStatsDaily
from app.model.task import Task, AgentStep


class StatsService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.stats_dao = StatsDAO(session)

    async def space_overview(self, space_id: int) -> dict[str, Any]:
        today = date.today()
        last_30 = today - timedelta(days=30)

        total_tasks = (
            await self.session.scalar(
                select(func.count()).select_from(Task).where(Task.space_id == space_id)
            )
            or 0
        )
        succeeded = (
            await self.session.scalar(
                select(func.count())
                .select_from(Task)
                .where(Task.space_id == space_id, Task.status == "succeeded")
            )
            or 0
        )
        today_count = (
            await self.session.scalar(
                select(func.count())
                .select_from(Task)
                .where(Task.space_id == space_id, Task.created_at >= last_30)
            )
            or 0
        )
        knowledge_total = (
            await self.session.scalar(
                select(func.count())
                .select_from(KnowledgeItem)
                .where(KnowledgeItem.space_id == space_id, KnowledgeItem.status == "active")
            )
            or 0
        )
        reused = (
            await self.session.scalar(
                select(func.sum(KnowledgeItem.usage_count)).where(
                    KnowledgeItem.space_id == space_id, KnowledgeItem.status == "active"
                )
            )
            or 0
        )
        reuse_rate = float(reused) / float(knowledge_total) if knowledge_total else 0.0

        return {
            "total_tasks": int(total_tasks),
            "succeeded": int(succeeded),
            "tasks_last_30d": int(today_count),
            "knowledge_total": int(knowledge_total),
            "reuse_rate": round(reuse_rate, 4),
        }

    async def agent_dashboard(self, space_id: int) -> list[dict]:
        # 最近 7 天各 Agent 调用与成功率
        since = date.today() - timedelta(days=7)
        res = await self.session.execute(
            select(
                AgentStep.agent_name,
                func.count().label("invocations"),
                func.avg(AgentStep.duration_ms).label("avg_ms"),
            )
            .where(AgentStep.task_id.in_(select(Task.id).where(Task.space_id == space_id)))
            .group_by(AgentStep.agent_name)
        )
        out = []
        for row in res:
            out.append(
                {
                    "agent_name": row.agent_name,
                    "invocations": int(row.invocations or 0),
                    "avg_duration_ms": int(row.avg_ms or 0),
                }
            )
        return out

    async def recent_tasks(self, space_id: int, limit: int = 10) -> list[dict]:
        res = await self.session.execute(
            select(Task).where(Task.space_id == space_id).order_by(Task.id.desc()).limit(limit)
        )
        return [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in res.scalars().all()
        ]

    async def task_log_replay(self, task_id: int) -> list[dict]:
        """链路回溯：按 step_index 拉所有步骤"""
        res = await self.session.execute(
            select(AgentStep).where(AgentStep.task_id == task_id).order_by(AgentStep.step_index)
        )
        return [
            {
                "step_index": s.step_index,
                "agent_name": s.agent_name,
                "status": s.status,
                "tools_used": s.tools_used,
                "duration_ms": s.duration_ms,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "finished_at": s.finished_at.isoformat() if s.finished_at else None,
            }
            for s in res.scalars().all()
        ]
