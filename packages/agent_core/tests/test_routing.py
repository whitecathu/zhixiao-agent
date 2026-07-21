from zhixiao_agent.routing import classify_task, route_task
from zhixiao_agent.types import TaskType


def test_routes_bugfix_to_full_engineering_team() -> None:
    task_type = classify_task("修复登录接口报错并补充测试")
    route = route_task(task_type)

    assert task_type is TaskType.BUGFIX
    assert route.agents == ("planner", "explorer", "implementer", "tester", "reviewer")
    assert "run_tests" in route.tools


def test_unknown_request_defaults_to_explore() -> None:
    assert classify_task("understand this repository") is TaskType.EXPLORE
