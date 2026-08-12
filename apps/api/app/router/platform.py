"""REST and SSE API for the engineering-agent control plane."""

from __future__ import annotations

import asyncio
import json
import secrets
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.error_codes import ErrorCode
from app.core.events import EventBroker
from app.core.exceptions import BizException
from app.core.middleware import get_current_user, get_space_id
from app.core.response import ApiResponse
from app.db.session import get_session
from app.model.platform import (
    AgentDefinition,
    EvaluationRun,
    FineTuneJob,
    KnowledgeEntity,
    ModelProfile,
    WorkflowDefinition,
)
from app.schema.platform import (
    AgentCreate,
    AgentOut,
    AgentUpdate,
    ApprovalDecision,
    ApprovalOut,
    ApprovalRequest,
    ArtifactCreate,
    ArtifactOut,
    DiffOut,
    EvaluationCreate,
    EvaluationOut,
    FineTuneCreate,
    FineTuneOut,
    KnowledgeEntityCreate,
    KnowledgeEntityOut,
    KnowledgeGraphExplore,
    KnowledgeGraphExploreOut,
    KnowledgeRelationCreate,
    KnowledgeRelationOut,
    ModelProfileCreate,
    ModelProfileOut,
    ModelProfileUpdate,
    RepositoryCreate,
    RepositoryOut,
    RunStepCreate,
    RunStepOut,
    TaskRunCreate,
    TaskRunOut,
    ToolDescriptor,
    ToolInvocationCreate,
    ToolInvocationOut,
    WebApprovalDecision,
    WorkerRunResult,
    WorkflowCreate,
    WorkflowOut,
    WorkflowUpdate,
    WorkspaceCreate,
    WorkspaceOut,
)
from app.service.platform_service import PlatformService, tool_descriptors

router = APIRouter(prefix="/api/v1", tags=["Agent 平台"])


def service(session: AsyncSession = Depends(get_session)) -> PlatformService:
    return PlatformService(session)


def success(data: Any = None) -> ApiResponse:
    return ApiResponse.success(data)


def repository_data(item) -> dict[str, Any]:
    data = RepositoryOut.model_validate(item).model_dump()
    data.update({"path": item.root_path, "remote_url": item.clone_url})
    return data


def approval_data(item) -> dict[str, Any]:
    data = ApprovalOut.model_validate(item).model_dump()
    data.update(
        {
            "task_id": item.task_run_id,
            "kind": "plan" if item.operation.startswith("execute_task") else item.operation,
            "summary": item.reason,
            "details": item.comment,
        }
    )
    return data


def artifact_data(item) -> dict[str, Any]:
    data = ArtifactOut.model_validate(item).model_dump()
    metadata = item.metadata_ or {}
    data.update(
        {
            "task_id": item.task_run_id,
            "content": metadata.get("content"),
            "url": item.path,
        }
    )
    return data


