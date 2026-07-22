"""API contracts for resumable onboarding."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class OnboardingStepOut(BaseModel):
    id: str
    label: str
    completed: bool


class OnboardingStateOut(BaseModel):
    steps: list[OnboardingStepOut]
    completed_steps: list[str]
    skipped: bool
    finished: bool
    current_step: str | None
    replay_count: int


class OnboardingConfigUpdate(BaseModel):
    recommended_template: str | None = Field(default=None, max_length=128)
    default_workflow_id: int | None = Field(default=None, ge=1)


class OnboardingConfigOut(OnboardingConfigUpdate):
    model_config = ConfigDict(from_attributes=True)

    space_id: int
