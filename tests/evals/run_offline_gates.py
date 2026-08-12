"""Offline evaluation gates that do not require a live model provider.

Produces an offline-harness report from deterministic policy/security checks
plus checked-in fixture results. It does not measure live model quality.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from zhixiao_agent.security import CommandPolicy, PermissionDenied, WorkspaceBoundary
from zhixiao_agent.types import PermissionMode

ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "fixtures" / "offline_harness_results.json"


def assert_security_gates() -> None:
    policy = CommandPolicy()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "repo").mkdir()
        boundary = WorkspaceBoundary(root / "repo")
        try:
            boundary.resolve("../escape.txt")
            raise AssertionError("workspace escape was not blocked")
        except Exception:
            pass
    for command in ("git push origin main", "rm -rf /tmp/x"):
        try:
            policy.validate(command, PermissionMode.FULL, approved=False)
            raise AssertionError(f"{command} should require ops approval")
        except PermissionDenied:
            pass
        policy.validate(command, PermissionMode.FULL, approved=True)


def main() -> None:
    assert_security_gates()
    import sys

    sys.path.insert(0, str(ROOT))
    from run_scenarios import (
        load_json,
        summarize_results,
        validate_manifest,
        validate_result_provenance,
    )

    manifest = load_json(ROOT / "scenarios.json")
    scenarios = validate_manifest(manifest)
    results = load_json(FIXTURE)
    provenance = validate_result_provenance(results)
    metrics = summarize_results(scenarios, results)
    report = {
        "dataset": manifest.get("dataset"),
        "schema_version": manifest["schema_version"],
        "scenario_count": len(scenarios),
        **provenance,
        "metrics": metrics,
    }
    output = ROOT / "artifacts" / "offline_report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
