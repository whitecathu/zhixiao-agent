"""app/dao/user_dao.py"""

from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dao.base import BaseDAO
from app.model.user import User, RefreshToken, Space, SpaceMember
from app.model.user import User as UserModel


class UserDAO(BaseDAO[UserModel]):
    model = UserModel

    async def get_by_username(self, username: str) -> Optional[User]:
        res = await self.session.execute(select(User).where(User.username == username))
        return res.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[User]:
        res = await self.session.execute(select(User).where(User.email == email))
        return res.scalar_one_or_none()

    async def update_last_login(self, user_id: int) -> None:
        from datetime import datetime

        await self.session.execute(
            update_sql := __import__("sqlalchemy")
            .update(User)
            .where(User.id == user_id)
            .values(last_login_at=datetime.utcnow())
        )


class RefreshTokenDAO(BaseDAO[RefreshToken]):
    model = RefreshToken

    async def get_by_jti(self, jti: str) -> Optional[RefreshToken]:
        res = await self.session.execute(select(RefreshToken).where(RefreshToken.jti == jti))
        return res.scalar_one_or_none()


class SpaceDAO(BaseDAO[Space]):
    model = Space


class SpaceMemberDAO(BaseDAO[SpaceMember]):
    model = SpaceMember

    async def is_member(self, space_id: int, user_id: int) -> Optional[SpaceMember]:
        res = await self.session.execute(
            select(SpaceMember).where(
                SpaceMember.space_id == space_id, SpaceMember.user_id == user_id
            )
        )
        return res.scalar_one_or_none()

    async def list_by_space(self, space_id: int) -> list[SpaceMember]:
        res = await self.session.execute(
            select(SpaceMember).where(SpaceMember.space_id == space_id)
        )
        return list(res.scalars().all())
