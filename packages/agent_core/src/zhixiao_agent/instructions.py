from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .security import WorkspaceBoundary

INSTRUCTION_NAMES = ("AGENTS.md", "AGENT.md", "Agents.md", "Claude.md")


@dataclass(frozen=True)
class ProjectInstruction:
    path: Path
    scope: Path
    content: str


def discover_instructions(workspace: Path, target: Path | None = None) -> list[ProjectInstruction]:
    boundary = WorkspaceBoundary(workspace)
    resolved_target = boundary.resolve(target or workspace, must_exist=True)
    current = resolved_target if resolved_target.is_dir() else resolved_target.parent
    directories: list[Path] = []
    while True:
        directories.append(current)
        if current == boundary.root:
            break
        current = current.parent
    instructions: list[ProjectInstruction] = []
    for directory in reversed(directories):
        for name in INSTRUCTION_NAMES:
            candidate = directory / name
            if candidate.is_file():
                instructions.append(
                    ProjectInstruction(
                        path=candidate,
                        scope=directory,
                        content=candidate.read_text(encoding="utf-8"),
                    )
                )
    return instructions


def render_instructions(instructions: list[ProjectInstruction], workspace: Path) -> str:
    root = workspace.resolve()
    sections = []
    for instruction in instructions:
        sections.append(
            f"## {instruction.path.relative_to(root).as_posix()}\n"
            f"Scope: {instruction.scope.relative_to(root).as_posix() or '.'}\n\n"
            f"{instruction.content.strip()}"
        )
    return "\n\n".join(sections)
