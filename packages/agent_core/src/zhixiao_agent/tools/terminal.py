from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..security import PermissionDenied, required_command_capability
from ..types import Artifact, ToolResult
from .base import BaseTool, ToolContext


class TerminalInput(BaseModel):
    command: str = Field(min_length=1)
    timeout: int = Field(default=120, ge=1, le=3600)


class TerminalTool(BaseTool):
    name = "terminal"
    description = "Execute one non-shell command in the workspace under the command policy."
    input_model = TerminalInput

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            request = self.validate(arguments)
            capability = required_command_capability(request.command)
            result = await context.runner.run(
                request.command,
                permission=context.permission,
                timeout=request.timeout,
                approved=capability is None or context.allows(capability),
            )
            data = result.model_dump()
            if result.exit_code == 0:
                return ToolResult.ok("command completed successfully", data)
            return ToolResult.error(
                "command failed",
                root_cause=result.stderr[-4000:] or f"exit code {result.exit_code}",
                retry="inspect the output, fix the cause, and run a focused command",
                stop_condition="stop after the same root cause occurs three times",
            ).model_copy(update={"data": data})
        except (PermissionDenied, OSError, ValueError) as exc:
            return ToolResult.error(
                "command was not executed",
                root_cause=str(exc),
                retry="request the required permission or use an allowed command",
            )


class TestInput(TerminalInput):
    report_path: str | None = None


class TestTool(TerminalTool):
    name = "run_tests"
    description = "Run a focused test command and return a verification result."
    input_model = TestInput

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        result = await super().execute(arguments, context)
        request = self.validate(arguments)
        if request.report_path:
            result.artifacts.append(
                Artifact(kind="test_report", path=request.report_path, description="test report")
            )
        return result
