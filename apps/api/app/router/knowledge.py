"""app/router/knowledge.py
知识接口
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core.middleware import get_current_user, get_space_id
from app.core.response import ApiResponse, PageResponse
from app.db.session import get_session
from app.schema.knowledge import (
    CategoryOut,
    KnowledgeOut,
    KnowledgeSearchIn,
    KnowledgeUpdateIn,
    TagOut,
)
from app.service.knowledge_service import KnowledgeService

router = APIRouter(prefix="/api/v1/knowledge", tags=["知识"])


@router.get("", response_model=PageResponse)
async def list_knowledge(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    type: Optional[str] = None,
    category_path: Optional[str] = None,
    user=Depends(get_current_user),
    space_id=Depends(get_space_id),
    session=Depends(get_session),
):
    svc = KnowledgeService(session)
    items, total = await svc.dao.list_by_space(
        space_id,
        type=type,
        category_path=category_path,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return PageResponse.of(
        items=[KnowledgeOut.model_validate(i).model_dump() for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/tags", response_model=ApiResponse[list])
async def list_tags(
    user=Depends(get_current_user), space_id=Depends(get_space_id), session=Depends(get_session)
):
    svc = KnowledgeService(session)
    items = await svc.list_tags(space_id)
    return ApiResponse.success([t.model_dump() for t in items])


@router.get("/categories", response_model=ApiResponse[list])
async def list_categories(
    user=Depends(get_current_user), space_id=Depends(get_space_id), session=Depends(get_session)
):
    svc = KnowledgeService(session)
    items = await svc.list_categories(space_id)
    return ApiResponse.success([c.model_dump() for c in items])


@router.get("/{knowledge_id}", response_model=ApiResponse[KnowledgeOut])
async def get_knowledge(
    knowledge_id: int,
    user=Depends(get_current_user),
    space_id=Depends(get_space_id),
    session=Depends(get_session),
):
    svc = KnowledgeService(session)
    out = await svc.get(space_id, knowledge_id)
    return ApiResponse.success(out.model_dump())


@router.put("/{knowledge_id}", response_model=ApiResponse[KnowledgeOut])
async def update_knowledge(
    knowledge_id: int,
    payload: KnowledgeUpdateIn,
    user=Depends(get_current_user),
    space_id=Depends(get_space_id),
    session=Depends(get_session),
):
    svc = KnowledgeService(session)
    out = await svc.update(space_id, knowledge_id, payload)
    return ApiResponse.success(out.model_dump())


@router.delete("/{knowledge_id}", response_model=ApiResponse)
async def delete_knowledge(
    knowledge_id: int,
    user=Depends(get_current_user),
    space_id=Depends(get_space_id),
    session=Depends(get_session),
):
    svc = KnowledgeService(session)
    await svc.delete(space_id, knowledge_id)
    return ApiResponse.success()


@router.post("/search", response_model=ApiResponse)
async def search(
    payload: KnowledgeSearchIn,
    user=Depends(get_current_user),
    space_id=Depends(get_space_id),
    session=Depends(get_session),
):
    svc = KnowledgeService(session)
    res = await svc.search(space_id, payload)
    return ApiResponse.success(res)
