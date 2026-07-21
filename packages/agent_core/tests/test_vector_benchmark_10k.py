import pytest

from zhixiao_agent.rag.vector import InMemoryVectorStore, VectorRecord, benchmark_store


@pytest.mark.asyncio
async def test_ten_thousand_record_vector_ci_benchmark() -> None:
    records = [
        VectorRecord(
            id=f"record-{index}",
            embedding=[float(index % 7), float(index % 11), 1.0],
            document=f"engineering knowledge {index}",
            metadata={"bucket": index % 10},
        )
        for index in range(10_000)
    ]
    report = await benchmark_store(
        InMemoryVectorStore(),
        records,
        query_vectors=[[1.0, 2.0, 1.0]],
        iterations=3,
    )
    assert report.record_count == 10_000
    assert report.query_count == 3
    assert report.insert_records_per_second > 0
    assert report.p95_query_ms >= report.p50_query_ms
