"""Business rules for repositories, run lifecycle, configuration, and graph data."""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.error_codes import ErrorCode
from app.core.events import EventBroker
from app.core.exceptions import BizException
from app.core.jobs import RunJob, RunQueue
from app.core.metrics import (
    record_approval,
    record_model_usage,
    record_task_run,
    record_tool_invocation,
)
from app.model.base import Base
from app.model.knowledge import ToolInvocation
from app.model.platform import (
    AgentDefinition,
    Approval,
    Artifact,
    KnowledgeEntity,
    KnowledgeRelation,
    McpServer,
    Repository,
    RunStep,
    TaskRun,
    WorkflowDefinition,
    Workspace,
)
from app.model.user import SpaceMember
from app.schema.platform import (
    AgentUpdate,
    ApprovalDecision,
    ApprovalRequest,
    KnowledgeEntityOut,
    KnowledgeEvidenceLink,
    KnowledgeGraphExplore,
    KnowledgeGraphExploreOut,
    KnowledgeRelationOut,
    McpServerCreate,
    McpServerUpdate,
    ModelProfileUpdate,
    TaskRunCreate,
    TaskRunFork,
    WorkerRunResult,
    WorkflowCreate,
    WorkflowDSL,
    WorkflowUpdate,
)

ModelT = TypeVar("ModelT", bound=Base)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _managed_workspace_path(value: str, *, label: str) -> str:
    """Validate local repository/workspace paths against API-visible managed roots."""
    candidate = Path(value).expanduser().resolve(strict=True)
    if not candidate.is_dir():
        raise BizException(
            ErrorCode.PARAM_INVALID,
            message=f"{label} 必须是已存在目录",
            http_status=422,
        )
    configured = [
        item.strip()
        for item in settings.WORKSPACE_SOURCE_ROOTS.split(os.pathsep)
        if item.strip()
    ]
    roots = [Path(item).expanduser().resolve() for item in configured]
    roots.append(Path(settings.RUNNER_ROOT).expanduser().resolve())
    if not any(_is_relative_to(candidate, root) for root in roots):
        raise BizException(
            ErrorCode.AUTH_PERMISSION_DENIED,
            message=f"{label} 不在受管工作区根目录内",
            http_status=403,
        )
    return str(candidate)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class PlatformService:
    def __init__(
        self,
        session: AsyncSession,
        events: EventBroker | None = None,
        queue: RunQueue | None = None,
    ) -> None:
        self.session = session
        self.events = events or EventBroker.default()
        self.queue = queue or RunQueue.default()

    async def create_scoped(
        self, model: type[ModelT], space_id: int, payload: BaseModel | dict[str, Any]
    ) -> ModelT:
        data = (
            payload.model_dump(exclude_unset=True)
            if isinstance(payload, BaseModel)
            else dict(payload)
        )
        obj = model(space_id=space_id, **data)
        self.session.add(obj)
        await self.session.commit()
        await self.session.refresh(obj)
        return obj

    async def require_space_admin(self, space_id: int, user_id: int) -> None:
        member = await self.require_space_member(space_id, user_id)
        if member.role not in {"space_admin", "super_admin"}:
            raise BizException(ErrorCode.AUTH_PERMISSION_DENIED, http_status=403)

    async def require_space_member(self, space_id: int, user_id: int) -> SpaceMember:
        member = await self.session.scalar(
            select(SpaceMember).where(
                SpaceMember.space_id == space_id,
                SpaceMember.user_id == user_id,
            )
        )
        if member is None:
            raise BizException(ErrorCode.AUTH_PERMISSION_DENIED, http_status=403)
        return member

    async def list_scoped(self, model: type[ModelT], space_id: int) -> list[ModelT]:
        result = await self.session.execute(
            select(model)
            .where(model.space_id == space_id, model.deleted_at.is_(None))
            .order_by(model.id.desc())
        )
        return list(result.scalars().all())

    async def get_scoped(self, model: type[ModelT], item_id: int, space_id: int) -> ModelT:
        result = await self.session.execute(
            select(model).where(
                model.id == item_id, model.space_id == space_id, model.deleted_at.is_(None)
            )
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            raise BizException(ErrorCode.NOT_FOUND, http_status=404)
        return obj

    async def create_repository(
        self, space_id: int, user_id: int, payload: BaseModel
    ) -> Repository:
        data = payload.model_dump(exclude_unset=True)
        if data.get("root_path") and settings.APP_ENV != "test":
            data["root_path"] = _managed_workspace_path(
                str(data["root_path"]),
                label="repository.root_path",
            )
        repository = Repository(space_id=space_id, owner_id=user_id, **data)
        self.session.add(repository)
        await self.session.commit()
        await self.session.refresh(repository)
        return repository

    async def index_repository(self, repository_id: int, space_id: int) -> Repository:
        repository = await self.get_scoped(Repository, repository_id, space_id)
        repository.status = "indexing"
        await self.session.commit()
        try:
            if not repository.root_path:
                raise ValueError("repository indexing requires a local root_path")
            stats = await asyncio.to_thread(_probe_repository, repository.root_path)
        except (OSError, ValueError) as exc:
            repository.status = "error"
            repository.settings = {**(repository.settings or {}), "index_error": str(exc)}
            await self.session.commit()
            await self.events.publish(
                str(repository.id),
                "repository.index_failed",
                {
                    "repository_id": repository.id,
                    "message": str(exc),
                },
            )
            raise BizException(
                ErrorCode.PARAM_INVALID, message=f"仓库索引失败: {exc}", http_status=422
            ) from exc
        repository.status = "ready"
        repository.settings = {
            **(repository.settings or {}),
            "index": stats,
            "indexed_at": utcnow().isoformat(),
        }
        await self.session.commit()
        await self.session.refresh(repository)
        await self.events.publish(
            str(repository.id),
            "repository.indexed",
            {
                "repository_id": repository.id,
                **stats,
            },
        )
        return repository

    async def create_workflow(
        self, space_id: int, user_id: int, payload: WorkflowCreate
    ) -> WorkflowDefinition:
        await self.require_space_admin(space_id, user_id)
        if payload.version != 1:
            raise BizException(
                ErrorCode.PARAM_INVALID,
                message="新工作流必须从版本 1 开始",
                http_status=422,
            )
        duplicate = await self.session.scalar(
            select(WorkflowDefinition.id).where(
                WorkflowDefinition.space_id == space_id,
                WorkflowDefinition.name == payload.name,
                WorkflowDefinition.deleted_at.is_(None),
            )
        )
        if duplicate is not None:
            raise BizException(
                ErrorCode.PARAM_INVALID,
                message="同名工作流已存在",
                http_status=409,
            )
        data = payload.model_dump(mode="json")
        data["status"] = "draft"
        return await self.create_scoped(WorkflowDefinition, space_id, data)

    async def update_workflow(
        self, workflow_id: int, space_id: int, user_id: int, payload: WorkflowUpdate
    ) -> WorkflowDefinition:
        await self.require_space_admin(space_id, user_id)
        current = await self.get_scoped(WorkflowDefinition, workflow_id, space_id)
        if payload.name is not None and payload.name != current.name:
            raise BizException(
                ErrorCode.PARAM_INVALID,
                message="版本化工作流不能改名；请新建工作流",
                http_status=422,
            )
        name = current.name
        max_version_result = await self.session.execute(
            select(func.max(WorkflowDefinition.version)).where(
                WorkflowDefinition.space_id == space_id,
                WorkflowDefinition.name == name,
                WorkflowDefinition.deleted_at.is_(None),
            )
        )
        next_version = int(max_version_result.scalar_one_or_none() or 0) + 1
        item = WorkflowDefinition(
            space_id=space_id,
            name=name,
            version=next_version,
            definition=(
                payload.definition.model_dump(mode="json")
                if payload.definition is not None
                else current.definition
            ),
            enabled=current.enabled if payload.enabled is None else payload.enabled,
            status="draft",
        )
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def list_workflow_versions(
        self, workflow_id: int, space_id: int
    ) -> list[WorkflowDefinition]:
        current = await self.get_scoped(WorkflowDefinition, workflow_id, space_id)
        result = await self.session.execute(
            select(WorkflowDefinition)
            .where(
                WorkflowDefinition.space_id == space_id,
                WorkflowDefinition.name == current.name,
                WorkflowDefinition.deleted_at.is_(None),
            )
            .order_by(WorkflowDefinition.version.desc())
        )
        return list(result.scalars().all())

    async def publish_workflow(
        self, workflow_id: int, space_id: int, user_id: int
    ) -> WorkflowDefinition:
        await self.require_space_admin(space_id, user_id)
        workflow = await self.get_scoped(WorkflowDefinition, workflow_id, space_id)
        if workflow.status != "draft":
            raise BizException(
                ErrorCode.TASK_STATE_INVALID,
                message="只有草稿工作流可以发布",
                http_status=409,
            )
        if not workflow.enabled:
            raise BizException(
                ErrorCode.PARAM_INVALID,
                message="禁用的工作流不能发布",
                http_status=422,
            )
        try:
            WorkflowDSL.model_validate(workflow.definition)
        except ValidationError as exc:
            raise BizException(
                ErrorCode.PARAM_INVALID,
                message="工作流定义无效，无法发布",
                http_status=422,
            ) from exc
        previous = await self.session.execute(
            select(WorkflowDefinition).where(
                WorkflowDefinition.space_id == space_id,
                WorkflowDefinition.name == workflow.name,
                WorkflowDefinition.status == "published",
                WorkflowDefinition.id != workflow.id,
                WorkflowDefinition.deleted_at.is_(None),
            )
        )
        for item in previous.scalars().all():
            item.status = "archived"
        workflow.status = "published"
        workflow.published_at = utcnow()
        await self.session.commit()
        await self.session.refresh(workflow)
        return workflow

    async def update_agent(
        self,
        agent_id: int,
        space_id: int,
        user_id: int,
        payload: AgentUpdate,
    ) -> AgentDefinition:
        agent = await self.get_scoped(AgentDefinition, agent_id, space_id)
        data = payload.model_dump(exclude_unset=True)
        role = str(data.get("role") or agent.role)
        tools = set(data.get("tool_allowlist") or agent.tool_allowlist or [])
        if role in {"metagpt", "team", "metagpt_team"} or tools & {
            "terminal",
            "background_command",
            "mcp",
            "sub_agent",
            "open_pull_request",
        }:
            await self.require_space_admin(space_id, user_id)
        if data.get("model_profile_id") is not None:
            from app.model.platform import ModelProfile

            await self.get_scoped(ModelProfile, data["model_profile_id"], space_id)
        for key, value in data.items():
            setattr(agent, key, value)
        await self.session.commit()
        await self.session.refresh(agent)
        return agent

    async def update_model_profile(self, model_id: int, space_id: int, payload: ModelProfileUpdate):
        from app.model.platform import ModelProfile

        model = await self.get_scoped(ModelProfile, model_id, space_id)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(model, key, value)
        await self.session.commit()
        await self.session.refresh(model)
        return model

    async def create_mcp_server(
        self,
        space_id: int,
        user_id: int,
        payload: McpServerCreate,
    ) -> McpServer:
        await self.require_space_admin(space_id, user_id)
        duplicate = await self.session.scalar(
            select(McpServer.id).where(
                McpServer.space_id == space_id,
                McpServer.name == payload.name,
                McpServer.deleted_at.is_(None),
            )
        )
        if duplicate is not None:
            raise BizException(
                ErrorCode.PARAM_INVALID,
                message="同名 MCP 服务器已存在",
                http_status=409,
            )
        server = McpServer(space_id=space_id, **payload.model_dump())
        self.session.add(server)
        await self.session.commit()
        await self.session.refresh(server)
        return server

    async def update_mcp_server(
        self,
        server_id: int,
        space_id: int,
        user_id: int,
        payload: McpServerUpdate,
    ) -> McpServer:
        await self.require_space_admin(space_id, user_id)
        server = await self.get_scoped(McpServer, server_id, space_id)
        current = {
            "name": server.name,
            "transport": server.transport,
            "command": server.command,
            "arguments": server.arguments,
            "url": server.url,
            "env_refs": server.env_refs,
            "credential_env": server.credential_env,
            "tool_allowlist": server.tool_allowlist,
            "startup_timeout_seconds": server.startup_timeout_seconds,
            "call_timeout_seconds": server.call_timeout_seconds,
            "enabled": server.enabled,
        }
        current.update(payload.model_dump(exclude_unset=True))
        validated = McpServerCreate.model_validate(current)
        if validated.name != server.name:
            duplicate = await self.session.scalar(
                select(McpServer.id).where(
                    McpServer.space_id == space_id,
                    McpServer.name == validated.name,
                    McpServer.id != server.id,
                    McpServer.deleted_at.is_(None),
                )
            )
            if duplicate is not None:
                raise BizException(
                    ErrorCode.PARAM_INVALID,
                    message="同名 MCP 服务器已存在",
                    http_status=409,
                )
        for key, value in validated.model_dump().items():
            setattr(server, key, value)
        await self.session.commit()
        await self.session.refresh(server)
        return server

    async def delete_mcp_server(
        self, server_id: int, space_id: int, user_id: int
    ) -> McpServer:
        await self.require_space_admin(space_id, user_id)
        server = await self.get_scoped(McpServer, server_id, space_id)
        server.deleted_at = utcnow()
        server.enabled = False
        await self.session.commit()
        await self.session.refresh(server)
        return server

    async def test_mcp_server(
        self, server_id: int, space_id: int, user_id: int
    ) -> dict[str, Any]:
        """Validate a definition without starting a command or making a request."""
        await self.require_space_admin(space_id, user_id)
        server = await self.get_scoped(McpServer, server_id, space_id)
        McpServerCreate.model_validate(
            {
                "name": server.name,
                "transport": server.transport,
                "command": server.command,
                "arguments": server.arguments,
                "url": server.url,
                "env_refs": server.env_refs,
                "credential_env": server.credential_env,
                "tool_allowlist": server.tool_allowlist,
                "startup_timeout_seconds": server.startup_timeout_seconds,
                "call_timeout_seconds": server.call_timeout_seconds,
                "enabled": server.enabled,
            }
        )
        referenced = sorted(
            set(server.env_refs.values())
            | ({server.credential_env} if server.credential_env else set())
        )
        return {
            "server_id": server.id,
            "status": "valid",
            "transport": server.transport,
            "referenced_env": referenced,
            "configured_env": {name: bool(os.environ.get(name)) for name in referenced},
            "network_attempted": False,
            "command_executed": False,
            "summary": "Configuration is valid; no command or network probe was executed",
        }

    async def create_run(self, space_id: int, user_id: int, payload: TaskRunCreate) -> TaskRun:
        repository = await self.get_scoped(Repository, payload.repository_id, space_id)
        workflow: WorkflowDefinition | None = None
        if payload.workflow_id is not None:
            workflow = await self.get_scoped(WorkflowDefinition, payload.workflow_id, space_id)
            if workflow.status != "published" or not workflow.enabled:
                raise BizException(
                    ErrorCode.TASK_STATE_INVALID,
                    message="任务只能绑定已发布且启用的工作流版本",
                    http_status=409,
                )
        if payload.agent_id is not None:
            await self.get_scoped(AgentDefinition, payload.agent_id, space_id)

        data = payload.model_dump()
        budget = data.pop("budget")
        verification_commands = data.pop("verification_commands")
        run = TaskRun(
            space_id=space_id,
            user_id=user_id,
            status="awaiting_approval",
            workflow_version=workflow.version if workflow is not None else None,
            budget_snapshot=budget,
            usage_snapshot={},
            verification_commands=verification_commands,
            **data,
        )
        self.session.add(run)
        await self.session.flush()
        requires_network_clone = bool(repository.clone_url and not repository.root_path)
        approval = Approval(
            task_run_id=run.id,
            operation=("execute_task_network_clone" if requires_network_clone else "execute_task"),
            reason=(
                "Clone the remote repository over the network, then start an isolated "
                "engineering-agent run"
                if requires_network_clone
                else "Start an isolated engineering-agent run"
            ),
            requested_by=user_id,
            status="pending",
        )
        self.session.add(approval)
        await self.session.commit()
        await self.session.refresh(run)
        await self.events.publish(
            str(run.id),
            "run.created",
            {
                "run_id": run.id,
                "status": run.status,
                "title": run.title,
            },
        )
        await self.events.publish(
            str(run.id),
            "approval.requested",
            {
                "run_id": run.id,
                "approval_id": approval.id,
                "operation": approval.operation,
            },
        )
        return run

    async def create_workspace(
        self, repository_id: int, space_id: int, payload: BaseModel
    ) -> Workspace:
        await self.get_scoped(Repository, repository_id, space_id)
        data = payload.model_dump()
        if settings.APP_ENV != "test":
            data["root_path"] = _managed_workspace_path(
                str(data["root_path"]),
                label="workspace.root_path",
            )
        if data.get("task_run_id") is not None:
            run = await self.get_run(data["task_run_id"], space_id)
            if run.repository_id != repository_id:
                raise BizException(
                    ErrorCode.PARAM_INVALID, message="任务与仓库不匹配", http_status=422
                )
        workspace = Workspace(repository_id=repository_id, **data)
        self.session.add(workspace)
        await self.session.commit()
        await self.session.refresh(workspace)
        return workspace

    async def list_workspaces(self, repository_id: int, space_id: int) -> list[Workspace]:
        await self.get_scoped(Repository, repository_id, space_id)
        result = await self.session.execute(
            select(Workspace)
            .where(Workspace.repository_id == repository_id, Workspace.deleted_at.is_(None))
            .order_by(Workspace.id.desc())
        )
        return list(result.scalars().all())

    async def get_run(self, run_id: int, space_id: int) -> TaskRun:
        return await self.get_scoped(TaskRun, run_id, space_id)

    async def list_runs(
        self,
        space_id: int,
        *,
        workspace_id: int | None = None,
        status: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> list[TaskRun]:
        statement = select(TaskRun).where(
            TaskRun.space_id == space_id,
            TaskRun.deleted_at.is_(None),
        )
        if status is not None:
            statement = statement.where(TaskRun.status == status)
        if created_from is not None:
            if created_from.tzinfo is not None:
                created_from = created_from.astimezone(UTC).replace(tzinfo=None)
            statement = statement.where(TaskRun.created_at >= created_from)
        if created_to is not None:
            if created_to.tzinfo is not None:
                created_to = created_to.astimezone(UTC).replace(tzinfo=None)
            statement = statement.where(TaskRun.created_at <= created_to)
        if workspace_id is not None:
            workspace = await self.session.get(Workspace, workspace_id)
            if workspace is None or workspace.deleted_at is not None:
                raise BizException(ErrorCode.NOT_FOUND, http_status=404)
            repository = await self.get_scoped(Repository, workspace.repository_id, space_id)
            statement = statement.where(TaskRun.repository_id == repository.id)
            if workspace.task_run_id is not None:
                statement = statement.where(TaskRun.id == workspace.task_run_id)
        result = await self.session.execute(statement.order_by(TaskRun.id.desc()))
        return list(result.scalars().all())

    async def fork_run(
        self,
        run_id: int,
        space_id: int,
        user_id: int,
        payload: TaskRunFork,
    ) -> TaskRun:
        source = await self.get_run(run_id, space_id)
        repository = await self.get_scoped(Repository, source.repository_id, space_id)
        overrides = payload.model_dump(exclude_unset=True)
        run = TaskRun(
            space_id=space_id,
            user_id=user_id,
            repository_id=source.repository_id,
            workflow_id=source.workflow_id,
            workflow_version=source.workflow_version,
            agent_id=source.agent_id,
            parent_run_id=source.id,
            session_name=overrides.get("session_name", source.session_name),
            title=overrides.get("title", f"{source.title} (fork)"),
            prompt=overrides.get("prompt", source.prompt),
            permission_mode=overrides.get("permission_mode", source.permission_mode),
            status="awaiting_approval",
            budget_snapshot=dict(source.budget_snapshot or {}),
            usage_snapshot={},
            allow_unverified=source.allow_unverified,
            verification_commands=list(source.verification_commands or []),
        )
        self.session.add(run)
        await self.session.flush()
        requires_network_clone = bool(repository.clone_url and not repository.root_path)
        approval = Approval(
            task_run_id=run.id,
            operation=(
                "execute_task_network_clone" if requires_network_clone else "execute_task"
            ),
            reason=(
                "Clone the remote repository over the network, then start a forked "
                "isolated engineering-agent run"
                if requires_network_clone
                else "Start a forked isolated engineering-agent run"
            ),
            requested_by=user_id,
            status="pending",
        )
        self.session.add(approval)
        await self.session.commit()
        await self.session.refresh(run)
        await self.events.publish(
            str(run.id),
            "run.forked",
            {"run_id": run.id, "parent_run_id": source.id, "status": run.status},
        )
        await self.events.publish(
            str(run.id),
            "approval.requested",
            {
                "run_id": run.id,
                "approval_id": approval.id,
                "operation": approval.operation,
            },
        )
        return run

    async def list_approvals(self, run_id: int, space_id: int) -> list[Approval]:
        await self.get_run(run_id, space_id)
        result = await self.session.execute(
            select(Approval)
            .where(Approval.task_run_id == run_id, Approval.deleted_at.is_(None))
            .order_by(Approval.id)
        )
        return list(result.scalars().all())

    async def request_approval(
        self,
        run_id: int,
        space_id: int,
        user_id: int,
        payload: ApprovalRequest,
    ) -> Approval:
        run = await self.get_run(run_id, space_id)
        if payload.operation in {
            "destructive_command",
            "git_publish",
            "mcp",
            "sub_agent",
        } and run.permission_mode != "full":
            raise BizException(
                ErrorCode.AUTH_PERMISSION_DENIED,
                message="该高风险操作要求任务使用 full 权限",
                http_status=403,
            )
        if payload.operation == "git_publish":
            if run.status != "succeeded" or not (run.diff_text or "").strip():
                raise BizException(
                    ErrorCode.TASK_STATE_INVALID,
                    message="仅已成功且包含 Diff 的任务可请求发布审批",
                    http_status=409,
                )
        pending = await self.session.scalar(
            select(Approval.id).where(
                Approval.task_run_id == run.id,
                Approval.operation == payload.operation,
                Approval.status == "pending",
                Approval.deleted_at.is_(None),
            )
        )
        if pending is not None:
            raise BizException(
                ErrorCode.TASK_STATE_INVALID,
                message="相同操作已有待审批记录",
                http_status=409,
            )
        reasons = {
            "destructive_command": "Allow one destructive command capability for this run",
            "git_publish": "Publish the verified diff as a pull request",
            "mcp": "Allow configured MCP tools for this run",
            "sub_agent": "Allow a read-only nested agent for this run",
            "network_tools": "Allow web search and fetch tools for this run",
        }
        approval = Approval(
            task_run_id=run.id,
            operation=payload.operation,
            reason=payload.reason or reasons[payload.operation],
            requested_by=user_id,
            status="pending",
        )
        self.session.add(approval)
        await self.session.commit()
        await self.session.refresh(approval)
        await self.events.publish(
            str(run.id),
            "approval.requested",
            {
                "run_id": run.id,
                "approval_id": approval.id,
                "operation": approval.operation,
            },
        )
        return approval

    async def decide_approval(
        self,
        approval_id: int,
        space_id: int,
        user_id: int,
        payload: ApprovalDecision,
        expected_run_id: int | None = None,
    ) -> Approval:
        result = await self.session.execute(select(Approval).where(Approval.id == approval_id))
        approval = result.scalar_one_or_none()
        if approval is None:
            raise BizException(ErrorCode.NOT_FOUND, http_status=404)
        if expected_run_id is not None and approval.task_run_id != expected_run_id:
            raise BizException(ErrorCode.PARAM_INVALID, message="审批与任务不匹配", http_status=422)
        run = await self.get_run(approval.task_run_id, space_id)
        if approval.status != "pending":
            raise BizException(ErrorCode.TASK_STATE_INVALID, message="审批已处理", http_status=409)

        start_operations = {"execute_task", "execute_task_network_clone"}
        capability_operations = {
            "destructive_command",
            "git_publish",
            "mcp",
            "sub_agent",
            "network_tools",
        }
        is_start = approval.operation in start_operations
        is_capability = approval.operation in capability_operations
        if (
            payload.decision == "approved"
            and is_capability
            and run.status not in {"succeeded", "interrupted"}
        ):
            raise BizException(
                ErrorCode.TASK_STATE_INVALID,
                message="能力型审批只能在任务成功或中断后重新入队",
                http_status=409,
            )

        approval.status = payload.decision
        approval.comment = payload.comment
        approval.decided_by = user_id
        approval.decided_at = utcnow()
        event_name = "approval.decided"
        if payload.decision == "approved":
            if is_start or is_capability:
                run.status = "queued"
                event_name = "run.queued"
        elif is_start:
            # Only start approvals cancel the run; capability denials leave status alone.
            run.status = "cancelled"
            run.finished_at = utcnow()
            event_name = "run.cancelled"
        else:
            event_name = "approval.rejected"
        await self.session.commit()
        if approval.decided_at is not None and approval.created_at is not None:
            record_approval(
                approval.status,
                max((approval.decided_at - approval.created_at).total_seconds(), 0.0),
            )
        if payload.decision == "approved" and (is_start or is_capability):
            await self._enqueue_run(run, approval=approval)
        await self.session.refresh(approval)
        await self.events.publish(
            str(run.id),
            "approval.decided",
            {
                "run_id": run.id,
                "approval_id": approval.id,
                "decision": approval.status,
            },
        )
        if event_name != "approval.decided":
            await self.events.publish(
                str(run.id),
                event_name,
                {
                    "run_id": run.id,
                    "status": run.status,
                    "approval_id": approval.id,
                    "operation": approval.operation,
                },
            )
        return approval

    async def interrupt_run(self, run_id: int, space_id: int) -> TaskRun:
        run = await self.get_run(run_id, space_id)
        if run.status not in {"awaiting_approval", "queued", "running"}:
            raise BizException(ErrorCode.TASK_STATE_INVALID, http_status=409)
        run.status = "interrupted"
        await self.session.commit()
        await self.session.refresh(run)
        # Signal in-flight workers to cancel the asyncio task / runner.
        from app.core.redis_client import RedisClient

        client = await RedisClient.get()
        await client.set(f"run:control:{run.id}", "stop", ex=3_600)
        await self.events.publish(
            str(run.id),
            "run.interrupted",
            {
                "run_id": run.id,
                "status": run.status,
            },
        )
        return run

    async def resume_run(self, run_id: int, space_id: int) -> TaskRun:
        run = await self.get_run(run_id, space_id)
        if run.status != "interrupted":
            raise BizException(ErrorCode.TASK_STATE_INVALID, http_status=409)
        run.status = "queued"
        await self.session.commit()
        from app.core.redis_client import RedisClient

        client = await RedisClient.get()
        await client.delete(f"run:control:{run.id}")
        await self._enqueue_run(run)
        await self.session.refresh(run)
        await self.events.publish(
            str(run.id),
            "run.queued",
            {
                "run_id": run.id,
                "status": run.status,
            },
        )
        return run

    async def _enqueue_run(self, run: TaskRun, *, approval: Approval | None = None) -> None:
        repository = await self.get_scoped(Repository, run.repository_id, run.space_id)
        workspace_result = await self.session.execute(
            select(Workspace)
            .where(
                Workspace.task_run_id == run.id,
                Workspace.deleted_at.is_(None),
            )
            .order_by(Workspace.id.desc())
            .limit(1)
        )
        workspace = workspace_result.scalar_one_or_none()
        test_command = ""
        if repository.settings and isinstance(repository.settings.get("test_command"), str):
            test_command = repository.settings["test_command"]
        workflow_definition = ""
        workflow_version = ""
        if run.workflow_id is not None:
            workflow = await self.get_scoped(WorkflowDefinition, run.workflow_id, run.space_id)
            if workflow.status not in {"published", "archived"}:
                raise BizException(
                    ErrorCode.TASK_STATE_INVALID,
                    message="任务绑定的工作流版本尚未发布",
                    http_status=409,
                )
            workflow_definition = json.dumps(
                workflow.definition, ensure_ascii=False, separators=(",", ":")
            )
            workflow_version = str(run.workflow_version or workflow.version)
        engine = "langgraph"
        roles_json = ""
        if run.agent_id is not None:
            agent = await self.get_scoped(AgentDefinition, run.agent_id, run.space_id)
            roles_json = json.dumps(
                [
                    {
                        "name": agent.name,
                        "profile": agent.role,
                        "goal": agent.system_prompt,
                        "tools": agent.tool_allowlist or [
                            "list_directory",
                            "read_file",
                            "grep",
                            "git_status",
                        ],
                        "watch": [],
                    }
                ],
                ensure_ascii=False,
            )
            if agent.role in {"metagpt", "team", "metagpt_team"}:
                engine = "metagpt"
        operation = approval.operation if approval is not None else "execute_task"
        if approval is None:
            prior = await self.session.scalar(
                select(Approval)
                .where(Approval.task_run_id == run.id, Approval.status == "approved")
                .order_by(Approval.id.desc())
                .limit(1)
            )
            if prior is not None:
                operation = prior.operation
        # Plan/run-start approval unlocks the agent loop, not destructive/network ops.
        plan_approved = "true"
        capability_by_operation = {
            "destructive_command": "destructive_command",
            "git_publish": "git_publish",
            "mcp": "mcp",
            "sub_agent": "sub_agent",
        }
        capability = capability_by_operation.get(operation)
        ops_capabilities = [capability] if capability else []
        ops_approved = "true" if ops_capabilities else "false"
        clone_approved = "true" if operation == "execute_task_network_clone" else "false"
        network_capability_by_operation = {
            "network_tools": "web",
            "git_publish": "git_publish",
            "mcp": "mcp",
        }
        network_capability = network_capability_by_operation.get(operation)
        network_capabilities = [network_capability] if network_capability else []
        # Clone approval is deliberately not reusable by web/MCP/PR network tools.
        network_approved = "true" if network_capabilities else "false"
        job_prompt = run.prompt
        if operation == "git_publish":
            job_prompt = (
                f"{run.prompt}\n\n"
                "Operator follow-up: do not modify files. Open a pull request for the "
                "existing verified workspace diff using open_pull_request."
            )
        try:
            budget = run.budget_snapshot or {}
            message_id = await self.queue.enqueue(
                RunJob(
                    run_id=str(run.id),
                    prompt=job_prompt,
                    permission_mode=run.permission_mode,
                    repository_root=repository.root_path or "",
                    clone_url=repository.clone_url or "",
                    default_branch=repository.default_branch,
                    workspace=workspace.root_path if workspace else "",
                    test_command=test_command,
                    approved=plan_approved,
                    ops_approved=ops_approved,
                    ops_capabilities=json.dumps(ops_capabilities),
                    clone_approved=clone_approved,
                    network_approved=network_approved,
                    network_capabilities=json.dumps(network_capabilities),
                    workflow_definition=workflow_definition,
                    workflow_version=workflow_version,
                    engine=engine,
                    roles_json=roles_json,
                    allow_unverified=run.allow_unverified or "",
                    verification_commands=json.dumps(
                        run.verification_commands or [], ensure_ascii=False
                    ),
                    max_model_turns=str(budget.get("max_model_turns", 30)),
                    max_tool_calls=str(budget.get("max_tool_calls", 50)),
                    max_tokens=str(budget.get("max_tokens", 200_000)),
                    max_cost_usd=(
                        str(budget["max_cost_usd"])
                        if budget.get("max_cost_usd") is not None
                        else ""
                    ),
                    max_duration_seconds=str(
                        budget.get("max_duration_seconds", 1_800)
                    ),
                )
            )
        except Exception as exc:
            run.status = "failed"
            run.error_message = f"Failed to enqueue worker job: {exc}"
            run.finished_at = utcnow()
            await self.session.commit()
            await self.events.publish(
                str(run.id),
                "run.failed",
                {
                    "run_id": run.id,
                    "status": run.status,
                    "message": run.error_message,
                },
            )
            raise
        run.execution_id = message_id
        await self.session.commit()

    async def apply_worker_result(self, run_id: int, result: WorkerRunResult) -> TaskRun:
        """Persist a worker result exactly once and project it into queryable run data."""
        run_result = await self.session.execute(select(TaskRun).where(TaskRun.id == run_id))
        run = run_result.scalar_one_or_none()
        if run is None:
            raise BizException(ErrorCode.NOT_FOUND, http_status=404)
        if result.run_id != str(run_id):
            raise BizException(
                ErrorCode.PARAM_INVALID, message="回调任务编号不匹配", http_status=422
            )
        existing_verification = run.verification or {}
        if existing_verification.get("callback_applied"):
            return run

        run.status = result.status
        run.started_at = run.started_at or utcnow()
        run.finished_at = (
            utcnow() if result.status in {"succeeded", "failed", "interrupted"} else None
        )
        run.current_step = "finalize" if run.finished_at else "approval"
        run.diff_text = result.diff
        run.error_message = result.error
        run.termination_reason = result.termination_reason
        run.usage_snapshot = result.usage or {}
        if result.budgets:
            run.budget_snapshot = result.budgets
        verification_outcome = str(result.verification.get("outcome") or "")
        verification_waived = bool(result.verification.get("waived"))
        legacy_verification_passed = (
            not verification_outcome
            and bool(result.test_command)
            and result.test_exit_code == 0
        )
        passed = (
            result.status == "succeeded"
            and (
                verification_outcome == "passed"
                or verification_waived
                or legacy_verification_passed
            )
        )
        if (
            result.status == "succeeded"
            and run.permission_mode in {"edit", "full"}
            and not passed
        ):
            run.status = "failed"
            run.finished_at = utcnow()
            run.current_step = "finalize"
            run.termination_reason = "verification_blocked"
            run.error_message = (
                result.error
                or "write-capable run did not provide passing verification or an explicit waiver"
            )
        model_usage: dict[str, Any] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost_usd": 0.0,
            "models": [],
        }
        model_breakdown: dict[str, dict[str, Any]] = {}
        has_model_usage = False
        for event in result.events:
            if event.get("event") != "model_turn":
                continue
            raw_data = event.get("data")
            data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
            model_usage["prompt_tokens"] += max(int(data.get("prompt_tokens", 0) or 0), 0)
            model_usage["completion_tokens"] += max(
                int(data.get("completion_tokens", 0) or 0), 0
            )
            model_usage["cost_usd"] += max(float(data.get("cost_usd", 0.0) or 0.0), 0.0)
            model_name = str(data.get("model", "unknown"))[:255]
            item = model_breakdown.setdefault(
                model_name,
                {
                    "provider": settings.LLM_PROVIDER[:32],
                    "model": model_name,
                    "tokens": 0,
                    "cost_usd": 0.0,
                    "calls": 0,
                },
            )
            item["tokens"] += max(int(data.get("prompt_tokens", 0) or 0), 0) + max(
                int(data.get("completion_tokens", 0) or 0), 0
            )
            item["cost_usd"] += max(float(data.get("cost_usd", 0.0) or 0.0), 0.0)
            item["calls"] += 1
            has_model_usage = True
        model_usage["models"] = list(model_breakdown.values())
        if not run.usage_snapshot and has_model_usage:
            run.usage_snapshot = model_usage
        run.verification = {
            "callback_applied": True,
            "passed": passed,
            "command": result.test_command,
            "exit_code": result.test_exit_code,
            "summary": result.summary,
            "model_usage": model_usage if has_model_usage else None,
            "details": result.verification,
            "next_actions": result.next_actions,
        }

        count_result = await self.session.execute(
            select(func.count(RunStep.id)).where(RunStep.task_run_id == run_id)
        )
        sequence = int(count_result.scalar_one())
        if sequence == 0:
            for plan_item in result.plan:
                self.session.add(
                    RunStep(
                        task_run_id=run_id,
                        sequence=sequence,
                        role="planner",
                        name=plan_item[:128],
                        status="succeeded" if result.status == "succeeded" else "failed",
                        output={"summary": plan_item},
                        started_at=run.started_at,
                        finished_at=run.finished_at,
                    )
                )
                sequence += 1

        terminal_lines: list[str] = []
        for event in result.events:
            if event.get("event") != "tool_result":
                continue
            raw_data = event.get("data")
            data = raw_data if isinstance(raw_data, dict) else {}
            raw_structured = data.get("result")
            structured = raw_structured if isinstance(raw_structured, dict) else {}
            tool_status = str(structured.get("status") or data.get("status", "failed"))
            persisted_status = {
                "succeeded": "succeeded",
                "success": "succeeded",
                "blocked": "blocked",
                "warning": "blocked",
                "approval_required": "blocked",
            }.get(tool_status, "failed")
            summary = str(structured.get("summary") or data.get("summary", ""))
            tool_name = str(data.get("tool", "unknown"))
            root_cause = structured.get("root_cause") or structured.get("error_root_cause")
            retry = structured.get("retry") or structured.get("retry_hint")
            stop = structured.get("stop_condition") or structured.get("stop_reason")
            artifacts = structured.get("artifacts")
            if not isinstance(artifacts, list):
                artifacts = []
            tool_input = data.get("arguments") if isinstance(data.get("arguments"), dict) else None
            if data.get("call_id"):
                tool_input = {**(tool_input or {}), "_call_id": data["call_id"]}
            terminal_lines.append(f"{tool_name}: {summary}")
            self.session.add(
                ToolInvocation(
                    task_run_id=run_id,
                    agent_name=str(data.get("agent", "worker"))[:64],
                    tool_name=tool_name[:64],
                    input=tool_input,
                    output={
                        "status": persisted_status,
                        "summary": summary,
                        "next_actions": structured.get("next_actions", []),
                        "artifacts": artifacts,
                        "data": structured.get("data"),
                        "error_root_cause": root_cause,
                        "retry_hint": retry,
                        "stop_reason": stop,
                    },
                    success=int(persisted_status == "succeeded"),
                    status=persisted_status,
                    error_root_cause=str(root_cause) if root_cause else None,
                    retry_hint=str(retry) if retry else None,
                    duration_ms=int(data.get("duration_ms", 0) or 0),
                )
            )

        artifact_rows: list[Artifact] = []
        if result.diff:
            artifact_rows.append(
                Artifact(
                    task_run_id=run_id,
                    kind="diff",
                    name="changes.diff",
                    mime_type="text/x-diff",
                    size=len(result.diff.encode()),
                    metadata_={"content": result.diff},
                )
            )
        if result.test_command:
            artifact_rows.append(
                Artifact(
                    task_run_id=run_id,
                    kind="test_report",
                    name="verification.json",
                    mime_type="application/json",
                    metadata_={
                        "command": result.test_command,
                        "exit_code": result.test_exit_code,
                        "passed": passed,
                        "summary": result.summary,
                    },
                )
            )
        if terminal_lines:
            content = "\n".join(terminal_lines)
            artifact_rows.append(
                Artifact(
                    task_run_id=run_id,
                    kind="log",
                    name="terminal.log",
                    mime_type="text/plain",
                    size=len(content.encode()),
                    metadata_={"content": content},
                )
            )
        for item in result.artifacts:
            artifact_rows.append(
                Artifact(
                    task_run_id=run_id,
                    kind=str(item.get("kind", "other"))[:32],
                    name=str(item.get("path") or item.get("name") or "artifact")[-255:],
                    path=str(item.get("path")) if item.get("path") else None,
                    metadata_={"description": item.get("description", "")},
                )
            )
        self.session.add_all(artifact_rows)
        await self.session.commit()
        if run.started_at is not None and run.finished_at is not None:
            record_task_run(
                run.status,
                max((run.finished_at - run.started_at).total_seconds(), 0.0),
            )
        for event in result.events:
            raw_data = event.get("data")
            data = raw_data if isinstance(raw_data, dict) else {}
            if event.get("event") == "tool_result":
                raw_structured = data.get("result")
                structured = raw_structured if isinstance(raw_structured, dict) else {}
                raw_status = str(structured.get("status") or data.get("status", "failed"))
                status = {
                    "succeeded": "succeeded",
                    "success": "succeeded",
                    "blocked": "blocked",
                    "warning": "blocked",
                    "approval_required": "blocked",
                }.get(raw_status, "failed")
                record_tool_invocation(
                    str(data.get("tool", "unknown")),
                    status,
                    max(float(data.get("duration_ms", 0) or 0) / 1000, 0.0),
                )
            elif event.get("event") == "model_turn":
                record_model_usage(
                    settings.LLM_PROVIDER,
                    prompt_tokens=int(data.get("prompt_tokens", 0) or 0),
                    completion_tokens=int(data.get("completion_tokens", 0) or 0),
                    cost_usd=float(data.get("cost_usd", 0.0) or 0.0),
                )
        await self.session.refresh(run)
        await self.events.publish(
            str(run_id),
            "result.persisted",
            {
                "run_id": run_id,
                "status": run.status,
                "verified": passed,
            },
        )
        return run

    async def list_artifacts(self, run_id: int, space_id: int) -> list[Artifact]:
        await self.get_run(run_id, space_id)
        result = await self.session.execute(
            select(Artifact)
            .where(Artifact.task_run_id == run_id, Artifact.deleted_at.is_(None))
            .order_by(Artifact.id)
        )
        return list(result.scalars().all())

    async def create_artifact(self, run_id: int, space_id: int, payload: BaseModel) -> Artifact:
        await self.get_run(run_id, space_id)
        data = payload.model_dump(exclude_unset=True)
        if "metadata" in data:
            data["metadata_"] = data.pop("metadata")
        artifact = Artifact(task_run_id=run_id, **data)
        self.session.add(artifact)
        await self.session.commit()
        await self.session.refresh(artifact)
        await self.events.publish(
            str(run_id),
            "artifact.created",
            {
                "run_id": run_id,
                "artifact_id": artifact.id,
                "kind": artifact.kind,
            },
        )
        return artifact

    async def list_steps(self, run_id: int, space_id: int) -> list[RunStep]:
        await self.get_run(run_id, space_id)
        result = await self.session.execute(
            select(RunStep).where(RunStep.task_run_id == run_id).order_by(RunStep.sequence)
        )
        return list(result.scalars().all())

    async def create_step(self, run_id: int, space_id: int, payload: BaseModel) -> RunStep:
        await self.get_run(run_id, space_id)
        step = RunStep(task_run_id=run_id, **payload.model_dump(exclude_unset=True))
        self.session.add(step)
        await self.session.commit()
        await self.session.refresh(step)
        await self.events.publish(
            str(run_id),
            "step.updated",
            {
                "run_id": run_id,
                "step_id": step.id,
                "status": step.status,
                "role": step.role,
                "name": step.name,
            },
        )
        return step

    async def list_tool_invocations(self, run_id: int, space_id: int) -> list[ToolInvocation]:
        await self.get_run(run_id, space_id)
        result = await self.session.execute(
            select(ToolInvocation)
            .where(ToolInvocation.task_run_id == run_id, ToolInvocation.deleted_at.is_(None))
            .order_by(ToolInvocation.id)
        )
        return list(result.scalars().all())

    async def create_tool_invocation(
        self, run_id: int, space_id: int, payload: BaseModel
    ) -> ToolInvocation:
        await self.get_run(run_id, space_id)
        data = payload.model_dump()
        result = data.pop("result")
        if data.get("run_step_id") is not None:
            step = await self.session.get(RunStep, data["run_step_id"])
            if step is None or step.task_run_id != run_id:
                raise BizException(
                    ErrorCode.PARAM_INVALID, message="步骤与任务不匹配", http_status=422
                )
        invocation = ToolInvocation(
            task_run_id=run_id,
            output=result,
            success=int(result["status"] == "succeeded"),
            status=result["status"],
            error_root_cause=result.get("error_root_cause"),
            retry_hint=result.get("retry_hint"),
            **data,
        )
        self.session.add(invocation)
        await self.session.commit()
        await self.session.refresh(invocation)
        await self.events.publish(
            str(run_id),
            "tool.completed",
            {
                "run_id": run_id,
                "tool_invocation_id": invocation.id,
                "tool_name": invocation.tool_name,
                "status": invocation.status,
            },
        )
        return invocation

    async def create_relation(self, space_id: int, payload: BaseModel) -> KnowledgeRelation:
        data = payload.model_dump()
        await self.get_scoped(KnowledgeEntity, data["source_entity_id"], space_id)
        await self.get_scoped(KnowledgeEntity, data["target_entity_id"], space_id)
        return await self.create_scoped(KnowledgeRelation, space_id, data)

    async def workflow_replay(self, run_id: int, space_id: int) -> dict[str, Any]:
        run = await self.get_run(run_id, space_id)
        if run.workflow_id is None:
            return {"task_run_id": run.id, "workflow": None, "steps": []}
        workflow = await self.get_scoped(WorkflowDefinition, run.workflow_id, space_id)
        step_result = await self.session.execute(
            select(RunStep)
            .where(RunStep.task_run_id == run.id, RunStep.deleted_at.is_(None))
            .order_by(RunStep.sequence)
        )
        return {
            "task_run_id": run.id,
            "workflow": {
                "id": workflow.id,
                "name": workflow.name,
                "version": run.workflow_version,
                "definition": workflow.definition,
            },
            "steps": [
                {
                    "id": step.id,
                    "sequence": step.sequence,
                    "role": step.role,
                    "name": step.name,
                    "status": step.status,
                    "output": step.output,
                    "error_message": step.error_message,
                }
                for step in step_result.scalars().all()
            ],
        }

    async def explore_knowledge_graph(
        self, space_id: int, user_id: int, payload: KnowledgeGraphExplore
    ) -> KnowledgeGraphExploreOut:
        await self.require_space_member(space_id, user_id)
        truncated = False
        if payload.entity_id is not None:
            seeds = [await self.get_scoped(KnowledgeEntity, payload.entity_id, space_id)]
        else:
            statement = select(KnowledgeEntity).where(
                KnowledgeEntity.space_id == space_id,
                KnowledgeEntity.deleted_at.is_(None),
            )
            if payload.query:
                pattern = f"%{payload.query}%"
                statement = statement.where(
                    or_(
                        KnowledgeEntity.name.ilike(pattern),
                        KnowledgeEntity.entity_type.ilike(pattern),
                    )
                )
            if payload.entity_types:
                statement = statement.where(KnowledgeEntity.entity_type.in_(payload.entity_types))
            result = await self.session.execute(
                statement.order_by(KnowledgeEntity.id.desc()).limit(payload.limit + 1)
            )
            seed_rows = list(result.scalars().all())
            truncated = len(seed_rows) > payload.limit
            seeds = seed_rows[: payload.limit]

        entities: dict[int, KnowledgeEntity] = {entity.id: entity for entity in seeds}
        relations: dict[int, KnowledgeRelation] = {}
        frontier = set(entities)
        relation_limit = min(payload.limit * 2, 200)
        for _ in range(payload.depth):
            if not frontier or len(relations) >= relation_limit:
                break
            result = await self.session.execute(
                select(KnowledgeRelation)
                .where(
                    KnowledgeRelation.space_id == space_id,
                    KnowledgeRelation.deleted_at.is_(None),
                    or_(
                        KnowledgeRelation.source_entity_id.in_(frontier),
                        KnowledgeRelation.target_entity_id.in_(frontier),
                    ),
                )
                .order_by(KnowledgeRelation.id)
                .limit(relation_limit - len(relations) + 1)
            )
            relation_rows = list(result.scalars().all())
            if len(relation_rows) > relation_limit - len(relations):
                truncated = True
            relation_rows = relation_rows[: relation_limit - len(relations)]
            candidate_ids = {
                entity_id
                for relation in relation_rows
                for entity_id in (relation.source_entity_id, relation.target_entity_id)
                if entity_id not in entities
            }
            if candidate_ids:
                entity_result = await self.session.execute(
                    select(KnowledgeEntity).where(
                        KnowledgeEntity.space_id == space_id,
                        KnowledgeEntity.deleted_at.is_(None),
                        KnowledgeEntity.id.in_(candidate_ids),
                    )
                )
                candidates = list(entity_result.scalars().all())
            else:
                candidates = []
            next_frontier: set[int] = set()
            for entity in candidates:
                if len(entities) >= payload.limit:
                    truncated = True
                    break
                entities[entity.id] = entity
                next_frontier.add(entity.id)
            for relation in relation_rows:
                if (
                    relation.source_entity_id in entities
                    and relation.target_entity_id in entities
                ):
                    relations[relation.id] = relation
                else:
                    truncated = True
            frontier = next_frontier

        evidence_chain = [
            KnowledgeEvidenceLink(
                kind="relation",
                relation_id=relation.id,
                source_entity_id=relation.source_entity_id,
                target_entity_id=relation.target_entity_id,
                relation_type=relation.relation_type,
                evidence=relation.evidence,
            )
            for relation in relations.values()
            if relation.evidence
        ]
        evidence_chain.extend(
            KnowledgeEvidenceLink(
                kind="entity",
                entity_id=entity.id,
                evidence=entity.source_refs,
            )
            for entity in entities.values()
            if entity.source_refs
        )
        if not entities:
            evidence_status = "no_matches"
        elif not evidence_chain:
            evidence_status = "no_source_evidence"
        else:
            evidence_status = "sufficient"
        return KnowledgeGraphExploreOut(
            entities=[KnowledgeEntityOut.model_validate(item) for item in entities.values()],
            relations=[KnowledgeRelationOut.model_validate(item) for item in relations.values()],
            evidence_chain=evidence_chain,
            evidence_sufficient=evidence_status == "sufficient",
            evidence_status=evidence_status,
            truncated=truncated,
            retrieval_mode="relational_graph",
        )


TOOL_CATALOG = [
    ("list_directory", "read_only", "List a directory inside the workspace."),
    ("read_file", "read_only", "Read a file inside the workspace."),
    ("grep", "read_only", "Search workspace text with bounded results."),
    ("exact_edit", "edit", "Apply an exact, auditable file edit."),
    ("write_file", "edit", "Create a file inside the workspace."),
    ("terminal", "execute", "Run a policy-checked command."),
    ("run_tests", "execute", "Run focused automated verification."),
    ("git_status", "read_only", "Inspect repository status."),
    ("git_diff", "read_only", "Inspect repository changes."),
    ("web_search", "full", "Search the network after approval."),
    ("web_fetch", "full", "Fetch an approved network resource."),
    ("todo", "read_only", "Maintain the run task list."),
    ("background_command", "execute", "Run a bounded background process."),
    ("sub_agent", "full", "Delegate a bounded task."),
    ("knowledge_search", "read_only", "Search retained project knowledge."),
    ("mcp", "full", "Invoke an approved MCP capability."),
]


def tool_descriptors() -> list[dict[str, Any]]:
    result_schema = {
        "required": ["status", "summary", "next_actions", "artifacts"],
        "properties": {
            "status": {"enum": ["succeeded", "failed", "blocked"]},
            "summary": {"type": "string"},
            "next_actions": {"type": "array"},
            "artifacts": {"type": "array"},
            "data": {},
            "error_root_cause": {"type": ["string", "null"]},
            "retry_hint": {"type": ["string", "null"]},
            "stop_reason": {"type": ["string", "null"]},
        },
    }
    return [
        {
            "name": name,
            "permission": permission,
            "description": description,
            "result_contract": result_schema,
        }
        for name, permission, description in TOOL_CATALOG
    ]


def _probe_repository(root_path: str) -> dict[str, Any]:
    root = Path(root_path).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repository root_path is not a directory")
    ignored = {".git", ".venv", "node_modules", "dist", "build", "__pycache__"}
    extensions: Counter[str] = Counter()
    file_count = 0
    directory_count = 0
    truncated = False
    pending = [root]
    while pending:
        directory = pending.pop()
        directory_count += 1
        for entry in directory.iterdir():
            if entry.name in ignored:
                continue
            if entry.is_dir():
                pending.append(entry)
                continue
            if entry.is_file():
                file_count += 1
                extensions[entry.suffix.lower() or "(none)"] += 1
                if file_count >= 100_000:
                    truncated = True
                    pending.clear()
                    break
    return {
        "root_path": str(root),
        "file_count": file_count,
        "directory_count": directory_count,
        "is_git_repository": (root / ".git").exists(),
        "top_extensions": dict(extensions.most_common(20)),
        "truncated": truncated,
    }
