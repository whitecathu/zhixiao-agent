"""app/model/user.py
用户 / 刷新令牌 / 空间 / 空间成员
"""

from sqlalchemy import (
    BigInteger,
    String,
    Integer,
    SmallInteger,
    TIMESTAMP,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, BigInt, PKMixin


class User(PKMixin, Base):
    __tablename__ = "users"
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(64), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    last_login_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)

    __table_args__ = (
        Index("idx_users_email", "email"),
        Index("idx_users_status", "status"),
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    jti: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[str] = mapped_column(TIMESTAMP, nullable=False)
    revoked: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)

    __table_args__ = (
        Index("idx_rt_user", "user_id"),
        Index("idx_rt_jti", "jti"),
    )


class Space(PKMixin, Base):
    __tablename__ = "spaces"
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)

    __table_args__ = (Index("idx_spaces_owner", "owner_id"),)


class SpaceMember(Base):
    __tablename__ = "space_members"
    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    space_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("spaces.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # super_admin / space_admin / member

    __table_args__ = (
        UniqueConstraint("space_id", "user_id", name="uk_space_user"),
        Index("idx_sm_user", "user_id"),
    )