@router.post("/repositories")
async def create_repository(
    payload: RepositoryCreate,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    obj = await svc.create_repository(space_id, user["user_id"], payload)
    return success(repository_data(obj))


@router.get("/repositories")
async def list_repositories(
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    from app.model.platform import Repository

    items = await svc.list_scoped(Repository, space_id)
    return success([repository_data(item) for item in items])


@router.get("/repositories/{repository_id}")
async def get_repository(
    repository_id: int,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    from app.model.platform import Repository

    item = await svc.get_scoped(Repository, repository_id, space_id)
    return success(repository_data(item))


@router.post("/repositories/{repository_id}/index")
async def index_repository(
    repository_id: int,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    item = await svc.index_repository(repository_id, space_id)
    return success(repository_data(item))


@router.post("/repositories/{repository_id}/workspaces")
async def create_workspace(
    repository_id: int,
    payload: WorkspaceCreate,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    item = await svc.create_workspace(repository_id, space_id, payload)
    return success(WorkspaceOut.model_validate(item).model_dump())


@router.get("/repositories/{repository_id}/workspaces")
async def list_workspaces(
    repository_id: int,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    items = await svc.list_workspaces(repository_id, space_id)
    return success([WorkspaceOut.model_validate(item).model_dump() for item in items])


@router.post("/task-runs")
async def create_task_run(
    payload: TaskRunCreate,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    run = await svc.create_run(space_id, user["user_id"], payload)
    return success(TaskRunOut.model_validate(run).model_dump())


@router.get("/task-runs")
async def list_task_runs(
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    items = await svc.list_runs(space_id)
    return success([TaskRunOut.model_validate(item).model_dump() for item in items])


@router.get("/task-runs/{run_id}")
async def get_task_run(
    run_id: int,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    run = await svc.get_run(run_id, space_id)
    return success(TaskRunOut.model_validate(run).model_dump())


@router.get("/task-runs/{run_id}/workflow-replay")
async def get_workflow_replay(
    run_id: int,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    return success(await svc.workflow_replay(run_id, space_id))


async def _interrupt(run_id: int, space_id: int, svc: PlatformService) -> ApiResponse:
    run = await svc.interrupt_run(run_id, space_id)
    return success(TaskRunOut.model_validate(run).model_dump())


@router.post("/task-runs/{run_id}/interrupt")
@router.post("/tasks/{run_id}/interrupt")
async def interrupt_task_run(
    run_id: int,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    return await _interrupt(run_id, space_id, svc)


@router.post("/task-runs/{run_id}/resume")
@router.post("/tasks/{run_id}/resume")
async def resume_task_run(
    run_id: int,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    run = await svc.resume_run(run_id, space_id)
    return success(TaskRunOut.model_validate(run).model_dump())


@router.get("/task-runs/{run_id}/approvals")
@router.get("/tasks/{run_id}/approvals")
async def list_run_approvals(
    run_id: int,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    items = await svc.list_approvals(run_id, space_id)
    return success([approval_data(item) for item in items])


@router.post("/task-runs/{run_id}/approvals")
async def request_run_approval(
    run_id: int,
    payload: ApprovalRequest,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    item = await svc.request_approval(run_id, space_id, user["user_id"], payload)
    return success(approval_data(item))


@router.post("/approvals/{approval_id}/decision")
async def decide_approval(
    approval_id: int,
    payload: ApprovalDecision,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    item = await svc.decide_approval(approval_id, space_id, user["user_id"], payload)
    return success(approval_data(item))


@router.post("/tasks/{run_id}/approvals")
async def decide_run_approval(
    run_id: int,
    payload: WebApprovalDecision,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    item = await svc.decide_approval(
        payload.approval_id, space_id, user["user_id"], payload, expected_run_id=run_id
    )
    return success(approval_data(item))


@router.get("/task-runs/{run_id}/diff")
@router.get("/tasks/{run_id}/diff")
async def get_run_diff(
    run_id: int,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    run = await svc.get_run(run_id, space_id)
    verified = bool(run.verification and run.verification.get("passed"))
    content = run.diff_text or ""
    return success(
        DiffOut(
            task_run_id=run.id, unified_diff=content, content=content, verified=verified
        ).model_dump()
    )


@router.get("/task-runs/{run_id}/artifacts")
@router.get("/tasks/{run_id}/artifacts")
async def list_run_artifacts(
    run_id: int,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    items = await svc.list_artifacts(run_id, space_id)
    return success([artifact_data(item) for item in items])


@router.post("/task-runs/{run_id}/artifacts")
@router.post("/tasks/{run_id}/artifacts")
async def create_run_artifact(
    run_id: int,
    payload: ArtifactCreate,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    item = await svc.create_artifact(run_id, space_id, payload)
    return success(artifact_data(item))


@router.get("/tasks/{run_id}/tests")
@router.get("/task-runs/{run_id}/tests")
async def list_run_tests(
    run_id: int,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    run = await svc.get_run(run_id, space_id)
    verification = run.verification or {}
    if not verification.get("command"):
        return success([])
    passed = verification.get("passed")
    status = (
        "passed"
        if passed
        else ("failed" if verification.get("exit_code") is not None else "skipped")
    )
    return success(
        [
            {
                "id": f"run-{run.id}-verification",
                "command": verification["command"],
                "status": status,
                "summary": verification.get("summary"),
            }
        ]
    )


@router.post("/internal/task-runs/{run_id}/result", include_in_schema=False)
async def persist_worker_result(
    run_id: int,
    payload: WorkerRunResult,
    x_worker_token: str = Header(default="", alias="X-Worker-Token"),
    svc: PlatformService = Depends(service),
):
    expected = settings.WORKER_CALLBACK_TOKEN
    if not expected or not secrets.compare_digest(x_worker_token, expected):
        raise BizException(
            ErrorCode.AUTH_PERMISSION_DENIED, message="Worker callback denied", http_status=403
        )
    run = await svc.apply_worker_result(run_id, payload)
    return success(TaskRunOut.model_validate(run).model_dump())


@router.get("/task-runs/{run_id}/steps")
@router.get("/tasks/{run_id}/steps")
async def list_run_steps(
    run_id: int,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    items = await svc.list_steps(run_id, space_id)
    return success([RunStepOut.model_validate(item).model_dump() for item in items])


@router.post("/task-runs/{run_id}/steps")
@router.post("/tasks/{run_id}/steps")
async def create_run_step(
    run_id: int,
    payload: RunStepCreate,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    item = await svc.create_step(run_id, space_id, payload)
    return success(RunStepOut.model_validate(item).model_dump())


@router.get("/task-runs/{run_id}/tool-invocations")
@router.get("/tasks/{run_id}/tool-invocations")
async def list_tool_invocations(
    run_id: int,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    items = await svc.list_tool_invocations(run_id, space_id)
    return success([ToolInvocationOut.model_validate(item).model_dump() for item in items])


@router.post("/task-runs/{run_id}/tool-invocations")
@router.post("/tasks/{run_id}/tool-invocations")
async def create_tool_invocation(
    run_id: int,
    payload: ToolInvocationCreate,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    item = await svc.create_tool_invocation(run_id, space_id, payload)
    return success(ToolInvocationOut.model_validate(item).model_dump())


def _sse(event_id: str, event: str, data: dict[str, Any]) -> str:
    return f"id: {event_id}\nevent: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/task-runs/{run_id}/events")
@router.get("/tasks/{run_id}/events")
async def stream_run_events(
    run_id: int,
    request: Request,
    cursor: str | None = Query(default=None),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    await svc.get_run(run_id, space_id)
    broker = EventBroker.default()
    initial_cursor = last_event_id or cursor or "0-0"

    async def generate():
        current = initial_cursor
        while not await request.is_disconnected():
            events = await broker.read(str(run_id), after=current, block_ms=5_000)
            if not events:
                yield ": heartbeat\n\n"
                await asyncio.sleep(0)
                continue
            for item in events:
                current = item.id
                yield _sse(item.id, item.event, item.data)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/workflows")
async def create_workflow(
    payload: WorkflowCreate,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    item = await svc.create_workflow(space_id, user["user_id"], payload)
    return success(WorkflowOut.model_validate(item).model_dump())


@router.get("/workflows")
async def list_workflows(
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    await svc.require_space_member(space_id, user["user_id"])
    items = await svc.list_scoped(WorkflowDefinition, space_id)
    return success([WorkflowOut.model_validate(item).model_dump() for item in items])


@router.put("/workflows/{workflow_id}")
async def update_workflow(
    workflow_id: int,
    payload: WorkflowUpdate,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    item = await svc.update_workflow(workflow_id, space_id, user["user_id"], payload)
    return success(WorkflowOut.model_validate(item).model_dump())


@router.get("/workflows/{workflow_id}/versions")
async def list_workflow_versions(
    workflow_id: int,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    await svc.require_space_member(space_id, user["user_id"])
    items = await svc.list_workflow_versions(workflow_id, space_id)
    return success([WorkflowOut.model_validate(item).model_dump() for item in items])


@router.post("/workflows/{workflow_id}/publish")
async def publish_workflow(
    workflow_id: int,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    item = await svc.publish_workflow(workflow_id, space_id, user["user_id"])
    return success(WorkflowOut.model_validate(item).model_dump())


@router.post("/agents")
async def create_agent(
    payload: AgentCreate,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    privileged_roles = {"metagpt", "team", "metagpt_team"}
    privileged_tools = {"terminal", "background_command", "mcp", "sub_agent", "open_pull_request"}
    if payload.role in privileged_roles or set(payload.tool_allowlist) & privileged_tools:
        await svc.require_space_admin(space_id, user["user_id"])
    item = await svc.create_scoped(AgentDefinition, space_id, payload)
    return success(AgentOut.model_validate(item).model_dump())


@router.get("/agents")
async def list_agents(
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    items = await svc.list_scoped(AgentDefinition, space_id)
    return success([AgentOut.model_validate(item).model_dump() for item in items])


@router.put("/agents/{agent_id}")
async def update_agent(
    agent_id: int,
    payload: AgentUpdate,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    item = await svc.update_agent(agent_id, space_id, user["user_id"], payload)
    return success(AgentOut.model_validate(item).model_dump())


@router.get("/tools")
async def list_tools(user=Depends(get_current_user)):
    return success(
        [ToolDescriptor.model_validate(item).model_dump() for item in tool_descriptors()]
    )


@router.post("/models")
async def create_model(
    payload: ModelProfileCreate,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    item = await svc.create_scoped(ModelProfile, space_id, payload)
    return success(ModelProfileOut.model_validate(item).model_dump())


@router.get("/models")
async def list_models(
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    items = await svc.list_scoped(ModelProfile, space_id)
    return success([ModelProfileOut.model_validate(item).model_dump() for item in items])


@router.put("/models/{model_id}")
async def update_model(
    model_id: int,
    payload: ModelProfileUpdate,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    item = await svc.update_model_profile(model_id, space_id, payload)
    return success(ModelProfileOut.model_validate(item).model_dump())


@router.post("/evaluations")
async def create_evaluation(
    payload: EvaluationCreate,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    item = await svc.create_scoped(EvaluationRun, space_id, payload)
    return success(EvaluationOut.model_validate(item).model_dump())


@router.get("/evaluations")
async def list_evaluations(
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    items = await svc.list_scoped(EvaluationRun, space_id)
    return success([EvaluationOut.model_validate(item).model_dump() for item in items])


@router.post("/fine-tunes")
async def create_fine_tune(
    payload: FineTuneCreate,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    item = await svc.create_scoped(FineTuneJob, space_id, payload)
    return success(FineTuneOut.model_validate(item).model_dump())


@router.get("/fine-tunes")
async def list_fine_tunes(
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    items = await svc.list_scoped(FineTuneJob, space_id)
    return success([FineTuneOut.model_validate(item).model_dump() for item in items])


@router.post("/knowledge-entities")
async def create_entity(
    payload: KnowledgeEntityCreate,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    await svc.require_space_member(space_id, user["user_id"])
    item = await svc.create_scoped(KnowledgeEntity, space_id, payload)
    return success(KnowledgeEntityOut.model_validate(item).model_dump())


@router.post("/knowledge-relations")
async def create_relation(
    payload: KnowledgeRelationCreate,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    await svc.require_space_member(space_id, user["user_id"])
    item = await svc.create_relation(space_id, payload)
    return success(KnowledgeRelationOut.model_validate(item).model_dump())


@router.get("/knowledge/graph")
async def get_knowledge_graph(
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    graph = await svc.explore_knowledge_graph(
        space_id, user["user_id"], KnowledgeGraphExplore(limit=100, depth=1)
    )
    return success(
        {
            "entities": [item.model_dump() for item in graph.entities],
            "relations": [item.model_dump() for item in graph.relations],
        }
    )


@router.post("/knowledge/graph/explore")
async def explore_knowledge_graph(
    payload: KnowledgeGraphExplore,
    user=Depends(get_current_user),
    space_id: int = Depends(get_space_id),
    svc: PlatformService = Depends(service),
):
    graph = await svc.explore_knowledge_graph(space_id, user["user_id"], payload)
    return success(KnowledgeGraphExploreOut.model_validate(graph).model_dump())
