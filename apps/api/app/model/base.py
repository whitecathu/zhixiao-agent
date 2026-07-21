"""app/model/base.py
所有 ORM 模型基类 - 统一创建 / 修改 / 软删除字段
"""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Integer, Text, TIMESTAMP, func
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import JSON as SAJSON

from app.db.session import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.current_timestamp(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True, default=None)


class PKMixin(TimestampMixin):
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )


def to_dict(self) -> dict[str, Any]:
    """扩展给所有模型用于序列化"""
    out: dict[str, Any] = {}
    for c in self.__table__.columns:
        v = getattr(self, c.name)
        if isinstance(v, datetime):
            v = v.isoformat()
        out[c.name] = v
    return out


Base.to_dict = to_dict  # type: ignore[attr-defined]
LongText = Text().with_variant(MEDIUMTEXT(), "mysql")
BigInt = BigInteger().with_variant(Integer, "sqlite")

__all__ = ["Base", "PKMixin", "TimestampMixin", "SAJSON", "LongText", "BigInt"]
