from __future__ import annotations

import sys

import pytest

from zhixiao_agent.rag import (
    ChromaVectorStore,
    DualWriteVectorStore,
    InMemoryVectorStore,
    MilvusVectorStore,
    VectorRecord,
    benchmark_store,
    migrate_vectors,
    rollback_vectors,
    validate_stores,
)


def record(record_id: str, value: float) -> VectorRecord:
    return VectorRecord(
        id=record_id,
        embedding=[value, 1.0 - value],
        document=f"document {record_id}",
        metadata={"space": "demo"},
    )


@pytest.mark.asyncio
async def test_in_memory_vector_store_filters_and_orders_by_similarity() -> None:
    store = InMemoryVectorStore()
    await store.upsert([record("a", 1.0), record("b", 0.0)])

    hits = await store.search([1.0, 0.0], limit=1, where={"space": "demo"})

    assert [hit.record.id for hit in hits] == ["a"]
    assert hits[0].score == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_dual_write_falls_back_to_secondary_read_and_reports_degraded_write() -> None:
    class FailingStore(InMemoryVectorStore):
        async def upsert(self, records: list[VectorRecord]) -> None:
            raise RuntimeError("primary unavailable")

        async def search(self, embedding, *, limit=10, where=None):
            raise RuntimeError("primary unavailable")

    secondary = InMemoryVectorStore()
    store = DualWriteVectorStore(FailingStore(), secondary, read_from="primary")

    report = await store.upsert_with_report([record("a", 1.0)])
    hits = await store.search([1.0, 0.0])

    assert report.degraded is True
    assert report.secondary_succeeded is True
    assert [hit.record.id for hit in hits] == ["a"]


@pytest.mark.asyncio
async def test_migration_validate_and_rollback_are_resumable() -> None:
    source = InMemoryVectorStore()
    target = InMemoryVectorStore()
    await source.upsert([record(str(index), index / 10) for index in range(5)])

    report = await migrate_vectors(source, target, batch_size=2)
    validation = await validate_stores(source, target)
    rollback = await rollback_vectors(target, report.migrated_ids[:2])

    assert report.scanned == 5
    assert report.migrated == 5
    assert report.failed == {}
    assert validation.consistent is True
    assert rollback.deleted == 2
    assert await target.count() == 3


@pytest.mark.asyncio
async def test_benchmark_reports_latency_and_throughput() -> None:
    result = await benchmark_store(
        InMemoryVectorStore(),
        [record(str(index), index / 10) for index in range(10)],
        query_vectors=[[1.0, 0.0], [0.0, 1.0]],
        iterations=2,
    )

    assert result.record_count == 10
    assert result.query_count == 4
    assert result.insert_records_per_second > 0
    assert result.p95_query_ms >= result.p50_query_ms >= 0


def test_heavy_adapters_are_importable_without_optional_dependencies(monkeypatch) -> None:
    from zhixiao_agent.rag import ChromaVectorStore, MilvusVectorStore

    monkeypatch.setitem(sys.modules, "chromadb", None)
    with pytest.raises(RuntimeError, match="chromadb"):
        ChromaVectorStore(collection="test", client=None, force_import=True)
    monkeypatch.setitem(sys.modules, "pymilvus", None)
    with pytest.raises(RuntimeError, match="pymilvus"):
        MilvusVectorStore(uri="memory://", collection="test", dimension=2, force_import=True)


@pytest.mark.asyncio
async def test_chroma_adapter_maps_backend_payloads() -> None:
    class Collection:
        def __init__(self):
            self.rows = {}

        def upsert(self, *, ids, embeddings, documents, metadatas):
            self.rows.update(
                (record_id, (embedding, document, metadata))
                for record_id, embedding, document, metadata in zip(
                    ids, embeddings, documents, metadatas, strict=True
                )
            )

        def query(self, **kwargs):
            record_id, (embedding, document, metadata) = next(iter(self.rows.items()))
            return {
                "ids": [[record_id]],
                "embeddings": [[embedding]],
                "documents": [[document]],
                "metadatas": [[metadata]],
                "distances": [[0.1]],
            }

        def get(self, *, ids=None, limit=None, offset=0, include=None):
            selected = list(self.rows) if ids is None else ids
            if limit is not None:
                selected = selected[offset : offset + limit]
            rows = [
                (record_id, self.rows[record_id])
                for record_id in selected
                if record_id in self.rows
            ]
            return {
                "ids": [row[0] for row in rows],
                "embeddings": [row[1][0] for row in rows],
                "documents": [row[1][1] for row in rows],
                "metadatas": [row[1][2] for row in rows],
            }

        def delete(self, *, ids):
            for record_id in ids:
                self.rows.pop(record_id, None)

        def count(self):
            return len(self.rows)

    collection = Collection()
    client = SimpleClient(collection)
    store = ChromaVectorStore("knowledge", client=client)
    await store.upsert([record("a", 1.0), record("b", 0.0)])

    assert (await store.search([1.0, 0.0]))[0].score == pytest.approx(0.9)
    assert [item.id for item in await store.get(["b"])] == ["b"]
    batches = [batch async for batch in store.iter_batches(batch_size=1)]
    assert len(batches) == 2
    await store.delete(["a"])
    assert await store.count() == 1


class SimpleClient:
    def __init__(self, collection):
        self.collection = collection

    def get_or_create_collection(self, *, name):
        return self.collection


@pytest.mark.asyncio
async def test_milvus_adapter_creates_collection_and_maps_payloads() -> None:
    class Iterator:
        def __init__(self, rows):
            self.rows = [rows, []]
            self.closed = False

        def next(self):
            return self.rows.pop(0)

        def close(self):
            self.closed = True

    class Client:
        def __init__(self):
            self.rows = {}
            self.created = False

        def has_collection(self, **kwargs):
            return False

        def create_collection(self, **kwargs):
            self.created = True

        def upsert(self, *, data, **kwargs):
            self.rows.update((row["id"], row) for row in data)

        def search(self, **kwargs):
            row = next(iter(self.rows.values()))
            return [[{"id": row["id"], "distance": 0.95, "entity": row}]]

        def get(self, *, ids, **kwargs):
            return [self.rows[record_id] for record_id in ids if record_id in self.rows]

        def delete(self, *, ids, **kwargs):
            for record_id in ids:
                self.rows.pop(record_id, None)

        def get_collection_stats(self, **kwargs):
            return {"row_count": len(self.rows)}

        def query_iterator(self, **kwargs):
            return Iterator(list(self.rows.values()))

    client = Client()
    store = MilvusVectorStore("memory://", "knowledge", 2, client=client)
    await store.upsert([record("a", 1.0)])

    assert client.created is True
    assert (await store.search([1.0, 0.0]))[0].score == pytest.approx(0.95)
    assert [item.id for item in await store.get(["a"])] == ["a"]
    assert len([item async for item in store.iter_batches(batch_size=5)]) == 1
    await store.delete(["a"])
    assert await store.count() == 0
