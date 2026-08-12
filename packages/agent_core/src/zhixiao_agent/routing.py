from __future__ import annotations

from dataclasses import dataclass

from .types import TaskType

_KEYWORDS: dict[TaskType, tuple[str, ...]] = {
    TaskType.BUGFIX: ("bug", "fix", "error", "exception", "失败", "报错", "修复"),
    TaskType.FEATURE: ("feature", "implement", "add", "新增", "实现", "功能"),
    TaskType.REFACTOR: ("refactor", "cleanup", "重构", "优化结构"),
    TaskType.TEST: ("test", "coverage", "测试", "覆盖率"),
    TaskType.REVIEW: ("review", "audit", "审查", "评审", "安全检查"),
    TaskType.DOCUMENTATION: ("docs", "readme", "document", "文档", "说明"),
    TaskType.OPERATIONS: ("deploy", "docker", "ci", "release", "部署", "运维", "发布"),
}


@dataclass(frozen=True)
class Route:
    task_type: TaskType
    agents: tuple[str, ...]
    tools: frozenset[str]


def classify_task(prompt: str) -> TaskType:
    lowered = prompt.lower()
    scores: dict[TaskType, float] = {}
    for task_type, keywords in _KEYWORDS.items():
        score = 0.0
        for keyword in keywords:
            if " " in keyword or len(keyword) > 4:
                if keyword in lowered:
                    score += 1.5
            elif keyword in lowered:
                score += 1.0
        scores[task_type] = score
    best, score = max(scores.items(), key=lambda pair: pair[1], default=(TaskType.EXPLORE, 0.0))
    return best if score else TaskType.EXPLORE


def route_task(task_type: TaskType) -> Route:
    readonly = frozenset(
        {
            "list_directory",
            "read_file",
            "grep",
            "git_status",
            "git_diff",
            "todo",
            "knowledge_search",
        }
    )
    editing = readonly | {"exact_edit", "write_file"}
    executing = editing | {"terminal", "run_tests", "background_command"}
    # Network tools stay routable; MCP stays opt-in. sub_agent is added in runtime
    # intake for feature/bugfix/refactor only when the registry registers it.
    networked = executing | {"web_search", "web_fetch"}
    routes = {
        TaskType.EXPLORE: Route(task_type, ("explorer", "reviewer"), readonly),
        TaskType.REVIEW: Route(task_type, ("explorer", "reviewer"), readonly),
        TaskType.DOCUMENTATION: Route(task_type, ("planner", "implementer", "reviewer"), editing),
        TaskType.TEST: Route(task_type, ("planner", "tester", "reviewer"), executing),
        TaskType.OPERATIONS: Route(
            task_type, ("planner", "implementer", "tester", "reviewer"), networked
        ),
        TaskType.BUGFIX: Route(
            task_type, ("planner", "explorer", "implementer", "tester", "reviewer"), networked
        ),
        TaskType.FEATURE: Route(
            task_type, ("planner", "explorer", "implementer", "tester", "reviewer"), networked
        ),
        TaskType.REFACTOR: Route(
            task_type, ("planner", "explorer", "implementer", "tester", "reviewer"), networked
        ),
    }
    return routes[task_type]


def with_experimental_tools(
    route_tools: frozenset[str],
    *,
    ops_capabilities: frozenset[str],
    include_mcp: bool,
    include_sub_agent: bool,
) -> frozenset[str]:
    """Advertise experimental tools only when that exact operation was approved."""
    extra: set[str] = set()
    if include_mcp and "mcp" in ops_capabilities:
        extra.add("mcp")
    if include_sub_agent and "sub_agent" in ops_capabilities:
        extra.add("sub_agent")
    return frozenset(route_tools | extra)
