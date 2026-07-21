from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    instructions: str
    path: Path
    tags: tuple[str, ...] = field(default_factory=tuple)


class SkillManager:
    """Load standard SKILL.md packages and legacy config/skprompt pairs."""

    def __init__(self, roots: list[Path]):
        self.roots = roots
        self._skills: dict[str, Skill] = {}

    def load(self) -> dict[str, Skill]:
        loaded: dict[str, Skill] = {}
        for root in self.roots:
            if not root.exists():
                continue
            for directory in (path for path in root.iterdir() if path.is_dir()):
                skill = self._load_standard(directory) or self._load_legacy(directory)
                if skill:
                    loaded[skill.name] = skill
        self._skills = loaded
        return dict(loaded)

    def _load_standard(self, directory: Path) -> Skill | None:
        path = directory / "SKILL.md"
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8")
        metadata: dict[str, str] = {}
        body = text
        if text.startswith("---"):
            _, frontmatter, body = text.split("---", 2)
            for line in frontmatter.splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    metadata[key.strip()] = value.strip()
        return Skill(
            name=metadata.get("name", directory.name),
            description=metadata.get("description", ""),
            instructions=body.strip(),
            path=path,
        )

    def _load_legacy(self, directory: Path) -> Skill | None:
        config_path = directory / "config.json"
        prompt_path = directory / "skprompt.txt"
        if not config_path.is_file() or not prompt_path.is_file():
            return None
        config = json.loads(config_path.read_text(encoding="utf-8"))
        return Skill(
            name=config.get("name", directory.name),
            description=config.get("description", ""),
            instructions=prompt_path.read_text(encoding="utf-8").strip(),
            path=prompt_path,
            tags=tuple(config.get("tags", [])),
        )

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def search(self, query: str) -> list[Skill]:
        terms = set(query.lower().split())
        return sorted(
            self._skills.values(),
            key=lambda skill: len(
                terms
                & set(f"{skill.name} {skill.description} {' '.join(skill.tags)}".lower().split())
            ),
            reverse=True,
        )
