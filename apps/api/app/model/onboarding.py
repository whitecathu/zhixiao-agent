"""Persistent onboarding state and space-level onboarding defaults."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.model.base import Base, PKMixin


class OnboardingState(PKMixin, Base):
    __tablename__ = "onboarding_states"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    space_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("spaces.id"), nullable=False)
    completed_steps: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    skipped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    replay_count: Mapped[int] = mapped_column(default=0, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "space_id", name="uk_onboarding_user_space"),
    )


class SpaceOnboardingConfig(PKMixin, Base):
    __tablename__ = "space_onboarding_configs"

    space_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("spaces.id"), nullable=False, unique=True
    )
    recommended_template: Mapped[str | None] = mapped_column(String(128), nullable=True)
    default_workflow_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("workflow_definitions.id"), nullable=True
    )
