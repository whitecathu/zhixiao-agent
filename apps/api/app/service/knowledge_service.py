"""app/service/knowledge_service.py
知识业务：CRUD / 标签 / 分类 / 混合检索 / 召回加权排序
"""

import json
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import ErrorCode
from app.core.exceptions import BizException
from app.dao.knowledge_dao import (
    CategoryDAO,
    KnowledgeDAO,
    TagDAO,
    StatsDAO,
    ToolInvocationDAO,
)
from app.model.knowledge import KnowledgeItem, KnowledgeCategory, KnowledgeTag
from app.schema.knowledge import (
    CategoryOut,
    KnowledgeOut,
    KnowledgeSearchIn,
    KnowledgeUpdateIn,
    SearchHit,
    TagOut,
)


class KnowledgeService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.dao = KnowledgeDAO(session)
        self.tag_dao = TagDAO(session)
        self.cat_dao = CategoryDAO(session)
        self.stats_dao = StatsDAO(session)
        self.tool_dao = ToolInvocationDAO(session)

    async def get(self, space_id: int, knowledge_id: int) -> KnowledgeOut:
        item = await self.dao.get(knowledge_id)
        if not item or item.space_id != space_id:
            raise BizException(ErrorCode.KNOWLEDGE_NOT_FOUND, http_status=404)
        return KnowledgeOut.model_validate(item)

    async def update(
        self, space_id: int, knowledge_id: int, payload: KnowledgeUpdateIn
    ) -> KnowledgeOut:
        item = await self.dao.get(knowledge_id)
        if not item or item.space_id != space_id:
            raise BizException(ErrorCode.KNOWLEDGE_NOT_FOUND, http_status=404)
        updated = await self.dao.update(knowledge_id, payload.model_dump(exclude_unset=True))
        await self.session.commit()
        return KnowledgeOut.model_validate(updated)

    async def delete(self, space_id: int, knowledge_id: int) -> None:
        item = await self.dao.get(knowledge_id)
        if not item or item.space_id != space_id:
            raise BizException(ErrorCode.KNOWLEDGE_NOT_FOUND, http_status=404)
        await self.dao.soft_delete(knowledge_id)
        await self.session.commit()

    # ---- 分类与标签 ----
    async def list_tags(self, space_id: int) -> list[TagOut]:
        from sqlalchemy import select

        res = await self.session.execute(
            select(KnowledgeTag).where(KnowledgeTag.space_id == space_id)
        )
        return [TagOut.model_validate(t) for t in res.scalars().all()]

    async def list_categories(self, space_id: int) -> list[CategoryOut]:
        from sqlalchemy import select

        res = await self.session.execute(
            select(KnowledgeCategory).where(KnowledgeCategory.space_id == space_id)
        )
        return [CategoryOut.model_validate(c) for c in res.scalars().all()]

    # ---- 混合检索 ----
    async def search(self, space_id: int, payload: KnowledgeSearchIn) -> dict:
        """
        混合召回：语义(Chroma) + 关键词(SQL LIKE) + 场景(命中同空间历史知识)
        加权融合排序：
        final = 0.45*sem + 0.20*kw + 0.15*scene + 0.10*quality + 0.10*time_decay
        """
        # 1. 语义召回（Chroma）-> 返回 knowledge_id / score / snippet
        sem_hits = await self._semantic_search(space_id, payload)

        # 2. 关键词召回（MySQL）
        kw_hits = await self.dao.keyword_search(space_id, payload.query, limit=20)

        # 3. 场景召回（同空间最近被用 10 条）
        from sqlalchemy import select

        recent = await self.session.execute(
            select(KnowledgeItem)
            .where(
                KnowledgeItem.space_id == space_id,
                KnowledgeItem.status == "active",
                KnowledgeItem.usage_count > 0,
            )
            .order_by(
                KnowledgeItem.last_used_at.desc().nullslast(),
                KnowledgeItem.usage_count.desc(),
            )
            .limit(10)
        )
        recent_items = list(recent.scalars().all())

        # 融合排序：以 knowledge_id 归集
        all_ids = (
            {h["knowledge_id"] for h in sem_hits}
            | {k.id for k in kw_hits}
            | {k.id for k in recent_items}
        )
        if not all_ids:
            return {"items": [], "total": 0}

        # 拉取元数据
        from sqlalchemy import select as _sel

        res = await self.session.execute(
            _sel(KnowledgeItem).where(KnowledgeItem.id.in_(list(all_ids)))
        )
        all_items: dict[int, KnowledgeItem] = {k.id: k for k in res.scalars().all()}

        def quality(it: KnowledgeItem) -> float:
            return float(it.quality_score or 0.5)

        def snippet_of(it: KnowledgeItem, query_lower: str) -> str:
            content = it.content or ""
            idx = content.lower().find(query_lower)
            if idx < 0:
                return content[:120]
            start = max(0, idx - 40)
            return ("..." if start > 0 else "") + content[start : start + 200] + "..."

        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).timestamp()

        hits: list[SearchHit] = []
        sem_map = {h["knowledge_id"]: h for h in sem_hits}
        kw_set = {k.id for k in kw_hits}
        recent_set = {k.id for k in recent_items}

        for kid, it in all_items.items():
            sem_score = sem_map.get(kid, {}).get("score", 0.0)
            kw_score = 1.0 if kid in kw_set else 0.0
            scene_score = 1.0 if kid in recent_set else 0.0
            qs = quality(it)
            last_ts = (
                it.last_used_at.timestamp()
                if it.last_used_at
                else it.created_at.timestamp()
                if it.created_at
                else now
            )
            time_decay = max(0.0, 1.0 - (now - last_ts) / (90 * 86400))
            final = (
                0.45 * sem_score
                + 0.20 * kw_score
                + 0.15 * scene_score
                + 0.10 * qs
                + 0.10 * time_decay
            )
            if not payload.include_low_quality and qs < 0.3:
                continue
            hits.append(
                SearchHit(
                    knowledge_id=kid,
                    score=round(final, 4),
                    title=it.title,
                    summary=it.summary,
                    snippet=snippet_of(it, payload.query.lower()),
                    tags=it.tags or [],
                    category_path=it.category_path,
                    quality_score=qs,
                    source_task_id=it.source_task_id,
                )
            )

        hits.sort(key=lambda h: h.score, reverse=True)
        offset = (payload.page - 1) * payload.page_size
        page_items = hits[offset : offset + payload.page_size]
        # 召回计数
        if page_items:
            await self.dao.increment_usage([h.knowledge_id for h in page_items])
            await self.session.commit()
        return {"items": [h.model_dump() for h in page_items], "total": len(hits)}

    async def _semantic_search(self, space_id: int, payload: KnowledgeSearchIn) -> list[dict]:
        """Chroma 语义检索；若无配置则跳过（仅依赖关键词）"""
        try:
            from app.engine.vector_client import chroma_collection
        except Exception:
            return []
        col = chroma_collection()
        if col is None:
            return []
        try:
            res = col.query(
                query_texts=[payload.query],
                n_results=payload.top_k,
                where={"space_id": space_id},
            )
        except Exception:
            return []
        out = []
        ids = res.get("ids", [[]])[0]
        dists = res.get("distances", [[]])[0]
        docs = res.get("documents", [[]])[0]
        for kid, dist, doc in zip(ids, dists, docs):
            score = max(0.0, 1 - float(dist))
            out.append(
                {
                    "knowledge_id": int(kid.split("-")[0]) if "-" in kid else 0,
                    "score": score,
                    "snippet": (doc or "")[:200],
                }
            )
        return out
