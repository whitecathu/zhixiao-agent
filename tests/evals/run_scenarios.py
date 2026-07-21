"""Validate the fixed engineering scenario set and summarize measured results.

This harness never invents measurements.  Validation-only output deliberately
contains null metrics.  A report is calculated only from an explicit result
file produced by an Agent run or CI job.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST = ROOT / "scenarios.json"
REQUIRED_CATEGORIES = {
    "defect_fix",
    "backend_feature",
    "frontend_feature",
    "test_generation",
    "full_stack_feature",
    "repair_loop",
    "resilience",
    "safety",
}
PERMISSIONS = {"read_only", "edit", "execute", "full"}


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def validate_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported scenario schema_version")
    scenarios = manifest.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("scenarios must be a non-empty list")
    ids: set[str] = set()
    categories: set[str] = set()
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise ValueError("each scenario must be an object")
        scenario_id = scenario.get("id")
        if not isinstance(scenario_id, str) or not scenario_id:
            raise ValueError("each scenario needs a non-empty id")
        if scenario_id in ids:
            raise ValueError(f"duplicate scenario id: {scenario_id}")
        ids.add(scenario_id)
        category = scenario.get("category")
        if not isinstance(category, str):
            raise ValueError(f"{scenario_id}: category is required")
        categories.add(category)
        if scenario.get("permission") not in PERMISSIONS:
            raise ValueError(f"{scenario_id}: invalid permission")
        for field in ("fixture", "prompt"):
            if not isinstance(scenario.get(field), str) or not scenario[field].strip():
                raise ValueError(f"{scenario_id}: {field} is required")
        for field in ("assertions", "required_evidence"):
            if not isinstance(scenario.get(field), list) or not scenario[field]:
                raise ValueError(f"{scenario_id}: {field} must be non-empty")
    missing = REQUIRED_CATEGORIES - categories
    if missing:
        raise ValueError(f"missing required scenario categories: {sorted(missing)}")
    return scenarios


def summarize_results(
    scenarios: list[dict[str, Any]], result_document: dict[str, Any]
) -> dict[str, Any]:
    results = result_document.get("results")
    if not isinstance(results, list):
        raise ValueError("results document must contain a results list")
    by_id = {item.get("scenario_id"): item for item in results if isinstance(item, dict)}
    expected = {scenario["id"] for scenario in scenarios}
    if set(by_id) != expected:
        raise ValueError("results must contain every scenario exactly once and no unknown ids")
    for scenario in scenarios:
        result = by_id[scenario["id"]]
        if not isinstance(result.get("passed"), bool):
            raise ValueError(f"{scenario['id']}: passed must be boolean")
        for field in ("attempts", "latency_ms"):
            if not isinstance(result.get(field), (int, float)) or result[field] < 0:
                raise ValueError(f"{scenario['id']}: {field} must be non-negative")
        artifacts = result.get("artifacts")
        if not isinstance(artifacts, list):
            raise ValueError(f"{scenario['id']}: artifacts must be a list")
        required = set(scenario["required_evidence"])
        if result["passed"] and not required.issubset(set(artifacts)):
            raise ValueError(f"{scenario['id']}: passed result lacks required evidence")

    ordered = [by_id[scenario["id"]] for scenario in scenarios]
    count = len(ordered)
    return {
        "scenario_count": count,
        "task_completion_rate": sum(item["passed"] for item in ordered) / count,
        "first_pass_rate": sum(item["passed"] and item["attempts"] == 1 for item in ordered) / count,
        "average_attempts": mean(item["attempts"] for item in ordered),
        "average_latency_ms": mean(item["latency_ms"] for item in ordered),
        "average_cost_usd": mean(float(item.get("cost_usd", 0.0)) for item in ordered),
        "hallucination_rate": mean(float(item.get("hallucination_rate", 0.0)) for item in ordered),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--results", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest = load_json(args.manifest)
    scenarios = validate_manifest(manifest)
    report: dict[str, Any] = {
        "dataset": manifest.get("dataset"),
        "schema_version": manifest["schema_version"],
        "scenario_count": len(scenarios),
        "status": "manifest_validated",
        "metrics": None,
    }
    if args.results:
        report["status"] = "measured"
        report["metrics"] = summarize_results(scenarios, load_json(args.results))
    elif not args.validate_only:
        parser.error("provide --results or explicitly use --validate-only")
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
