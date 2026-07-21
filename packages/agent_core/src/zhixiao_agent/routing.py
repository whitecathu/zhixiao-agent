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
    scores = {
        task_type: sum(keyword in lowered for keyword in keywords)
        for task_type, keywords in _KEYWORDS.items()
    }
    best, score = max(scores.items(), key=lambda pair: pair[1], default=(TaskType.EXPLORE, 0))
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
    full = executing | {"web_search", "web_fetch", "sub_agent", "mcp"}
    routes = {
        TaskType.EXPLORE: Route(task_type, ("explorer", "reviewer"), readonly),
        TaskType.REVIEW: Route(task_type, ("explorer", "reviewer"), readonly),
        TaskType.DOCUMENTATION: Route(task_type, ("planner", "implementer", "reviewer"), editing),
        TaskType.TEST: Route(task_type, ("planner", "tester", "reviewer"), executing),
        TaskType.OPERATIONS: Route(
            task_type, ("planner", "implementer", "tester", "reviewer"), full
        ),
        TaskType.BUGFIX: Route(
            task_type, ("planner", "explorer", "implementer", "tester", "reviewer"), full
        ),
        TaskType.FEATURE: Route(
            task_type, ("planner", "explorer", "implementer", "tester", "reviewer"), full
        ),
        TaskType.REFACTOR: Route(
            task_type, ("planner", "explorer", "implementer", "tester", "reviewer"), full
        ),
    }
    return routes[task_type]
