from __future__ import annotations

import asyncio
import math
import statistics
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Literal, cast


class VectorStoreDependencyError(RuntimeError):
    """Raised when an optional vector backend is selected but not installed."""


@dataclass(frozen=True, slots=True)
class VectorRecord:
    id: str
    embedding: list[float]
    document: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("VectorRecord.id must not be empty")
        if not self.embedding:
            raise ValueError("VectorRecord.embedding must not be empty")
        if not all(math.isfinite(value) for value in self.embedding):
            raise ValueError("VectorRecord.embedding must contain finite values")


@dataclass(frozen=True, slots=True)
class VectorHit:
    record: VectorRecord
    score: float


class VectorStore(ABC):
    """Async backend-neutral contract used by retrieval and migration services."""

    @abstractmethod
    async def upsert(self, records: Sequence[VectorRecord]) -> None: ...

    @abstractmethod
    async def search(
        self,
        embedding: Sequence[float],
        *,
        limit: int = 10,
        where: dict[str, Any] | None = None,
    ) -> list[VectorHit]: ...

    @abstractmethod
    async def get(self, ids: Sequence[str]) -> list[VectorRecord]: ...

    @abstractmethod
    async def delete(self, ids: Sequence[str]) -> None: ...

    @abstractmethod
    async def count(self) -> int: ...

    @abstractmethod
    def iter_batches(self, *, batch_size: int = 1_000) -> AsyncIterator[list[VectorRecord]]: ...


@dataclass(frozen=True, slots=True)
class VectorStoreSettings:
    mode: Literal["chroma", "milvus", "dual"] = "chroma"
    collection: str = "zhixiao_knowledge"
    dimension: int = 1_024
    chroma_host: str = "localhost"
    chroma_port: int = 8000
    milvus_uri: str = "http://localhost:19530"
    milvus_token: str | None = None
    dual_read_from: Literal["primary", "secondary"] = "primary"


def _matches(metadata: dict[str, Any], where: dict[str, Any] | None) -> bool:
    return where is None or all(metadata.get(key) == value for key, value in where.items())


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        return -1.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


class InMemoryVectorStore(VectorStore):
    """Deterministic fake suitable for tests and local dependency-free runs."""

    def __init__(self) -> None:
        self._records: dict[str, VectorRecord] = {}
        self._lock = asyncio.Lock()

    async def upsert(self, records: Sequence[VectorRecord]) -> None:
        dimensions = {len(record.embedding) for record in records}
        if len(dimensions) > 1:
            raise ValueError("All embeddings in a batch must have the same dimension")
        async with self._lock:
            known_dimensions = {len(record.embedding) for record in self._records.values()}
            if known_dimensions and dimensions and dimensions != known_dimensions:
                raise ValueError("Embedding dimension does not match the collection")
            self._records.update((record.id, record) for record in records)

    async def search(
        self,
        embedding: Sequence[float],
        *,
        limit: int = 10,
        where: dict[str, Any] | None = None,
    ) -> list[VectorHit]:
        if limit < 1:
            raise ValueError("limit must be positive")
        hits = [
            VectorHit(record, _cosine(embedding, record.embedding))
            for record in self._records.values()
            if _matches(record.metadata, where)
        ]
        return sorted(hits, key=lambda item: (-item.score, item.record.id))[:limit]

    async def get(self, ids: Sequence[str]) -> list[VectorRecord]:
        return [self._records[record_id] for record_id in ids if record_id in self._records]

    async def delete(self, ids: Sequence[str]) -> None:
        async with self._lock:
            for record_id in ids:
                self._records.pop(record_id, None)

    async def count(self) -> int:
        return len(self._records)

    async def iter_batches(self, *, batch_size: int = 1_000) -> AsyncIterator[list[VectorRecord]]:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        records = sorted(self._records.values(), key=lambda item: item.id)
        for offset in range(0, len(records), batch_size):
            yield records[offset : offset + batch_size]


