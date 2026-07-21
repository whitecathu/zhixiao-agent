from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .types import PermissionMode


class WorkspaceViolation(ValueError):
    """Raised when a tool attempts to escape the configured workspace."""


class PermissionDenied(PermissionError):
    """Raised when a requested action exceeds the permission mode."""


@dataclass(frozen=True)
class WorkspaceBoundary:
    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.resolve(strict=True))

    def resolve(self, path: str | Path, *, must_exist: bool = False) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve(strict=must_exist)
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceViolation(f"path escapes workspace: {path}") from exc
        return resolved


_SHELL_META = re.compile(r"[;&|><`]|\$\(")
_DESTRUCTIVE = re.compile(
    r"(?:^|\s)(?:rm\s+-rf|del\s+/[sqf]|rmdir\s+/s|format\s+|mkfs\b|git\s+reset\s+--hard|git\s+clean\s+-[a-z]*f)",
    re.IGNORECASE,
)
_PUBLISH = re.compile(
    r"(?:^|\s)(?:git\s+push|gh\s+pr\s+create|gh\s+release\s+create)(?:\s|$)", re.IGNORECASE
)


class CommandPolicy:
    def validate(self, command: str, permission: PermissionMode, *, approved: bool = False) -> None:
        if permission not in {PermissionMode.EXECUTE, PermissionMode.FULL}:
            raise PermissionDenied("command execution requires execute or full permission")
        if _SHELL_META.search(command):
            raise PermissionDenied(
                "shell metacharacters are not allowed; execute one command at a time"
            )
        if _DESTRUCTIVE.search(command) and not approved:
            raise PermissionDenied("destructive command requires explicit approval")
        if _PUBLISH.search(command) and not approved:
            raise PermissionDenied("Git publication requires explicit approval")


def require_write(permission: PermissionMode) -> None:
    if permission not in {PermissionMode.EDIT, PermissionMode.FULL}:
        raise PermissionDenied("file modification requires edit or full permission")
