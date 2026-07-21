from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .graph import GraphStore, extract_query_entities
from .vector import VectorRecord, VectorStore

KeywordSearch = Callable[[str, int], Awaitable[dict[str, float]]]


@dataclass(frozen=True, slots=True)
class RetrievalEvidence:
    channel: str
    source_id: str
    score: float
    detail: str


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    record: VectorRecord
    score: float
    evidence: tuple[RetrievalEvidence, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class FusionWeights:
    semantic: float = 0.4
    graph: float = 0.2
    keyword: float = 0.2
    quality: float = 0.1
    recency: float = 0.1

    def __post_init__(self) -> None:
        values = (self.semantic, self.graph, self.keyword, self.quality, self.recency)
        if any(value < 0 for value in values) or not math.isclose(sum(values), 1.0):
            raise ValueError("Fusion weights must be non-negative and sum to 1")


class HybridRetriever:
    """Fuses semantic, keyword, and graph channels with source-backed evidence."""

    def __init__(
        self,
        vectors: VectorStore,
        graph: GraphStore,
        keyword_search: KeywordSearch,
        *,
        weights: FusionWeights | None = None,
    ) -> None:
        self._vectors = vectors
        self._graph = graph
        self._keyword_search = keyword_search
        self._weights = weights or FusionWeights()

    async def retrieve(
        self,
        query: str,
        embedding: Sequence[float],
        *,
        entities: Sequence[str] | None = None,
        limit: int = 10,
        candidate_limit: int = 20,
    ) -> list[RetrievalResult]:
        import asyncio

        graph_entities = list(entities) if entities is not None else extract_query_entities(query)
        vector_task = self._vectors.search(embedding, limit=candidate_limit)
        keyword_task = self._keyword_search(query, candidate_limit)
        graph_task = self._graph.neighbors(graph_entities, max_hops=2, limit=candidate_limit)
        vector_hits, keyword_hits, graph_hits = await asyncio.gather(
            vector_task, keyword_task, graph_task
        )

        records = {hit.record.id: hit.record for hit in vector_hits}
        missing_ids = (set(keyword_hits) | {hit.source_id for hit in graph_hits}) - set(records)
        if missing_ids:
            records.update(
                (record.id, record) for record in await self._vectors.get(sorted(missing_ids))
            )

        scores: dict[str, float] = defaultdict(float)
        evidence: dict[str, list[RetrievalEvidence]] = defaultdict(list)
        for hit in vector_hits:
            score = max(0.0, min(1.0, (hit.score + 1.0) / 2.0))
            scores[hit.record.id] += self._weights.semantic * score
            evidence[hit.record.id].append(
                RetrievalEvidence("vector", hit.record.id, score, "cosine similarity")
            )
        for source_id, raw_score in keyword_hits.items():
            score = max(0.0, min(1.0, raw_score))
            scores[source_id] += self._weights.keyword * score
            evidence[source_id].append(
                RetrievalEvidence("keyword", source_id, score, f"keyword match: {query}")
            )
        best_graph_scores: dict[str, float] = {}
        for item in graph_hits:
            score = 1.0 / item.hops
            best_graph_scores[item.source_id] = max(
                best_graph_scores.get(item.source_id, 0.0), score
            )
            evidence[item.source_id].append(
                RetrievalEvidence("graph", item.source_id, score, " -> ".join(item.chain))
            )
        for source_id, score in best_graph_scores.items():
            scores[source_id] += self._weights.graph * score

        for source_id, record in records.items():
            quality = _bounded_float(record.metadata.get("quality", 0.5), default=0.5)
            recency = _recency_score(record.metadata.get("created_at"))
            scores[source_id] += self._weights.quality * quality
            scores[source_id] += self._weights.recency * recency

        results = [
            RetrievalResult(record, scores[source_id], tuple(evidence[source_id]))
            for source_id, record in records.items()
        ]
        return sorted(results, key=lambda item: (-item.score, item.record.id))[:limit]


def _bounded_float(value: Any, *, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _recency_score(value: Any) -> float:
    if not value:
        return 0.5
    try:
        created_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return 0.5
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    age_days = max(0.0, (datetime.now(UTC) - created_at).total_seconds() / 86_400)
    return math.exp(-age_days / 180.0)
