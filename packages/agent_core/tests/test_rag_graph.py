from __future__ import annotations

import pytest

from zhixiao_agent.rag import (
    HybridRetriever,
    InMemoryGraphStore,
    InMemoryVectorStore,
    LLMTripleExtractor,
    Neo4jGraphStore,
    RuleBasedTripleExtractor,
    Triple,
    VectorRecord,
)


@pytest.mark.asyncio
async def test_rule_based_extractor_only_accepts_verifiable_delimited_lines() -> None:
    extractor = RuleBasedTripleExtractor()

    triples = await extractor.extract(
        "A公司|合作|B公司\ninvalid\nB公司 | 位于 | 上海", source_id="k1"
    )

    assert triples == [
        Triple(subject="A公司", relation="合作", object="B公司", source_id="k1"),
        Triple(subject="B公司", relation="位于", object="上海", source_id="k1"),
    ]


@pytest.mark.asyncio
async def test_graph_store_returns_source_backed_evidence_chain() -> None:
    graph = InMemoryGraphStore()
    await graph.upsert_triples(
        [
            Triple(subject="A", relation="uses", object="B", source_id="doc-1"),
            Triple(subject="B", relation="part_of", object="C", source_id="doc-2"),
        ]
    )

    evidence = await graph.neighbors(["A"], max_hops=2)

    assert [item.source_id for item in evidence] == ["doc-1", "doc-2"]
    assert evidence[1].chain == ("A", "uses", "B", "part_of", "C")


@pytest.mark.asyncio
async def test_hybrid_retriever_fuses_three_channels_and_keeps_evidence() -> None:
    vectors = InMemoryVectorStore()
    await vectors.upsert(
        [
            VectorRecord("doc-1", [1.0, 0.0], "A uses B", {"quality": 0.8}),
            VectorRecord("doc-2", [0.0, 1.0], "unrelated", {"quality": 0.5}),
        ]
    )
    graph = InMemoryGraphStore()
    await graph.upsert_triples([Triple("A", "uses", "B", "doc-1")])

    async def keywords(query: str, limit: int):
        return {"doc-1": 0.9} if "A" in query else {}

    retriever = HybridRetriever(vectors, graph, keywords)
    results = await retriever.retrieve("A dependency", [1.0, 0.0], entities=["A"])

    assert results[0].record.id == "doc-1"
    assert {e.channel for e in results[0].evidence} == {"vector", "keyword", "graph"}
    graph_evidence = next(e for e in results[0].evidence if e.channel == "graph")
    assert graph_evidence.source_id == "doc-1"
    assert "uses" in graph_evidence.detail


@pytest.mark.asyncio
async def test_llm_extractor_rejects_invalid_json_and_skips_incomplete_items() -> None:
    extractor = LLMTripleExtractor(
        lambda prompt: async_value(
            '[{"subject":"A","relation":"uses","object":"B"},{"subject":"bad"}]'
        )
    )

    assert await extractor.extract("text", source_id="doc") == [Triple("A", "uses", "B", "doc")]
    invalid = LLMTripleExtractor(lambda prompt: async_value("not-json"))
    with pytest.raises(ValueError, match="invalid JSON"):
        await invalid.extract("text", source_id="doc")


async def async_value(value):
    return value


@pytest.mark.asyncio
async def test_neo4j_adapter_uses_parameterized_queries_and_maps_evidence() -> None:
    class Cursor:
        async def data(self):
            return [
                {
                    "start_name": "A",
                    "target_name": "B",
                    "relations": ["uses"],
                    "source_ids": ["doc-1"],
                    "hops": 1,
                }
            ]

    class Session:
        def __init__(self):
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def run(self, query, **parameters):
            self.calls.append((query, parameters))
            return Cursor()

    class Driver:
        def __init__(self):
            self.sessions = []
            self.closed = False

        def session(self, **kwargs):
            session = Session()
            self.sessions.append(session)
            return session

        async def close(self):
            self.closed = True

    driver = Driver()
    store = Neo4jGraphStore("neo4j://unused", ("u", "p"), driver=driver)
    await store.ensure_schema()
    await store.upsert_triples([Triple("A", "uses", "B", "doc-1")])
    evidence = await store.neighbors(["A"], max_hops=1)
    await store.close()

    assert evidence[0].chain == ("A", "uses", "B")
    assert driver.sessions[1].calls[0][1]["rows"][0]["source_id"] == "doc-1"
    assert driver.closed is True
