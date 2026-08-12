"""Configurable vector-store benchmark for CI (10k) and scale labs (1M).

Usage:
  python -m zhixiao_agent.rag.benchmark_cli --count 10000
  python -m zhixiao_agent.rag.benchmark_cli --count 1000000 --backend memory
"""
from __future__ import annotations

import argparse
import asyncio
import json

from .vector import InMemoryVectorStore, VectorRecord, benchmark_store


async def _run(count: int, iterations: int) -> dict[str, float | int]:
    records = [
        VectorRecord(
            id=f"record-{index}",
            embedding=[float(index % 7), float(index % 11), 1.0],
            document=f"engineering knowledge {index}",
            metadata={"bucket": index % 10},
        )
        for index in range(count)
    ]
    report = await benchmark_store(
        InMemoryVectorStore(),
        records,
        query_vectors=[[1.0, 2.0, 1.0]],
        iterations=iterations,
    )
    return {
        "record_count": report.record_count,
        "query_count": report.query_count,
        "insert_records_per_second": report.insert_records_per_second,
        "p50_query_ms": report.p50_query_ms,
        "p95_query_ms": report.p95_query_ms,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=10_000)
    parser.add_argument("--iterations", type=int, default=3)
    args = parser.parse_args()
    if args.count > 100_000:
        print(
            json.dumps(
                {
                    "warning": "million-scale runs need dedicated RAM/CPU; not a CI default",
                    "requested_count": args.count,
                }
            )
        )
    payload = asyncio.run(_run(args.count, args.iterations))
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
