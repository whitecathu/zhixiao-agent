"""Workspace text index: chunk files into JSONL keyword store or optional VectorStore."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .vector import InMemoryVectorStore, VectorRecord, VectorStore

DEFAULT_INDEX_RELATIVE = Path(".zhixiao") / "index.jsonl"
SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        "node_modules",
        ".zhixiao-worktrees",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
    }
)
TEXT_SUFFIXES = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".vue",
        ".md",
        ".txt",
        ".rst",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".css",
        ".scss",
        ".html",
        ".sql",
        ".sh",
        ".ps1",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
    }
)
MAX_FILE_BYTES = 256_000
CHUNK_CHARS = 1_200
CHUNK_OVERLAP = 120


@dataclass(frozen=True, slots=True)
class IndexChunk:
    id: str
    path: str
    start: int
    text: str

    def as_record(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "start": self.start,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class IndexHit:
    path: str
    score: float
    text: str
    chunk_id: str
    start: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "score": self.score,
            "text": self.text,
            "chunk_id": self.chunk_id,
            "start": self.start,
        }


@dataclass(frozen=True, slots=True)
class IndexReport:
    files: int
    chunks: int
    index_path: str | None = None


def _should_skip_dir(name: str) -> bool:
    return name in SKIP_DIR_NAMES


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES


def _chunk_text(
    text: str, *, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP
) -> list[tuple[int, str]]:
    if size < 1:
        raise ValueError("chunk size must be positive")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be in [0, size)")
    cleaned = text.replace("\r\n", "\n")
    if not cleaned.strip():
        return []
    chunks: list[tuple[int, str]] = []
    start = 0
    length = len(cleaned)
    while start < length:
        end = min(start + size, length)
        piece = cleaned[start:end]
        if piece.strip():
            chunks.append((start, piece))
        if end >= length:
            break
        start = max(0, end - overlap)
    return chunks


def _chunk_id(relative_path: str, start: int, text: str) -> str:
    digest = hashlib.blake2b(f"{relative_path}:{start}:{text}".encode(), digest_size=8).hexdigest()
    return f"{relative_path}:{start}:{digest}"


def iter_workspace_files(workspace: Path) -> Iterable[Path]:
    root = workspace.resolve()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            relative_parts = path.relative_to(root).parts
        except ValueError:
            continue
        if any(_should_skip_dir(part) for part in relative_parts[:-1]):
            continue
        if not _is_text_file(path):
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield path


def build_chunks(workspace: Path) -> list[IndexChunk]:
    root = workspace.resolve()
    chunks: list[IndexChunk] = []
    for path in iter_workspace_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        relative = path.relative_to(root).as_posix()
        for start, piece in _chunk_text(text):
            chunks.append(
                IndexChunk(
                    id=_chunk_id(relative, start, piece),
                    path=relative,
                    start=start,
                    text=piece,
                )
            )
    return chunks


def _bag_of_words_embedding(text: str, *, dim: int = 64) -> list[float]:
    vector = [0.0] * dim
    for token in re.findall(r"[\w-]+", text.lower()):
        vector[hash(token) % dim] += 1.0
    norm = sum(value * value for value in vector) ** 0.5
    if norm:
        return [value / norm for value in vector]
    return vector


def _query_embedding(query: str, *, dim: int = 64) -> list[float]:
    return _bag_of_words_embedding(query, dim=dim)


async def index_workspace(
    workspace: Path,
    store: VectorStore | None = None,
    *,
    index_path: Path | None = None,
) -> IndexReport:
    """Walk text files, chunk, and upsert into ``store`` or `.zhixiao/index.jsonl`."""
    root = workspace.resolve()
    chunks = build_chunks(root)
    files = {chunk.path for chunk in chunks}

    if store is not None:
        records = [
            VectorRecord(
                id=chunk.id,
                embedding=_bag_of_words_embedding(chunk.text),
                document=chunk.text,
                metadata={"path": chunk.path, "start": chunk.start},
            )
            for chunk in chunks
        ]
        if records:
            await store.upsert(records)
        return IndexReport(files=len(files), chunks=len(chunks), index_path=None)

    target = (root / DEFAULT_INDEX_RELATIVE) if index_path is None else index_path
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk.as_record(), ensure_ascii=False) + "\n")
    return IndexReport(files=len(files), chunks=len(chunks), index_path=str(target))


def _score_chunk(text: str, terms: set[str]) -> int:
    haystack = text.lower()
    return sum(haystack.count(term) for term in terms)


def _search_jsonl(index_file: Path, query: str, limit: int) -> list[IndexHit]:
    terms = {term.lower() for term in re.findall(r"[\w-]+", query)}
    if not terms:
        return []
    ranked: list[tuple[int, IndexHit]] = []
    with index_file.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            text = str(item.get("text", ""))
            score = _score_chunk(text, terms)
            if not score:
                continue
            ranked.append(
                (
                    score,
                    IndexHit(
                        path=str(item.get("path", "")),
                        score=float(score),
                        text=text,
                        chunk_id=str(item.get("id", "")),
                        start=int(item.get("start", 0) or 0),
                    ),
                )
            )
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [hit for _, hit in ranked[:limit]]


async def search_workspace(
    workspace: Path,
    query: str,
    *,
    limit: int = 8,
    store: VectorStore | None = None,
    index_path: Path | None = None,
) -> list[IndexHit]:
    """Search an existing workspace index; empty list when no index is present."""
    if limit < 1:
        raise ValueError("limit must be positive")
    root = workspace.resolve()

    if store is not None:
        hits = await store.search(_query_embedding(query), limit=limit)
        return [
            IndexHit(
                path=str(hit.record.metadata.get("path", "")),
                score=float(hit.score),
                text=hit.record.document,
                chunk_id=hit.record.id,
                start=int(hit.record.metadata.get("start", 0) or 0),
            )
            for hit in hits
        ]

    target = (root / DEFAULT_INDEX_RELATIVE) if index_path is None else index_path
    if not target.is_file():
        return []
    return _search_jsonl(target, query, limit)


def index_exists(workspace: Path, *, index_path: Path | None = None) -> bool:
    target = (workspace.resolve() / DEFAULT_INDEX_RELATIVE) if index_path is None else index_path
    return target.is_file()


__all__ = [
    "DEFAULT_INDEX_RELATIVE",
    "IndexChunk",
    "IndexHit",
    "IndexReport",
    "InMemoryVectorStore",
    "build_chunks",
    "index_exists",
    "index_workspace",
    "iter_workspace_files",
    "search_workspace",
]
