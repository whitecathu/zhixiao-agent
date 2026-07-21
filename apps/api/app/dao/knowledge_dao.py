"""app/dao/knowledge_dao.py"""

from typing import Optional
from sqlalchemy import select, or_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.dao.base import BaseDAO
from app.model.knowledge import (
    KnowledgeItem,
    KnowledgeTag,
    KnowledgeCategory,
    ToolInvocation,
    TaskStatsDaily,
    AgentMetric,
)


class KnowledgeDAO(BaseDAO[KnowledgeItem]):
    model = KnowledgeItem

    async def list_by_space(
        self,
        space_id: int,
        *,
        type: Optional[str] = None,
        category_path: Optional[str] = None,
        tag: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[KnowledgeItem], int]:
        filters = [KnowledgeItem.space_id == space_id]
        if type:
            filters.append(KnowledgeItem.type == type)
        if category_path:
            filters.append(KnowledgeItem.category_path == category_path)
        return await self.list(offset=offset, limit=limit, filters=filters)

    async def keyword_search(
        self, space_id: int, keyword: str, *, limit: int = 20
    ) -> list[KnowledgeItem]:
        """简化关键词搜索：基于 title/content LIKE（实际项目可用 FULLTEXT）"""
        res = await self.session.execute(
            select(KnowledgeItem)
            .where(
                KnowledgeItem.space_id == space_id,
                or_(
                    KnowledgeItem.title.like(f"%{keyword}%"),
                    KnowledgeItem.content.like(f"%{keyword}%"),
                    KnowledgeItem.summary.like(f"%{keyword}%"),
                ),
                KnowledgeItem.status == "active",
            )
            .limit(limit)
            .order_by(KnowledgeItem.usage_count.desc())
        )
        return list(res.scalars().all())

    async def increment_usage(self, ids: list[int]) -> None:
        from datetime import datetime

        await self.session.execute(
            text(
                "UPDATE knowledge_items SET usage_count=usage_count+1, last_used_at=NOW() "
                "WHERE id IN :ids"
            ).bindparams(ids=tuple(ids))
            if ids
            else text("SELECT 1")
        )


class TagDAO(BaseDAO[KnowledgeTag]):
    model = KnowledgeTag


class CategoryDAO(BaseDAO[KnowledgeCategory]):
    model = KnowledgeCategory


class ToolInvocationDAO(BaseDAO[ToolInvocation]):
    model = ToolInvocation


class StatsDAO:
    """日聚合读取"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def space_total(
        self, space_id: int, stat_date: Optional[str] = None
    ) -> Optional[TaskStatsDaily]:
        if stat_date is None:
            res = await self.session.execute(
                select(TaskStatsDaily)
                .where(TaskStatsDaily.space_id == space_id)
                .order_by(TaskStatsDaily.stat_date.desc())
                .limit(1)
            )
            return res.scalar_one_or_none()
        res = await self.session.execute(
            select(TaskStatsDaily).where(
                TaskStatsDaily.space_id == space_id, TaskStatsDaily.stat_date == stat_date
            )
        )
        return res.scalar_one_or_none()

    async def agent_summary(self, space_id: int, limit: int = 20) -> list[AgentMetric]:
        res = await self.session.execute(
            select(AgentMetric).where(AgentMetric.space_id == space_id).limit(limit)
        )
        return list(res.scalars().all())
