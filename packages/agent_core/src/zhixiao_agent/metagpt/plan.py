"""Plan / Task with topological ordering."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class Task(BaseModel):
    task_id: str
    dependent_task_ids: list[str] = Field(default_factory=list)
    instruction: str
    task_type: str = ""
    code: str = ""
    result: str = ""
    is_success: bool = False
    is_finished: bool = False
    assignee: str = ""

    def reset(self) -> None:
        self.code = ""
        self.result = ""
        self.is_success = False
        self.is_finished = False

    def update_task_result(self, task_result: Any) -> None:
        if hasattr(task_result, "code") and task_result.code:
            self.code = (self.code + "\n" + task_result.code).strip()
        if hasattr(task_result, "result") and task_result.result:
            self.result = (self.result + "\n" + str(task_result.result)).strip()
        if hasattr(task_result, "is_success"):
            self.is_success = bool(task_result.is_success)


class Plan(BaseModel):
    goal: str
    context: str = ""
    tasks: list[Task] = Field(default_factory=list)
    task_map: dict = Field(default_factory=dict)
    current_task_id: str = ""

    def add_tasks(self, tasks: list[Task]) -> None:
        if not tasks:
            return
        sorted_tasks = self._topological_sort(tasks)
        if not self.tasks:
            self.tasks = sorted_tasks
        else:
            prefix_length = 0
            for old_task, new_task in zip(self.tasks, sorted_tasks):
                if (
                    old_task.task_id != new_task.task_id
                    or old_task.instruction != new_task.instruction
                ):
                    break
                prefix_length += 1
            self.tasks = self.tasks[:prefix_length] + sorted_tasks[prefix_length:]
        self._update_current_task()

    @staticmethod
    def _topological_sort(tasks: list[Task]) -> list[Task]:
        task_map = {t.task_id: t for t in tasks}
        visited: set[str] = set()
        ordered: list[Task] = []

        def visit(tid: str, path: set[str]) -> None:
            if tid in visited:
                return
            if tid in path:
                raise ValueError(f"循环依赖检测: {tid}")
            path.add(tid)
            for dep in task_map.get(tid, Task(task_id="", instruction="")).dependent_task_ids:
                if dep in task_map:
                    visit(dep, path)
            path.discard(tid)
            visited.add(tid)
            ordered.append(task_map[tid])

        for t in tasks:
            visit(t.task_id, set())
        return ordered

    def _update_current_task(self) -> None:
        self.task_map = {t.task_id: t for t in self.tasks}
        current = ""
        for t in self.tasks:
            if not t.is_finished:
                current = t.task_id
                break
        self.current_task_id = current

    @property
    def current_task(self) -> Optional[Task]:
        return self.task_map.get(self.current_task_id)

    def finish_current_task(self) -> Optional[Task]:
        if self.current_task_id and self.current_task:
            self.current_task.is_finished = True
        self._update_current_task()
        return self.current_task

    def is_plan_finished(self) -> bool:
        return bool(self.tasks) and all(t.is_finished for t in self.tasks)

    def get_finished_tasks(self) -> list[Task]:
        return [t for t in self.tasks if t.is_finished]
