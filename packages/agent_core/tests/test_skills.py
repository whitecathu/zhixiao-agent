from pathlib import Path

from zhixiao_agent.skills import SkillManager, default_skill_roots, render_skill_context


def test_load_search_and_render_skills(tmp_path: Path) -> None:
    skill_root = tmp_path / "skills" / "PlannerBoost"
    skill_root.mkdir(parents=True)
    (skill_root / "config.json").write_text(
        '{"name": "PlannerBoost", "description": "planning decomposition helper", '
        '"tags": ["planning", "task"]}',
        encoding="utf-8",
    )
    (skill_root / "skprompt.txt").write_text(
        "Break the request into ordered verification steps.",
        encoding="utf-8",
    )

    manager = SkillManager([tmp_path / "skills"])
    loaded = manager.load()
    assert "PlannerBoost" in loaded

    matches = manager.search("planning task decomposition")
    assert matches[0].name == "PlannerBoost"

    rendered = render_skill_context("planning task for the agent", manager)
    assert "Relevant skills:" in rendered
    assert "PlannerBoost" in rendered
    assert "Break the request into ordered verification steps." in rendered


def test_default_skill_roots_exclude_untrusted_workspace(tmp_path: Path) -> None:
    roots = default_skill_roots(tmp_path)
    assert any(root.name == "skills" for root in roots)
    assert (tmp_path / ".zhixiao" / "skills").resolve() not in roots


def test_default_skill_roots_include_explicitly_trusted_workspace(tmp_path: Path) -> None:
    roots = default_skill_roots(tmp_path, trusted_workspace=True)
    assert (tmp_path / ".zhixiao" / "skills").resolve() in roots
