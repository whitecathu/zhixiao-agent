from pathlib import Path

import pytest

from zhixiao_agent.runner import LocalRunner
from zhixiao_agent.security import CommandPolicy, PermissionDenied
from zhixiao_agent.tools import (
    ExactEditTool,
    GrepTool,
    ListDirectoryTool,
    ReadFileTool,
    TodoTool,
    ToolContext,
    WriteFileTool,
)
from zhixiao_agent.types import PermissionMode, ToolStatus


def _context(workspace: Path, permission: PermissionMode) -> ToolContext:
    return ToolContext(
        workspace=workspace,
        permission=permission,
        runner=LocalRunner(workspace),
    )


@pytest.mark.asyncio
async def test_read_and_exact_edit_respect_permissions(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    readonly = ToolContext(
        workspace=tmp_path,
        permission=PermissionMode.READ_ONLY,
        runner=LocalRunner(tmp_path),
    )
    read = await ReadFileTool().execute({"path": "app.py"}, readonly)
    denied = await ExactEditTool().execute(
        {"path": "app.py", "old_text": "1", "new_text": "2"}, readonly
    )

    assert read.status is ToolStatus.SUCCESS
    assert "1:value = 1" in read.data
    assert denied.status is ToolStatus.ERROR
    assert source.read_text(encoding="utf-8") == "value = 1\n"

    editable = readonly.model_copy(update={"permission": PermissionMode.EDIT})
    changed = await ExactEditTool().execute(
        {"path": "app.py", "old_text": "value = 1", "new_text": "value = 2"}, editable
    )
    assert changed.status is ToolStatus.SUCCESS
    assert source.read_text(encoding="utf-8") == "value = 2\n"


@pytest.mark.asyncio
async def test_todo_enforces_single_in_progress(tmp_path: Path) -> None:
    context = ToolContext(
        workspace=tmp_path,
        permission=PermissionMode.READ_ONLY,
        runner=LocalRunner(tmp_path),
    )
    result = await TodoTool().execute(
        {
            "replace": True,
            "todos": [
                {"id": "a", "content": "A", "status": "in_progress"},
                {"id": "b", "content": "B", "status": "in_progress"},
            ],
        },
        context,
    )
    assert result.status is ToolStatus.ERROR


@pytest.mark.asyncio
async def test_list_directory_stays_inside_workspace(tmp_path: Path) -> None:
    (tmp_path / "visible.txt").write_text("ok\n", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "inner.txt").write_text("inner\n", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret\n", encoding="utf-8")
    context = _context(tmp_path, PermissionMode.READ_ONLY)

    listed = await ListDirectoryTool().execute({"path": "."}, context)
    assert listed.status is ToolStatus.SUCCESS
    assert "visible.txt" in listed.data
    assert "nested/" in listed.data

    parent = await ListDirectoryTool().execute({"path": ".."}, context)
    escaped = await ListDirectoryTool().execute({"path": str(outside)}, context)
    assert parent.status is ToolStatus.ERROR
    assert escaped.status is ToolStatus.ERROR


@pytest.mark.asyncio
async def test_grep_finds_workspace_match(tmp_path: Path) -> None:
    marker = "ZX_GREP_UNIQUE_TOKEN_9f3a2b"
    (tmp_path / "notes.md").write_text(f"header\n{marker}\nfooter\n", encoding="utf-8")
    context = _context(tmp_path, PermissionMode.READ_ONLY)

    found = await GrepTool().execute({"pattern": marker}, context)
    assert found.status is ToolStatus.SUCCESS
    assert found.data
    assert found.data[0]["path"] == "notes.md"
    assert found.data[0]["text"] == marker
    assert found.data[0]["line"] == 2


@pytest.mark.asyncio
async def test_write_file_denied_in_read_only(tmp_path: Path) -> None:
    existing = tmp_path / "kept.txt"
    existing.write_text("original\n", encoding="utf-8")
    target = tmp_path / "created.txt"
    context = _context(tmp_path, PermissionMode.READ_ONLY)

    created = await WriteFileTool().execute(
        {"path": "created.txt", "content": "should-not-write\n"}, context
    )
    overwritten = await WriteFileTool().execute(
        {"path": "kept.txt", "content": "mutated\n", "overwrite": True}, context
    )

    assert created.status is ToolStatus.ERROR
    assert overwritten.status is ToolStatus.ERROR
    assert not target.exists()
    assert existing.read_text(encoding="utf-8") == "original\n"


@pytest.mark.asyncio
async def test_write_file_allowed_in_edit(tmp_path: Path) -> None:
    context = _context(tmp_path, PermissionMode.EDIT)
    written = await WriteFileTool().execute(
        {"path": "notes.txt", "content": "hello from edit\n"}, context
    )
    target = tmp_path / "notes.txt"
    assert written.status is ToolStatus.SUCCESS
    assert target.read_text(encoding="utf-8") == "hello from edit\n"


@pytest.mark.asyncio
async def test_dangerous_commands_require_explicit_approval(tmp_path: Path) -> None:
    context = _context(tmp_path, PermissionMode.FULL)
    policy = CommandPolicy()
    for command in ("git push origin main", "rm -rf /tmp/x"):
        with pytest.raises(PermissionDenied):
            policy.validate(command, context.permission, approved=False)
        policy.validate(command, context.permission, approved=True)
