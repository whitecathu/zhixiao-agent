"""Tests for workspace semantic/keyword indexing."""

from __future__ import annotations

from pathlib import Path

import pytest

from zhixiao_agent.rag.vector import InMemoryVectorStore
from zhixiao_agent.rag.workspace_index import (
    DEFAULT_INDEX_RELATIVE,
    index_exists,
    index_workspace,
    search_workspace,
)
from zhixiao_agent.runner import LocalRunner
from zhixiao_agent.tools.base import ToolContext
from zhixiao_agent.tools.integrations import KnowledgeSearchTool
from zhixiao_agent.types import PermissionMode, ToolStatus


@pytest.mark.asyncio
async def test_index_and_search_workspace_jsonl(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "api.py").write_text(
        "def create_task():\n    return FastAPI contract helper\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "ui.ts").write_text(
        "export const label = 'Vue component'\n",
        encoding="utf-8",
    )
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text("should not be indexed", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("ignored", encoding="utf-8")

    report = await index_workspace(tmp_path)
    assert report.chunks >= 2
    assert report.files == 2
    assert index_exists(tmp_path)
    assert (tmp_path / DEFAULT_INDEX_RELATIVE).is_file()

    hits = await search_workspace(tmp_path, "FastAPI contract", limit=4)
    assert hits
    assert hits[0].path == "src/api.py"
    assert "FastAPI" in hits[0].text


@pytest.mark.asyncio
async def test_index_workspace_optional_vector_store(tmp_path: Path) -> None:
    (tmp_path / "readme.md").write_text("workspace vector index demo\n", encoding="utf-8")
    store = InMemoryVectorStore()
    report = await index_workspace(tmp_path, store=store)
    assert report.chunks == 1
    hits = await search_workspace(tmp_path, "vector index", limit=3, store=store)
    assert hits
    assert hits[0].path == "readme.md"


@pytest.mark.asyncio
async def test_knowledge_search_prefers_workspace_index(tmp_path: Path) -> None:
    (tmp_path / "lib.py").write_text("semantic retrieval ranking helper\n", encoding="utf-8")
    await index_workspace(tmp_path)
    knowledge = tmp_path / ".zhixiao" / "knowledge.jsonl"
    knowledge.write_text(
        '{"text": "unrelated memory record"}\n',
        encoding="utf-8",
    )
    ctx = ToolContext(
        workspace=tmp_path,
        permission=PermissionMode.READ_ONLY,
        runner=LocalRunner(tmp_path),
    )
    result = await KnowledgeSearchTool().execute({"query": "semantic retrieval"}, ctx)
    assert result.status is ToolStatus.SUCCESS
    assert result.data["channel"] == "workspace_index"
    assert result.data["degraded"] is False
    assert "lib.py" in result.data["hits"][0]["source_path"]
