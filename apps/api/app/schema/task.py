"""app/schema/task.py
任务 / 执行 模块的请求/响应模型
"""

from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel, ConfigDict, Field


class TaskCreateIn(BaseModel):
    title: str = Field(min_length=2, max_length=128)
    goal: str = Field(min_length=10)
    attachments: Optional[list[int]] = None
    priority: int = Field(5, ge=1, le=9)
    template_id: Optional[int] = None
    # 幂等令牌
    request_token: Optional[str] = Field(None, description="幂等令牌（X-Request-Token 也支持）")


class TaskUpdateIn(BaseModel):
    status: Optional[str] = Field(None, pattern="^(pending|running|succeeded|failed|interrupted)$")
    priority: Optional[int] = Field(None, ge=1, le=9)


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    space_id: int
    user_id: int
    title: str
    goal: str
    status: str
    priority: int
    template_id: Optional[int]
    result_url: Optional[str]
    duration_ms: int
    error_code: Optional[str]
    error_message: Optional[str]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    created_at: datetime


class AgentStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    task_id: int
    agent_name: str
    node_id: str
    step_index: int
    status: str
    input: Optional[str]
    output: Optional[str]
    tools_used: Optional[list]
    tokens_in: int
    tokens_out: int
    duration_ms: int
    error_message: Optional[str]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]


class ExecutionControlIn(BaseModel):
    """任务控制指令（中断/恢复）"""

    action: str = Field(..., pattern="^(interrupt|resume)$")
