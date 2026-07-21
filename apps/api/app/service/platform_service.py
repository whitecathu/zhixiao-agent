"""Business rules for repositories, run lifecycle, configuration, and graph data."""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import ErrorCode
from app.core.events import EventBroker
from app.core.exceptions import BizException
from app.core.jobs import RunJob, RunQueue
from app.model.base import Base
from app.model.knowledge import ToolInvocation
from app.model.platform import (
    AgentDefinition,
    Approval,
    Artifact,
    KnowledgeEntity,
    KnowledgeRelation,
    Repository,
    RunStep,
    TaskRun,
    WorkflowDefinition,
    Workspace,
)
from app.schema.platform import (
    AgentUpdate,
    ApprovalDecision,
    ModelProfileUpdate,
    TaskRunCreate,
    WorkerRunResult,
    WorkflowUpdate,
)

ModelT = TypeVar("ModelT", bound=Base)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


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

    async def update_workflow(
        self, workflow_id: int, space_id: int, payload: WorkflowUpdate
    ) -> WorkflowDefinition:
        current = await self.get_scoped(WorkflowDefinition, workflow_id, space_id)
        name = payload.name or current.name
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
            definition=payload.definition or current.definition,
            enabled=current.enabled if payload.enabled is None else payload.enabled,
        )
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def update_agent(
        self, agent_id: int, space_id: int, payload: AgentUpdate
    ) -> AgentDefinition:
        agent = await self.get_scoped(AgentDefinition, agent_id, space_id)
        data = payload.model_dump(exclude_unset=True)
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

    async def create_run(self, space_id: int, user_id: int, payload: TaskRunCreate) -> TaskRun:
        repository = await self.get_scoped(Repository, payload.repository_id, space_id)
        if payload.workflow_id is not None:
            await self.get_scoped(WorkflowDefinition, payload.workflow_id, space_id)
        if payload.agent_id is not None:
            await self.get_scoped(AgentDefinition, payload.agent_id, space_id)

        run = TaskRun(
            space_id=space_id,
            user_id=user_id,
            status="awaiting_approval",
            **payload.model_dump(),
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

    async def list_runs(self, space_id: int) -> list[TaskRun]:
        return await self.list_scoped(TaskRun, space_id)

    async def list_approvals(self, run_id: int, space_id: int) -> list[Approval]:
        await self.get_run(run_id, space_id)
        result = await self.session.execute(
            select(Approval)
            .where(Approval.task_run_id == run_id, Approval.deleted_at.is_(None))
            .order_by(Approval.id)
        )
        return list(result.scalars().all())

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

        approval.status = payload.decision
        approval.comment = payload.comment
        approval.decided_by = user_id
        approval.decided_at = utcnow()
        if payload.decision == "approved":
            run.status = "queued"
            event_name = "run.queued"
        else:
            run.status = "cancelled"
            run.finished_at = utcnow()
            event_name = "run.cancelled"
        await self.session.commit()
        if payload.decision == "approved":
            await self._enqueue_run(run)
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
        await self.events.publish(
            str(run.id),
            event_name,
            {
                "run_id": run.id,
                "status": run.status,
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

    async def _enqueue_run(self, run: TaskRun) -> None:
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
        try:
            message_id = await self.queue.enqueue(
                RunJob(
                    run_id=str(run.id),
                    prompt=run.prompt,
                    permission_mode=run.permission_mode,
                    repository_root=repository.root_path or "",
                    clone_url=repository.clone_url or "",
                    default_branch=repository.default_branch,
                    workspace=workspace.root_path if workspace else "",
                    test_command=test_command,
                    network_approved=str(
                        bool(
                            repository.clone_url and not repository.root_path and workspace is None
                        )
                    ).lower(),
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
        passed = result.status == "succeeded" and result.test_exit_code in {None, 0}
        run.verification = {
            "callback_applied": True,
            "passed": passed,
            "command": result.test_command,
            "exit_code": result.test_exit_code,
            "summary": result.summary,
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
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            structured = data.get("result") if isinstance(data.get("result"), dict) else {}
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
