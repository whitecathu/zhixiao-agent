from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from ..security import PermissionDenied, WorkspaceViolation, require_write
from ..types import Artifact, ToolResult
from .base import BaseTool, ToolContext


class PathInput(BaseModel):
    path: str = "."


class ListDirectoryInput(PathInput):
    recursive: bool = False
    limit: int = Field(default=200, ge=1, le=2000)


class ListDirectoryTool(BaseTool):
    name = "list_directory"
    description = "List workspace files without reading their content."
    input_model = ListDirectoryInput

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            request = self.validate(arguments)
            directory = context.boundary.resolve(request.path, must_exist=True)
            if not directory.is_dir():
                return ToolResult.error("path is not a directory", root_cause=str(directory))
            iterator = directory.rglob("*") if request.recursive else directory.iterdir()
            ignored = {".git", ".venv", "node_modules", "__pycache__", "dist", "build"}
            items: list[str] = []
            for item in iterator:
                if any(part in ignored for part in item.parts):
                    continue
                suffix = "/" if item.is_dir() else ""
                items.append(item.relative_to(context.workspace.resolve()).as_posix() + suffix)
                if len(items) >= request.limit:
                    break
            return ToolResult.ok(f"listed {len(items)} entries", sorted(items))
        except (OSError, WorkspaceViolation, ValueError) as exc:
            return ToolResult.error(
                "unable to list directory",
                root_cause=str(exc),
                retry="use a path inside the workspace",
            )


class ReadFileInput(PathInput):
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    max_bytes: int = Field(default=200_000, ge=1, le=2_000_000)


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read a UTF-8 text file inside the workspace with optional line bounds."
    input_model = ReadFileInput

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            request = self.validate(arguments)
            path = context.boundary.resolve(request.path, must_exist=True)
            if not path.is_file():
                return ToolResult.error("path is not a file", root_cause=str(path))
            if path.stat().st_size > request.max_bytes:
                return ToolResult.error(
                    "file exceeds read limit",
                    root_cause=f"{path.stat().st_size} bytes > {request.max_bytes}",
                    retry="request a smaller file or increase max_bytes within the allowed limit",
                )
            lines = path.read_text(encoding="utf-8").splitlines()
            end = request.end_line or len(lines)
            selected = lines[request.start_line - 1 : end]
            content = "\n".join(
                f"{line_number}:{line}"
                for line_number, line in enumerate(selected, start=request.start_line)
            )
            return ToolResult.ok(f"read {len(selected)} lines from {request.path}", content)
        except (OSError, UnicodeError, WorkspaceViolation, ValueError) as exc:
            return ToolResult.error(
                "unable to read file",
                root_cause=str(exc),
                retry="verify the path and UTF-8 encoding",
            )


class GrepInput(BaseModel):
    pattern: str
    path: str = "."
    glob: str = "*"
    ignore_case: bool = False
    limit: int = Field(default=200, ge=1, le=2000)


class GrepTool(BaseTool):
    name = "grep"
    description = "Search text files in the workspace using a regular expression."
    input_model = GrepInput

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            request = self.validate(arguments)
            root = context.boundary.resolve(request.path, must_exist=True)
            regex = re.compile(request.pattern, re.IGNORECASE if request.ignore_case else 0)
            files = [root] if root.is_file() else root.rglob(request.glob)
            matches: list[dict[str, Any]] = []
            for path in files:
                if not path.is_file() or any(
                    p in {".git", "node_modules", ".venv"} for p in path.parts
                ):
                    continue
                try:
                    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                        if regex.search(line):
                            matches.append(
                                {
                                    "path": path.relative_to(
                                        context.workspace.resolve()
                                    ).as_posix(),
                                    "line": number,
                                    "text": line,
                                }
                            )
                            if len(matches) >= request.limit:
                                return ToolResult.ok(
                                    f"found at least {len(matches)} matches", matches
                                )
                except (UnicodeError, OSError):
                    continue
            return ToolResult.ok(f"found {len(matches)} matches", matches)
        except (re.error, OSError, WorkspaceViolation, ValueError) as exc:
            return ToolResult.error(
                "search failed", root_cause=str(exc), retry="check the regex and path"
            )


class WriteFileInput(PathInput):
    content: str
    overwrite: bool = False


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Create a UTF-8 file; overwriting requires the overwrite flag."
    input_model = WriteFileInput

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            require_write(context.permission)
            request = self.validate(arguments)
            path = context.boundary.resolve(request.path)
            if path.exists() and not request.overwrite:
                return ToolResult.error(
                    "file already exists",
                    root_cause=str(path),
                    retry="use exact_edit or explicitly set overwrite after reading the file",
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(request.content, encoding="utf-8")
            return ToolResult.ok(
                f"wrote {len(request.content)} characters",
                artifacts=[Artifact(kind="file", path=str(path), description="written file")],
            )
        except (OSError, WorkspaceViolation, PermissionDenied, ValueError) as exc:
            return ToolResult.error(
                "write failed", root_cause=str(exc), retry="check permission and path"
            )


class ExactEditInput(PathInput):
    old_text: str = Field(min_length=1)
    new_text: str
    replace_all: bool = False


class ExactEditTool(BaseTool):
    name = "exact_edit"
    description = "Replace an exact, normally unique string in an existing UTF-8 file."
    input_model = ExactEditInput

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            require_write(context.permission)
            request = self.validate(arguments)
            path = context.boundary.resolve(request.path, must_exist=True)
            content = path.read_text(encoding="utf-8")
            count = content.count(request.old_text)
            if count == 0:
                return ToolResult.error(
                    "target text was not found",
                    root_cause=request.path,
                    retry="read the current file and use an exact substring",
                )
            if count > 1 and not request.replace_all:
                return ToolResult.error(
                    "target text is not unique",
                    root_cause=f"{count} matches",
                    retry="provide more context or set replace_all",
                )
            updated = content.replace(
                request.old_text, request.new_text, -1 if request.replace_all else 1
            )
            path.write_text(updated, encoding="utf-8")
            return ToolResult.ok(
                f"replaced {count if request.replace_all else 1} occurrence(s)",
                artifacts=[Artifact(kind="file", path=str(path), description="edited file")],
            )
        except (OSError, UnicodeError, WorkspaceViolation, PermissionDenied, ValueError) as exc:
            return ToolResult.error(
                "edit failed", root_cause=str(exc), retry="check permission and path"
            )
