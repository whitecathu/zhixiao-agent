"""app/dao/base.py
通用 DAO 基类 - 提供 CRUD 模板
"""

from typing import Any, Generic, Optional, Sequence, Type, TypeVar

from pydantic import BaseModel
from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.model.base import Base

ModelT = TypeVar("ModelT", bound=Base)  # type: ignore[valid-type]


class BaseDAO(Generic[ModelT]):
    model: Type[ModelT]

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, pk: int, *, lock: bool = False) -> Optional[ModelT]:
        stmt = select(self.model).where(self.model.id == pk)  # type: ignore[attr-defined]
        if lock:
            stmt = stmt.with_for_update()
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list(
        self, *, offset: int = 0, limit: int = 20, filters: Optional[Sequence[Any]] = None
    ) -> tuple[list[ModelT], int]:
        stmt = select(self.model)
        if filters:
            stmt = stmt.where(*filters)
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery()))
        items = (
            (
                await self.session.execute(
                    stmt.offset(offset)
                    .limit(limit)
                    .order_by(
                        self.model.id.desc()  # type: ignore[attr-defined]
                    )
                )
            )
            .scalars()
            .all()
        )
        return list(items), int(total or 0)

    async def create(self, data: dict | BaseModel) -> ModelT:
        if isinstance(data, BaseModel):
            data = data.model_dump(exclude_unset=True)
        obj = self.model(**data)  # type: ignore[call-arg]
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def update(self, pk: int, data: dict | BaseModel) -> Optional[ModelT]:
        if isinstance(data, BaseModel):
            data = data.model_dump(exclude_unset=True)
        if not data:
            return await self.get(pk)
        await self.session.execute(
            update(self.model).where(self.model.id == pk).values(**data)  # type: ignore[attr-defined]
        )
        await self.session.flush()
        return await self.get(pk)

    async def soft_delete(self, pk: int) -> bool:
        from datetime import datetime

        await self.session.execute(
            update(self.model).where(self.model.id == pk).values(deleted_at=datetime.utcnow())  # type: ignore[attr-defined]
        )
        return True

    async def hard_delete(self, pk: int) -> bool:
        await self.session.execute(
            delete(self.model).where(self.model.id == pk)  # type: ignore[attr-defined]
        )
        return True
