"""app/schema/knowledge.py
知识模块请求/响应
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeUpdateIn(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    summary: Optional[str] = None
    tags: Optional[list[str]] = None
    category_path: Optional[str] = None
    quality_score: Optional[Decimal] = Field(None, ge=0, le=1)


class KnowledgeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    space_id: int
    source_task_id: Optional[int]
    source_agent_step_id: Optional[int]
    type: str
    title: str
    content: str
    summary: Optional[str]
    tags: Optional[list]
    category_path: Optional[str]
    quality_score: Decimal
    usage_count: int
    last_used_at: Optional[datetime]
    status: str
    created_at: datetime


class KnowledgeSearchIn(BaseModel):
    """混合检索请求"""

    query: str = Field(min_length=1, max_length=512)
    type: Optional[str] = Field(None, pattern="^(experience|template|knowledge|pitfall)$")
    tags: Optional[list[str]] = None
    category_path: Optional[str] = None
    include_low_quality: bool = False
    top_k: int = Field(20, ge=1, le=100)
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class SearchHit(BaseModel):
    knowledge_id: int
    score: float
    title: str
    summary: Optional[str]
    snippet: str
    tags: Optional[list]
    category_path: Optional[str]
    quality_score: float
    source_task_id: Optional[int]


class TagOut(BaseModel):
    id: int
    name: str


class CategoryOut(BaseModel):
    id: int
    parent_id: Optional[int]
    name: str
    path: Optional[str]
