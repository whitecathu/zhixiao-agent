"""tests/test_plan_topology.py
MetaGPT Plan 拓扑排序单测
"""
from app.plans.task import Plan, Task


def test_topological_sort_linear():
    p = Plan(goal="g")
    p.add_tasks([
        Task(task_id="C", instruction="c", dependent_task_ids=["A", "B"]),
        Task(task_id="B", instruction="b", dependent_task_ids=["A"]),
        Task(task_id="A", instruction="a"),
    ])
    assert [t.task_id for t in p.tasks] == ["A", "B", "C"]
    assert p.current_task_id == "A"
    p.finish_current_task()
    assert p.current_task_id == "B"
    p.finish_current_task()
    assert p.current_task_id == "C"
    p.finish_current_task()
    assert p.is_plan_finished()


def test_dependency_cycle_raises():
    p = Plan(goal="g")
    try:
        p.add_tasks([
            Task(task_id="X", instruction="x", dependent_task_ids=["Y"]),
            Task(task_id="Y", instruction="y", dependent_task_ids=["X"]),
        ])
        assert False, "循环依赖应抛错"
    except ValueError:
        pass


def test_merge_keep_prefix():
    p = Plan(goal="g")
    p.add_tasks([Task(task_id="A", instruction="a")])
    p.add_tasks([
        Task(task_id="A", instruction="a"),
        Task(task_id="B", instruction="b", dependent_task_ids=["A"]),
    ])
    assert [t.task_id for t in p.tasks] == ["A", "B"]