"""app/service/space_service.py
团队空间业务：创建 / 修改 / 解散 / 成员管理 / 权限校验
"""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import ErrorCode
from app.core.exceptions import BizException
from app.dao.user_dao import SpaceDAO, SpaceMemberDAO
from app.model.user import Space, SpaceMember
from app.schema.space import MemberIn, SpaceIn, SpaceOut, SpaceUpdateIn


class SpaceService:
    SUPER_ADMIN = "super_admin"
    SPACE_ADMIN = "space_admin"
    MEMBER = "member"

    def __init__(self, session: AsyncSession):
        self.session = session
        self.space_dao = SpaceDAO(session)
        self.member_dao = SpaceMemberDAO(session)

    async def create(self, user_id: int, payload: SpaceIn) -> SpaceOut:
        space = await self.space_dao.create(
            {
                "name": payload.name,
                "description": payload.description,
                "owner_id": user_id,
            }
        )
        # Persist the space before using its generated id for owner membership.
        await self.session.flush()
        await self.member_dao.create(
            {
                "space_id": space.id,
                "user_id": user_id,
                "role": self.SUPER_ADMIN,
            }
        )
        await self.session.commit()
        return SpaceOut.model_validate(space)

    async def update(self, space_id: int, user_id: int, payload: SpaceUpdateIn) -> SpaceOut:
        member = await self.member_dao.is_member(space_id, user_id)
        if not member or member.role not in (self.SUPER_ADMIN, self.SPACE_ADMIN):
            raise BizException(ErrorCode.AUTH_PERMISSION_DENIED, http_status=403)
        space = await self.space_dao.update(space_id, payload.model_dump(exclude_unset=True))
        if not space:
            raise BizException(ErrorCode.SPACE_NOT_FOUND, http_status=404)
        await self.session.commit()
        return SpaceOut.model_validate(space)

    async def list_user_spaces(self, user_id: int) -> list[SpaceOut]:
        from sqlalchemy import select
        from app.model.user import Space

        res = await self.session.execute(
            select(Space)
            .join(SpaceMember, SpaceMember.space_id == Space.id)
            .where(SpaceMember.user_id == user_id)
            .order_by(Space.id.desc())
        )
        return [SpaceOut.model_validate(s) for s in res.scalars().all()]

    async def add_member(self, space_id: int, operator_id: int, payload: MemberIn) -> SpaceMember:
        operator = await self.member_dao.is_member(space_id, operator_id)
        if not operator or operator.role not in (self.SUPER_ADMIN, self.SPACE_ADMIN):
            raise BizException(ErrorCode.AUTH_PERMISSION_DENIED, http_status=403)
        if await self.member_dao.is_member(space_id, payload.user_id):
            raise BizException(ErrorCode.SPACE_MEMBER_EXISTS)
        member = await self.member_dao.create(
            {
                "space_id": space_id,
                "user_id": payload.user_id,
                "role": payload.role,
            }
        )
        await self.session.commit()
        return member

    async def list_members(self, space_id: int, operator_id: int) -> list[SpaceMember]:
        if not await self.member_dao.is_member(space_id, operator_id):
            raise BizException(ErrorCode.AUTH_PERMISSION_DENIED, http_status=403)
        return await self.member_dao.list_by_space(space_id)

    async def remove_member(self, space_id: int, operator_id: int, member_user_id: int) -> None:
        operator = await self.member_dao.is_member(space_id, operator_id)
        if not operator or operator.role not in (self.SUPER_ADMIN, self.SPACE_ADMIN):
            raise BizException(ErrorCode.AUTH_PERMISSION_DENIED, http_status=403)
        m = await self.member_dao.is_member(space_id, member_user_id)
        if not m:
            raise BizException(ErrorCode.SPACE_MEMBER_NOT_FOUND, http_status=404)
        await self.session.delete(m)
        await self.session.commit()

    async def has_role(self, space_id: int, user_id: int, roles: tuple[str, ...]) -> bool:
        member = await self.member_dao.is_member(space_id, user_id)
        return bool(member and member.role in roles)
