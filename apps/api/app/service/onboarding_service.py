"""Business rules for user onboarding and space-level defaults."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import ErrorCode
from app.core.exceptions import BizException
from app.model.onboarding import OnboardingState, SpaceOnboardingConfig
from app.model.platform import WorkflowDefinition
from app.model.user import SpaceMember
from app.schema.onboarding import (
    OnboardingConfigOut,
    OnboardingConfigUpdate,
    OnboardingStateOut,
    OnboardingStepOut,
)

ONBOARDING_STEPS: tuple[tuple[str, str], ...] = (
    ("select_space", "选择工作空间"),
    ("connect_repository", "接入代码仓库"),
    ("create_task", "创建首个 Agent 任务"),
    ("approve_plan", "审批执行计划"),
    ("inspect_delivery", "查看 Diff 与验证证据"),
)
STEP_IDS = frozenset(step_id for step_id, _ in ONBOARDING_STEPS)
ADMIN_ROLES = frozenset({"super_admin", "space_admin"})


class OnboardingService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_state(self, user_id: int, space_id: int) -> OnboardingStateOut:
        await self._membership(user_id, space_id)
        state = await self._state(user_id, space_id)
        return self._serialize(state)

    async def complete_step(
        self, user_id: int, space_id: int, step_id: str
    ) -> OnboardingStateOut:
        await self._membership(user_id, space_id)
        if step_id not in STEP_IDS:
            raise BizException(ErrorCode.PARAM_INVALID, http_status=422)
        state = await self._get_or_create_state(user_id, space_id)
        completed = list(dict.fromkeys([*state.completed_steps, step_id]))
        state.completed_steps = completed
        state.skipped = False
        state.finished_at = datetime.utcnow() if set(completed) == STEP_IDS else None
        await self.session.commit()
        return self._serialize(state)

    async def skip(self, user_id: int, space_id: int) -> OnboardingStateOut:
        await self._membership(user_id, space_id)
        state = await self._get_or_create_state(user_id, space_id)
        state.skipped = True
        state.finished_at = datetime.utcnow()
        await self.session.commit()
        return self._serialize(state)

    async def replay(self, user_id: int, space_id: int) -> OnboardingStateOut:
        await self._membership(user_id, space_id)
        state = await self._get_or_create_state(user_id, space_id)
        state.completed_steps = []
        state.skipped = False
        state.finished_at = None
        state.replay_count += 1
        await self.session.commit()
        return self._serialize(state)

    async def get_config(self, user_id: int, space_id: int) -> OnboardingConfigOut:
        await self._membership(user_id, space_id)
        config = await self._config(space_id)
        return OnboardingConfigOut(
            space_id=space_id,
            recommended_template=config.recommended_template if config else None,
            default_workflow_id=config.default_workflow_id if config else None,
        )

    async def update_config(
        self,
        user_id: int,
        space_id: int,
        payload: OnboardingConfigUpdate,
    ) -> OnboardingConfigOut:
        member = await self._membership(user_id, space_id)
        if member.role not in ADMIN_ROLES:
            raise BizException(ErrorCode.AUTH_PERMISSION_DENIED, http_status=403)
        if payload.default_workflow_id is not None:
            workflow = await self.session.scalar(
                select(WorkflowDefinition).where(
                    WorkflowDefinition.id == payload.default_workflow_id,
                    WorkflowDefinition.space_id == space_id,
                )
            )
            if workflow is None:
                raise BizException(ErrorCode.NOT_FOUND, http_status=404)
        config = await self._config(space_id)
        if config is None:
            config = SpaceOnboardingConfig(space_id=space_id)
            self.session.add(config)
        updates = payload.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(config, field, value)
        await self.session.commit()
        await self.session.refresh(config)
        return OnboardingConfigOut.model_validate(config)

    async def _membership(self, user_id: int, space_id: int) -> SpaceMember:
        member = await self.session.scalar(
            select(SpaceMember).where(
                SpaceMember.user_id == user_id,
                SpaceMember.space_id == space_id,
            )
        )
        if member is None:
            raise BizException(ErrorCode.AUTH_PERMISSION_DENIED, http_status=403)
        return member

    async def _state(self, user_id: int, space_id: int) -> OnboardingState | None:
        return await self.session.scalar(
            select(OnboardingState).where(
                OnboardingState.user_id == user_id,
                OnboardingState.space_id == space_id,
            )
        )

    async def _get_or_create_state(self, user_id: int, space_id: int) -> OnboardingState:
        state = await self._state(user_id, space_id)
        if state is None:
            state = OnboardingState(user_id=user_id, space_id=space_id, completed_steps=[])
            self.session.add(state)
            await self.session.flush()
        return state

    async def _config(self, space_id: int) -> SpaceOnboardingConfig | None:
        return await self.session.scalar(
            select(SpaceOnboardingConfig).where(SpaceOnboardingConfig.space_id == space_id)
        )

    @staticmethod
    def _serialize(state: OnboardingState | None) -> OnboardingStateOut:
        completed_steps = list(state.completed_steps) if state else []
        skipped = state.skipped if state else False
        finished = skipped or set(completed_steps) == STEP_IDS
        current_step = next(
            (step_id for step_id, _ in ONBOARDING_STEPS if step_id not in completed_steps),
            None,
        )
        return OnboardingStateOut(
            steps=[
                OnboardingStepOut(
                    id=step_id,
                    label=label,
                    completed=step_id in completed_steps,
                )
                for step_id, label in ONBOARDING_STEPS
            ],
            completed_steps=completed_steps,
            skipped=skipped,
            finished=finished,
            current_step=None if finished else current_step,
            replay_count=state.replay_count if state else 0,
        )