class ChromaVectorStore(VectorStore):
    """Chroma adapter. Import and network access happen only when instantiated."""

    def __init__(
        self,
        collection: str,
        *,
        host: str = "localhost",
        port: int = 8000,
        client: Any | None = None,
        force_import: bool = False,
    ) -> None:
        del force_import
        if client is None:
            try:
                import chromadb
            except ImportError as exc:
                raise VectorStoreDependencyError(
                    "Chroma backend requires optional dependency 'chromadb'; "
                    "install zhixiao-agent[rag]."
                ) from exc
            client = chromadb.HttpClient(host=host, port=port)
        self._collection = client.get_or_create_collection(name=collection)

    async def upsert(self, records: Sequence[VectorRecord]) -> None:
        if not records:
            return
        await asyncio.to_thread(
            lambda: self._collection.upsert(
                ids=[record.id for record in records],
                embeddings=cast(Any, [record.embedding for record in records]),
                documents=[record.document for record in records],
                metadatas=[record.metadata for record in records],
            )
        )

    async def search(
        self,
        embedding: Sequence[float],
        *,
        limit: int = 10,
        where: dict[str, Any] | None = None,
    ) -> list[VectorHit]:
        kwargs: dict[str, Any] = {
            "query_embeddings": [list(embedding)],
            "n_results": limit,
            "include": ["embeddings", "documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where
        result = await asyncio.to_thread(lambda: self._collection.query(**kwargs))
        ids = _first_result(result.get("ids"))
        embeddings = _first_result(result.get("embeddings"))
        documents = _first_result(result.get("documents"))
        metadatas = _first_result(result.get("metadatas"))
        distances = _first_result(result.get("distances"))
        return [
            VectorHit(
                VectorRecord(record_id, list(vector), document or "", metadata or {}),
                1.0 - float(distance),
            )
            for record_id, vector, document, metadata, distance in zip(
                ids, embeddings, documents, metadatas, distances, strict=True
            )
        ]

    async def get(self, ids: Sequence[str]) -> list[VectorRecord]:
        if not ids:
            return []
        result = await asyncio.to_thread(
            lambda: self._collection.get(
                ids=list(ids), include=["embeddings", "documents", "metadatas"]
            )
        )
        return _records_from_columnar(cast(dict[str, Any], result))

    async def delete(self, ids: Sequence[str]) -> None:
        if ids:
            await asyncio.to_thread(self._collection.delete, ids=list(ids))

    async def count(self) -> int:
        return int(await asyncio.to_thread(self._collection.count))

    async def iter_batches(self, *, batch_size: int = 1_000) -> AsyncIterator[list[VectorRecord]]:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        offset = 0
        while True:
            get_batch = partial(
                self._collection.get,
                limit=batch_size,
                offset=offset,
                include=["embeddings", "documents", "metadatas"],
            )
            result = await asyncio.to_thread(get_batch)
            batch = _records_from_columnar(cast(dict[str, Any], result))
            if not batch:
                return
            yield batch
            offset += len(batch)


def _records_from_columnar(result: dict[str, Any]) -> list[VectorRecord]:
    ids = result.get("ids")
    embeddings = result.get("embeddings")
    documents = result.get("documents")
    metadatas = result.get("metadatas")
    return [
        VectorRecord(record_id, list(vector), document or "", metadata or {})
        for record_id, vector, document, metadata in zip(
            [] if ids is None else ids,
            [] if embeddings is None else embeddings,
            [] if documents is None else documents,
            [] if metadatas is None else metadatas,
            strict=True,
        )
    ]


def _first_result(value: Any) -> list[Any]:
    if value is None or len(value) == 0:
        return []
    return list(value[0])


class MilvusVectorStore(VectorStore):
    """Milvus adapter based on the pymilvus high-level client."""

    def __init__(
        self,
        uri: str,
        collection: str,
        dimension: int,
        *,
        token: str | None = None,
        client: Any | None = None,
        force_import: bool = False,
    ) -> None:
        del force_import
        if dimension < 1:
            raise ValueError("dimension must be positive")
        if client is None:
            try:
                from pymilvus import MilvusClient
            except ImportError as exc:
                raise VectorStoreDependencyError(
                    "Milvus backend requires optional dependency 'pymilvus'; "
                    "install zhixiao-agent[rag]."
                ) from exc
            client = MilvusClient(uri=uri, token=token)
        self._client = client
        self._collection = collection
        self._dimension = dimension
        if not client.has_collection(collection_name=collection):
            client.create_collection(
                collection_name=collection,
                dimension=dimension,
                metric_type="COSINE",
                id_type="string",
                max_length=512,
            )

    async def upsert(self, records: Sequence[VectorRecord]) -> None:
        for record in records:
            if len(record.embedding) != self._dimension:
                raise ValueError(f"Expected embedding dimension {self._dimension}")
        if records:
            await asyncio.to_thread(
                self._client.upsert,
                collection_name=self._collection,
                data=[
                    {
                        "id": record.id,
                        "vector": record.embedding,
                        "document": record.document,
                        "metadata": record.metadata,
                    }
                    for record in records
                ],
            )

    async def search(
        self,
        embedding: Sequence[float],
        *,
        limit: int = 10,
        where: dict[str, Any] | None = None,
    ) -> list[VectorHit]:
        if len(embedding) != self._dimension:
            raise ValueError(f"Expected embedding dimension {self._dimension}")
        filter_expression = " and ".join(
            f"metadata['{key}'] == {value!r}" for key, value in (where or {}).items()
        )
        result = await asyncio.to_thread(
            self._client.search,
            collection_name=self._collection,
            data=[list(embedding)],
            limit=limit,
            filter=filter_expression,
            output_fields=["id", "vector", "document", "metadata"],
        )
        hits = result[0] if result else []
        return [
            VectorHit(
                VectorRecord(
                    str(item.get("id") or item["entity"]["id"]),
                    list(item["entity"].get("vector", [])),
                    str(item["entity"].get("document", "")),
                    dict(item["entity"].get("metadata", {})),
                ),
                float(item.get("distance", 0.0)),
            )
            for item in hits
        ]

    async def get(self, ids: Sequence[str]) -> list[VectorRecord]:
        if not ids:
            return []
        rows = await asyncio.to_thread(
            self._client.get,
            collection_name=self._collection,
            ids=list(ids),
            output_fields=["id", "vector", "document", "metadata"],
        )
        return [_record_from_row(row) for row in rows]

    async def delete(self, ids: Sequence[str]) -> None:
        if ids:
            await asyncio.to_thread(
                self._client.delete, collection_name=self._collection, ids=list(ids)
            )

    async def count(self) -> int:
        stats = await asyncio.to_thread(
            self._client.get_collection_stats, collection_name=self._collection
        )
        return int(stats.get("row_count", 0))

    async def iter_batches(self, *, batch_size: int = 1_000) -> AsyncIterator[list[VectorRecord]]:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        iterator = await asyncio.to_thread(
            self._client.query_iterator,
            collection_name=self._collection,
            batch_size=batch_size,
            filter="id != ''",
            output_fields=["id", "vector", "document", "metadata"],
        )
        try:
            while True:
                rows = await asyncio.to_thread(iterator.next)
                if not rows:
                    return
                yield [_record_from_row(row) for row in rows]
        finally:
            await asyncio.to_thread(iterator.close)


def _record_from_row(row: dict[str, Any]) -> VectorRecord:
    return VectorRecord(
        id=str(row["id"]),
        embedding=list(row.get("vector", [])),
        document=str(row.get("document", "")),
        metadata=dict(row.get("metadata", {})),
    )


@dataclass(frozen=True, slots=True)
class DualWriteReport:
    primary_succeeded: bool
    secondary_succeeded: bool
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def degraded(self) -> bool:
        return not (self.primary_succeeded and self.secondary_succeeded)


class DualWriteVectorStore(VectorStore):
    """Writes to both stores and reads from the preferred store with fallback."""

    def __init__(
        self,
        primary: VectorStore,
        secondary: VectorStore,
        *,
        read_from: Literal["primary", "secondary"] = "primary",
    ) -> None:
        self.primary = primary
        self.secondary = secondary
        self.read_from = read_from

    async def upsert_with_report(self, records: Sequence[VectorRecord]) -> DualWriteReport:
        results = await asyncio.gather(
            self.primary.upsert(records), self.secondary.upsert(records), return_exceptions=True
        )
        errors = {
            name: str(result)
            for name, result in zip(("primary", "secondary"), results, strict=True)
            if isinstance(result, BaseException)
        }
        return DualWriteReport(
            primary_succeeded="primary" not in errors,
            secondary_succeeded="secondary" not in errors,
            errors=errors,
        )

    async def upsert(self, records: Sequence[VectorRecord]) -> None:
        report = await self.upsert_with_report(records)
        if not report.primary_succeeded and not report.secondary_succeeded:
            raise RuntimeError(f"Both vector writes failed: {report.errors}")

    def _read_order(self) -> tuple[VectorStore, VectorStore]:
        if self.read_from == "primary":
            return self.primary, self.secondary
        return self.secondary, self.primary

    async def search(
        self,
        embedding: Sequence[float],
        *,
        limit: int = 10,
        where: dict[str, Any] | None = None,
    ) -> list[VectorHit]:
        preferred, fallback = self._read_order()
        try:
            return await preferred.search(embedding, limit=limit, where=where)
        except Exception:
            return await fallback.search(embedding, limit=limit, where=where)

    async def get(self, ids: Sequence[str]) -> list[VectorRecord]:
        preferred, fallback = self._read_order()
        try:
            return await preferred.get(ids)
        except Exception:
            return await fallback.get(ids)

    async def delete(self, ids: Sequence[str]) -> None:
        results = await asyncio.gather(
            self.primary.delete(ids), self.secondary.delete(ids), return_exceptions=True
        )
        if all(isinstance(result, BaseException) for result in results):
            raise RuntimeError("Delete failed in both vector stores")

    async def count(self) -> int:
        preferred, fallback = self._read_order()
        try:
            return await preferred.count()
        except Exception:
            return await fallback.count()

    async def iter_batches(self, *, batch_size: int = 1_000) -> AsyncIterator[list[VectorRecord]]:
        preferred, _ = self._read_order()
        async for batch in preferred.iter_batches(batch_size=batch_size):
            yield batch


@dataclass(frozen=True, slots=True)
class MigrationReport:
    scanned: int
    migrated_ids: tuple[str, ...]
    failed: dict[str, str]

    @property
    def migrated(self) -> int:
        return len(self.migrated_ids)


@dataclass(frozen=True, slots=True)
class ValidationReport:
    source_count: int
    target_count: int
    missing_in_target: tuple[str, ...]
    extra_in_target: tuple[str, ...]
    mismatched: tuple[str, ...]

    @property
    def consistent(self) -> bool:
        return not (self.missing_in_target or self.extra_in_target or self.mismatched)


@dataclass(frozen=True, slots=True)
class RollbackReport:
    deleted: int


async def migrate_vectors(
    source: VectorStore, target: VectorStore, *, batch_size: int = 1_000
) -> MigrationReport:
    migrated: list[str] = []
    failed: dict[str, str] = {}
    scanned = 0
    async for batch in source.iter_batches(batch_size=batch_size):
        scanned += len(batch)
        try:
            await target.upsert(batch)
        except Exception as batch_error:
            for record in batch:
                try:
                    await target.upsert([record])
                except Exception as record_error:
                    failed[record.id] = str(record_error)
                else:
                    migrated.append(record.id)
            if not batch:
                failed[f"batch-{scanned}"] = str(batch_error)
        else:
            migrated.extend(record.id for record in batch)
    return MigrationReport(scanned, tuple(migrated), failed)


async def _all_records(store: VectorStore, batch_size: int) -> dict[str, VectorRecord]:
    records: dict[str, VectorRecord] = {}
    async for batch in store.iter_batches(batch_size=batch_size):
        records.update((record.id, record) for record in batch)
    return records


async def validate_stores(
    source: VectorStore, target: VectorStore, *, batch_size: int = 1_000
) -> ValidationReport:
    source_records, target_records = await asyncio.gather(
        _all_records(source, batch_size), _all_records(target, batch_size)
    )
    source_ids = set(source_records)
    target_ids = set(target_records)
    shared = source_ids & target_ids
    mismatched = tuple(
        sorted(
            record_id
            for record_id in shared
            if source_records[record_id] != target_records[record_id]
        )
    )
    return ValidationReport(
        source_count=len(source_records),
        target_count=len(target_records),
        missing_in_target=tuple(sorted(source_ids - target_ids)),
        extra_in_target=tuple(sorted(target_ids - source_ids)),
        mismatched=mismatched,
    )


async def rollback_vectors(target: VectorStore, migrated_ids: Sequence[str]) -> RollbackReport:
    unique_ids = tuple(dict.fromkeys(migrated_ids))
    existing = await target.get(unique_ids)
    await target.delete([record.id for record in existing])
    return RollbackReport(deleted=len(existing))


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    record_count: int
    query_count: int
    insert_records_per_second: float
    p50_query_ms: float
    p95_query_ms: float


async def benchmark_store(
    store: VectorStore,
    records: Sequence[VectorRecord],
    *,
    query_vectors: Sequence[Sequence[float]],
    iterations: int = 10,
    limit: int = 10,
) -> BenchmarkResult:
    if iterations < 1:
        raise ValueError("iterations must be positive")
    started = time.perf_counter()
    await store.upsert(records)
    insert_seconds = max(time.perf_counter() - started, 1e-9)
    latencies: list[float] = []
    for _ in range(iterations):
        for vector in query_vectors:
            query_started = time.perf_counter()
            await store.search(vector, limit=limit)
            latencies.append((time.perf_counter() - query_started) * 1_000)
    sorted_latencies = sorted(latencies)
    p50 = statistics.median(sorted_latencies) if sorted_latencies else 0.0
    p95_index = max(0, math.ceil(len(sorted_latencies) * 0.95) - 1)
    p95 = sorted_latencies[p95_index] if sorted_latencies else 0.0
    return BenchmarkResult(
        record_count=len(records),
        query_count=len(latencies),
        insert_records_per_second=len(records) / insert_seconds,
        p50_query_ms=p50,
        p95_query_ms=p95,
    )


def build_vector_store(
    settings: VectorStoreSettings,
    *,
    chroma_client: Any | None = None,
    milvus_client: Any | None = None,
) -> VectorStore:
    """Create the configured backend without importing unused optional drivers."""

    def chroma() -> ChromaVectorStore:
        return ChromaVectorStore(
            settings.collection,
            host=settings.chroma_host,
            port=settings.chroma_port,
            client=chroma_client,
        )

    def milvus() -> MilvusVectorStore:
        return MilvusVectorStore(
            settings.milvus_uri,
            settings.collection,
            settings.dimension,
            token=settings.milvus_token,
            client=milvus_client,
        )

    if settings.mode == "chroma":
        return chroma()
    if settings.mode == "milvus":
        return milvus()
    if settings.mode == "dual":
        return DualWriteVectorStore(milvus(), chroma(), read_from=settings.dual_read_from)
    raise ValueError(f"Unsupported vector mode: {settings.mode}")


# Compatibility aliases retained from the original GOAL-06 specification.
ChromaStore = ChromaVectorStore
MilvusStore = MilvusVectorStore
