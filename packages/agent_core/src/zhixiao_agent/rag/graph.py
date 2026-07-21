from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any


class GraphStoreDependencyError(RuntimeError):
    """Raised when Neo4j is selected without its optional dependency."""


@dataclass(frozen=True, slots=True)
class Triple:
    subject: str
    relation: str
    object: str
    source_id: str

    def __post_init__(self) -> None:
        if not all(
            (self.subject.strip(), self.relation.strip(), self.object.strip(), self.source_id)
        ):
            raise ValueError("Triple fields must not be empty")


@dataclass(frozen=True, slots=True)
class GraphEvidence:
    source_id: str
    subject: str
    relation: str
    object: str
    hops: int
    chain: tuple[str, ...]


class EntityRelationExtractor(ABC):
    @abstractmethod
    async def extract(self, text: str, *, source_id: str) -> list[Triple]: ...


class RuleBasedTripleExtractor(EntityRelationExtractor):
    """Strict parser for pre-extracted ``subject|relation|object`` lines."""

    async def extract(self, text: str, *, source_id: str) -> list[Triple]:
        triples: list[Triple] = []
        for line in text.splitlines():
            fields = [field.strip().strip("()") for field in line.split("|")]
            if len(fields) == 3 and all(fields):
                triples.append(Triple(fields[0], fields[1], fields[2], source_id))
        return triples


class LLMTripleExtractor(EntityRelationExtractor):
    """Model-backed extractor that accepts JSON arrays and rejects malformed output."""

    def __init__(self, invoke: Callable[[str], Awaitable[str]]) -> None:
        self._invoke = invoke

    async def extract(self, text: str, *, source_id: str) -> list[Triple]:
        prompt = (
            "Extract only verifiable relationships from the text as a JSON array. "
            'Each item must have string keys "subject", "relation", and "object".\n'
            f"Text:\n{text}"
        )
        response = await self._invoke(prompt)
        try:
            raw = json.loads(response)
        except json.JSONDecodeError as exc:
            raise ValueError("Triple extractor returned invalid JSON") from exc
        if not isinstance(raw, list):
            raise ValueError("Triple extractor must return a JSON array")
        triples: list[Triple] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                triples.append(
                    Triple(
                        subject=str(item["subject"]).strip(),
                        relation=str(item["relation"]).strip(),
                        object=str(item["object"]).strip(),
                        source_id=source_id,
                    )
                )
            except (KeyError, ValueError):
                continue
        return triples


class GraphStore(ABC):
    @abstractmethod
    async def upsert_triples(self, triples: Sequence[Triple]) -> None: ...

    @abstractmethod
    async def neighbors(
        self, entities: Sequence[str], *, max_hops: int = 2, limit: int = 100
    ) -> list[GraphEvidence]: ...

    @abstractmethod
    async def close(self) -> None: ...


class InMemoryGraphStore(GraphStore):
    """Directed property graph fake preserving source provenance."""

    def __init__(self) -> None:
        self._outgoing: dict[str, list[Triple]] = defaultdict(list)

    async def upsert_triples(self, triples: Sequence[Triple]) -> None:
        for triple in triples:
            if triple not in self._outgoing[triple.subject]:
                self._outgoing[triple.subject].append(triple)

    async def neighbors(
        self, entities: Sequence[str], *, max_hops: int = 2, limit: int = 100
    ) -> list[GraphEvidence]:
        if max_hops < 1:
            raise ValueError("max_hops must be positive")
        results: list[GraphEvidence] = []
        for entity in dict.fromkeys(entities):
            queue: deque[tuple[str, int, tuple[str, ...]]] = deque([(entity, 0, (entity,))])
            best_depth: dict[str, int] = {entity: 0}
            while queue and len(results) < limit:
                current, depth, chain = queue.popleft()
                if depth >= max_hops:
                    continue
                for triple in self._outgoing.get(current, []):
                    next_depth = depth + 1
                    next_chain = (*chain, triple.relation, triple.object)
                    results.append(
                        GraphEvidence(
                            source_id=triple.source_id,
                            subject=triple.subject,
                            relation=triple.relation,
                            object=triple.object,
                            hops=next_depth,
                            chain=next_chain,
                        )
                    )
                    if next_depth < best_depth.get(triple.object, max_hops + 1):
                        best_depth[triple.object] = next_depth
                        queue.append((triple.object, next_depth, next_chain))
                    if len(results) >= limit:
                        break
        return results

    async def close(self) -> None:
        return None


