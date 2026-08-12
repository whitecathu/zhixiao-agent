"""Live evaluation harness against a real model provider.

Requires explicit opt-in:

  ZHIXIAO_LIVE_EVAL=1
  LLM_API_KEY=...

Without both, this process exits with code 2 and never calls a model.
CI must not set ZHIXIAO_LIVE_EVAL; offline gates use run_offline_gates.py /
fixtures/offline_harness_results.json instead.

Output JSON uses explicit live provenance so run_scenarios.py --results can
compute metrics without confusing it with checked-in fixture evidence.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent

# Allow importing sibling harness modules when invoked as a script.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from run_scenarios import DEFAULT_MANIFEST, load_json, validate_manifest  # noqa: E402


def require_live_enabled() -> None:
    """Refuse to run unless the operator opted into paid/live evaluation."""
    if os.environ.get("ZHIXIAO_LIVE_EVAL", "").strip() != "1":
        print(
            "live eval disabled: set ZHIXIAO_LIVE_EVAL=1 to run against a real model",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if not os.environ.get("LLM_API_KEY", "").strip():
        print(
            "live eval requires LLM_API_KEY (real model; Offline/Scripted are not used)",
            file=sys.stderr,
        )
        raise SystemExit(2)


def _env_cost_per_million(name: str) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return 0.0
    return float(raw)


def build_live_model():
    """Construct the production OpenAI-compatible client — never Offline/Scripted."""
    from zhixiao_agent.model import ModelProfile, OpenAICompatibleModel

    api_key = os.environ["LLM_API_KEY"].strip()
    return OpenAICompatibleModel(
        ModelProfile(
            provider=os.environ.get("LLM_PROVIDER", "deepseek"),
            model=os.environ.get("LLM_MODEL", "deepseek-chat"),
            api_base=os.environ.get("LLM_API_BASE", "https://api.deepseek.com/v1"),
            api_key=api_key,
            input_cost_per_million=_env_cost_per_million("LLM_INPUT_COST_PER_MILLION"),
            output_cost_per_million=_env_cost_per_million("LLM_OUTPUT_COST_PER_MILLION"),
        )
    )


def prepare_workspace(scenario: dict[str, Any], parent: Path) -> Path:
    """Use fixtures/<name> when present; otherwise a minimal scratch workspace."""
    fixture_name = str(scenario["fixture"])
    fixture_dir = ROOT / "fixtures" / "workspaces" / fixture_name
    target = parent / fixture_name
    if fixture_dir.is_dir():
        # Shallow copy: copytree would pull ignored trees; use symlink/junction when possible.
        import shutil

        shutil.copytree(fixture_dir, target)
    else:
        target.mkdir(parents=True, exist_ok=True)
        (target / "README.md").write_text(
            f"# Live eval fixture placeholder: {fixture_name}\n\n"
            f"Prompt: {scenario['prompt']}\n",
            encoding="utf-8",
        )
    return target.resolve(strict=True)


def derive_artifacts(result: Any) -> list[str]:
    """Map a RunResult into the evidence labels used by scenarios.json."""
    found: set[str] = set()
    events = list(getattr(result, "events", []) or [])
    if events:
        found.add("timeline")
    for event in events:
        name = getattr(event, "event", None) or (
            event.get("event") if isinstance(event, dict) else None
        )
        if name in {"approval_required", "approval"}:
            found.add("approval")
        if name in {"verification_finished", "test_finished"}:
            found.add("test_report")
        data = getattr(event, "data", None) or (
            event.get("data") if isinstance(event, dict) else {}
        )
        if isinstance(data, dict) and data.get("checkpoint"):
            found.add("checkpoint")
    if getattr(result, "diff", ""):
        found.add("diff")
    if getattr(result, "test_exit_code", None) is not None:
        found.add("test_report")
    status = getattr(getattr(result, "status", None), "value", None) or str(
        getattr(result, "status", "")
    )
    if status == "awaiting_approval":
        found.add("approval")
    for artifact in getattr(result, "artifacts", []) or []:
        kind = getattr(artifact, "kind", None) or (
            artifact.get("kind") if isinstance(artifact, dict) else None
        )
        if not kind:
            continue
        if kind in {"git_diff", "diff", "worktree"}:
            found.add("diff")
        elif kind in {"test_report", "coverage", "openapi", "migration", "e2e_report"}:
            found.add(str(kind))
        elif kind == "git_status":
            found.add("git_status")
        elif kind == "checkpoint":
            found.add("checkpoint")
    return sorted(found)


def grade_scenario(scenario: dict[str, Any], result: Any) -> tuple[bool, list[str]]:
    artifacts = derive_artifacts(result)
    required = set(scenario["required_evidence"])
    status = getattr(getattr(result, "status", None), "value", None) or str(
        getattr(result, "status", "")
    )
    category = scenario.get("category")
    if category in {"safety", "resilience"}:
        passed = required.issubset(set(artifacts)) and status in {
            "awaiting_approval",
            "succeeded",
            "interrupted",
        }
    else:
        passed = status == "succeeded" and required.issubset(set(artifacts))
    return passed, artifacts


def live_result_document(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "live",
        "evaluation_mode": "live",
        "metrics_source": "live_agent_runtime",
        "note": "Live AgentRuntime results. Requires ZHIXIAO_LIVE_EVAL=1 and LLM_API_KEY.",
        "results": results,
    }


async def run_one(
    runtime: Any,
    scenario: dict[str, Any],
    workspace: Path,
    *,
    model: Any,
) -> dict[str, Any]:
    from zhixiao_agent.runtime import RuntimeConfig
    from zhixiao_agent.types import PermissionMode

    permission = PermissionMode(scenario["permission"])
    started = time.perf_counter()
    usage_before = float(getattr(getattr(model, "usage", None), "cost_usd", 0.0) or 0.0)
    result = await runtime.run(
        scenario["prompt"],
        workspace,
        RuntimeConfig(
            permission=permission,
            approved=True,
            require_plan_approval=False,
            ops_approved=scenario.get("category") != "safety",
            isolate_worktree=False,
        ),
        run_id=f"live-{scenario['id']}",
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    usage_after = float(getattr(getattr(model, "usage", None), "cost_usd", 0.0) or 0.0)
    passed, artifacts = grade_scenario(scenario, result)
    repair_rounds = 0
    for event in getattr(result, "events", []) or []:
        name = getattr(event, "event", None) or (
            event.get("event") if isinstance(event, dict) else None
        )
        if name == "repair_started":
            repair_rounds += 1
    attempts = 1 + repair_rounds
    return {
        "scenario_id": scenario["id"],
        "passed": passed,
        "attempts": attempts,
        "latency_ms": latency_ms,
        "cost_usd": round(max(usage_after - usage_before, 0.0), 6),
        "hallucination_rate": 0.0,
        "artifacts": artifacts,
        "status": getattr(getattr(result, "status", None), "value", str(result.status)),
        "summary": getattr(result, "summary", "") or "",
    }


async def run_live(
    scenarios: list[dict[str, Any]],
    *,
    model: Any | None = None,
) -> dict[str, Any]:
    from zhixiao_agent.runtime import AgentRuntime

    live_model = model or build_live_model()
    runtime = AgentRuntime(live_model)
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="zhixiao-live-eval-") as tmp:
        parent = Path(tmp)
        for scenario in scenarios:
            workspace = prepare_workspace(scenario, parent)
            results.append(await run_one(runtime, scenario, workspace, model=live_model))
    return live_result_document(results)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run live eval scenarios against a real LLM")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "live_results.json",
    )
    parser.add_argument("--scenario-id", action="append", default=[])
    args = parser.parse_args(argv)

    require_live_enabled()
    manifest = load_json(args.manifest)
    scenarios = validate_manifest(manifest)
    if args.scenario_id:
        wanted = set(args.scenario_id)
        scenarios = [item for item in scenarios if item["id"] in wanted]
        if not scenarios:
            parser.error(f"no scenarios matched: {sorted(wanted)}")

    document = asyncio.run(run_live(scenarios))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    if not all(item["passed"] for item in document["results"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
