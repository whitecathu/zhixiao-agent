"""Validated, versioned workflow DSL used by the runtime control plane."""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, model_validator


class WorkflowNode(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    role: Literal["planner", "explorer", "implementer", "tester", "reviewer", "knowledge"]
    tool_allowlist: list[str] = Field(default_factory=list, max_length=32)
    retry_limit: int = Field(
        default=0,
        ge=0,
        le=5,
        validation_alias=AliasChoices("retry_limit", "retries"),
    )
    approval_required: bool = False


class WorkflowEdge(BaseModel):
    source: str
    target: str
    condition: Literal["always", "success", "failure"] = "always"


class WorkflowDefinition(BaseModel):
    schema_version: Literal[1] = 1
    entrypoint: str | None = None
    nodes: list[WorkflowNode] = Field(min_length=1, max_length=64)
    edges: list[WorkflowEdge] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def validate_graph(self) -> WorkflowDefinition:
        ids = [node.id for node in self.nodes]
        known = set(ids)
        if len(ids) != len(known):
            raise ValueError("workflow node ids must be unique")
        self.entrypoint = self.entrypoint or ids[0]
        if self.entrypoint not in known:
            raise ValueError("workflow entrypoint must reference a node")
        outgoing: dict[str, list[WorkflowEdge]] = {node_id: [] for node_id in ids}
        incoming = {node_id: 0 for node_id in ids}
        for edge in self.edges:
            if edge.source not in known or edge.target not in known:
                raise ValueError("workflow edge references an unknown node")
            if edge.source == edge.target:
                raise ValueError("workflow self-cycles are not allowed")
            outgoing[edge.source].append(edge)
            incoming[edge.target] += 1
        for edges in outgoing.values():
            conditions = [edge.condition for edge in edges]
            if len(set(conditions)) != len(conditions):
                raise ValueError("workflow conditions must be deterministic")
            if "always" in conditions and len(conditions) > 1:
                raise ValueError("always cannot be combined with conditional edges")
        pending = [node_id for node_id, count in incoming.items() if count == 0]
        visited: set[str] = set()
        while pending:
            current = pending.pop()
            visited.add(current)
            for edge in outgoing[current]:
                incoming[edge.target] -= 1
                if incoming[edge.target] == 0:
                    pending.append(edge.target)
        if visited != known:
            raise ValueError("workflow cycles are not allowed")
        reachable = {self.entrypoint}
        pending = [self.entrypoint]
        while pending:
            current = pending.pop()
            for edge in outgoing[current]:
                if edge.target not in reachable:
                    reachable.add(edge.target)
                    pending.append(edge.target)
        if reachable != known:
            raise ValueError("all workflow nodes must be reachable from the entrypoint")
        return self

    def outgoing(self, node_id: str) -> list[WorkflowEdge]:
        return [edge for edge in self.edges if edge.source == node_id]

    def next_node(self, node_id: str, *, failed: bool) -> str | None:
        edges = self.outgoing(node_id)
        wanted = "failure" if failed else "success"
        for edge in edges:
            if edge.condition == wanted:
                return edge.target
        for edge in edges:
            if edge.condition == "always":
                return edge.target
        return None