class Neo4jGraphStore(GraphStore):
    """Neo4j adapter with parameterized Cypher and lazy dependency loading."""

    def __init__(
        self,
        uri: str,
        auth: tuple[str, str],
        *,
        database: str = "neo4j",
        driver: Any | None = None,
    ) -> None:
        if driver is None:
            try:
                from neo4j import AsyncGraphDatabase
            except ImportError as exc:
                raise GraphStoreDependencyError(
                    "Neo4j graph backend requires optional dependency 'neo4j'; "
                    "install zhixiao-agent[rag]."
                ) from exc
            driver = AsyncGraphDatabase.driver(uri, auth=auth)
        self._driver = driver
        self._database = database

    async def ensure_schema(self) -> None:
        query = (
            "CREATE CONSTRAINT entity_name IF NOT EXISTS FOR (n:Entity) REQUIRE n.name IS UNIQUE"
        )
        async with self._driver.session(database=self._database) as session:
            await session.run(query)

    async def upsert_triples(self, triples: Sequence[Triple]) -> None:
        if not triples:
            return
        query = """
        UNWIND $rows AS row
        MERGE (a:Entity {name: row.subject})
        MERGE (b:Entity {name: row.object})
        MERGE (a)-[r:RELATES_TO {relation: row.relation, source_id: row.source_id}]->(b)
        ON CREATE SET r.count = 1
        ON MATCH SET r.count = coalesce(r.count, 0) + 1
        """
        rows = [
            {
                "subject": triple.subject,
                "relation": triple.relation,
                "object": triple.object,
                "source_id": triple.source_id,
            }
            for triple in triples
        ]
        async with self._driver.session(database=self._database) as session:
            await session.run(query, rows=rows)

    async def neighbors(
        self, entities: Sequence[str], *, max_hops: int = 2, limit: int = 100
    ) -> list[GraphEvidence]:
        if max_hops not in (1, 2):
            raise ValueError("Neo4jGraphStore supports max_hops 1 or 2")
        hop_expression = "1" if max_hops == 1 else "1..2"
        query = f"""
        MATCH path=(start:Entity)-[rels:RELATES_TO*{hop_expression}]->(target:Entity)
        WHERE start.name IN $entities
        WITH path, rels, start, target
        ORDER BY length(path), start.name, target.name
        LIMIT $limit
        RETURN start.name AS start_name, target.name AS target_name,
               [r IN rels | r.relation] AS relations,
               [r IN rels | r.source_id] AS source_ids,
               length(path) AS hops
        """
        async with self._driver.session(database=self._database) as session:
            cursor = await session.run(query, entities=list(entities), limit=limit)
            rows = await cursor.data()
        evidence: list[GraphEvidence] = []
        for row in rows:
            relations = row["relations"]
            source_ids = row["source_ids"]
            chain: list[str] = [row["start_name"]]
            for relation in relations:
                chain.extend((relation, row["target_name"] if relation == relations[-1] else "…"))
            evidence.append(
                GraphEvidence(
                    source_id=source_ids[-1],
                    subject=row["start_name"],
                    relation=" -> ".join(relations),
                    object=row["target_name"],
                    hops=int(row["hops"]),
                    chain=tuple(chain),
                )
            )
        return evidence

    async def close(self) -> None:
        await self._driver.close()


def extract_query_entities(query: str) -> list[str]:
    """Extract conservative identifier-like entities without inventing facts."""

    latin = re.findall(r"\b[A-Z][A-Za-z0-9_.-]{1,}\b", query)
    chinese = re.findall(r"[\u4e00-\u9fff]{2,}(?:公司|项目|系统|平台)", query)
    return list(dict.fromkeys((*latin, *chinese)))
