from pathlib import Path

import pytest

from zhixiao_agent.runner import LocalRunner
from zhixiao_agent.tools import ExactEditTool, ReadFileTool, TodoTool, ToolContext
from zhixiao_agent.types import PermissionMode, ToolStatus


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
