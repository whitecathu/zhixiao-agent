"""tests/test_task_state_machine.py
任务状态机流转校验
"""
from app.model.task import Task


def test_state_machine_happy_path():
    assert Task.next_status("pending", "running") is True
    assert Task.next_status("running", "succeeded") is True
    assert Task.next_status("running", "failed") is True
    assert Task.next_status("running", "interrupted") is True


def test_state_machine_invalid_transition():
    assert Task.next_status("pending", "succeeded") is False     # 未运行不能直接终态
    assert Task.next_status("succeeded", "running") is False     # 终态不可逆
    assert Task.next_status("failed", "running") is False


def test_interrupted_can_resume():
    assert Task.next_status("interrupted", "running") is True