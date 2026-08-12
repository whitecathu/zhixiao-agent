from zhixiao_agent.routing import classify_task, route_task, with_experimental_tools
from zhixiao_agent.types import TaskType


def test_routes_bugfix_to_full_engineering_team() -> None:
    task_type = classify_task("修复登录接口报错并补充测试")
    route = route_task(task_type)

    assert task_type is TaskType.BUGFIX
    assert route.agents == ("planner", "explorer", "implementer", "tester", "reviewer")
    assert "run_tests" in route.tools


def test_unknown_request_defaults_to_explore() -> None:
    assert classify_task("understand this repository") is TaskType.EXPLORE


def test_with_experimental_tools_requires_scoped_capabilities() -> None:
    route = route_task(TaskType.EXPLORE)
    denied = with_experimental_tools(
        route.tools,
        ops_capabilities=frozenset(),
        include_mcp=True,
        include_sub_agent=True,
    )
    assert "mcp" not in denied
    assert "sub_agent" not in denied
    extended = with_experimental_tools(
        route.tools,
        ops_capabilities=frozenset({"mcp", "sub_agent"}),
        include_mcp=True,
        include_sub_agent=True,
    )
    assert "mcp" in extended
    assert "sub_agent" in extended
    assert route.tools <= extended
