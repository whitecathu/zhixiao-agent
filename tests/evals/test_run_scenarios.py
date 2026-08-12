from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import run_live
from run_scenarios import (
    DEFAULT_MANIFEST,
    load_json,
    summarize_results,
    validate_manifest,
    validate_result_provenance,
)


ROOT = Path(__file__).resolve().parent


class EvaluationManifestTests(unittest.TestCase):
    def test_fixed_manifest_covers_required_scenario_types(self) -> None:
        scenarios = validate_manifest(load_json(DEFAULT_MANIFEST))
        self.assertEqual(len(scenarios), 8)

    def test_metrics_require_complete_evidence_backed_results(self) -> None:
        scenarios = validate_manifest(load_json(DEFAULT_MANIFEST))
        results = {
            "results": [
                {
                    "scenario_id": item["id"],
                    "passed": True,
                    "attempts": 1,
                    "latency_ms": 100,
                    "cost_usd": 0.01,
                    "hallucination_rate": 0.0,
                    "artifacts": item["required_evidence"],
                }
                for item in scenarios
            ]
        }
        metrics = summarize_results(scenarios, results)
        self.assertEqual(metrics["task_completion_rate"], 1.0)
        self.assertEqual(metrics["first_pass_rate"], 1.0)

    def test_passed_result_without_evidence_is_rejected(self) -> None:
        scenarios = validate_manifest(load_json(DEFAULT_MANIFEST))
        results = {
            "results": [
                {
                    "scenario_id": item["id"],
                    "passed": True,
                    "attempts": 1,
                    "latency_ms": 100,
                    "artifacts": [],
                }
                for item in scenarios
            ]
        }
        with self.assertRaisesRegex(ValueError, "lacks required evidence"):
            summarize_results(scenarios, results)

    def test_validate_only_forces_null_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "manifest.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "run_scenarios.py"),
                    "--validate-only",
                    "--output",
                    str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "manifest_validated")
            self.assertEqual(report["evaluation_mode"], "manifest_only")
            self.assertIsNone(report["metrics_source"])
            self.assertIsNone(report["metrics"])

    def test_offline_fixture_report_preserves_explicit_provenance(self) -> None:
        fixture = ROOT / "fixtures" / "offline_harness_results.json"
        provenance = validate_result_provenance(load_json(fixture))
        self.assertEqual(
            provenance,
            {
                "status": "offline_harness",
                "evaluation_mode": "offline_fixture",
                "metrics_source": "fixture",
            },
        )

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "offline-report.json"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "run_scenarios.py"),
                    "--results",
                    str(fixture),
                    "--output",
                    str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "offline_harness")
            self.assertEqual(report["evaluation_mode"], "offline_fixture")
            self.assertEqual(report["metrics_source"], "fixture")

    def test_ambiguous_result_provenance_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "evaluation_mode"):
            validate_result_provenance({"status": "measured", "results": []})


class LiveEvalGateTests(unittest.TestCase):
    def test_live_exits_without_opt_in(self) -> None:
        env = os.environ.copy()
        env.pop("ZHIXIAO_LIVE_EVAL", None)
        env["LLM_API_KEY"] = "dummy"
        completed = subprocess.run(
            [sys.executable, str(ROOT / "run_live.py")],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("ZHIXIAO_LIVE_EVAL", completed.stderr)

    def test_live_exits_without_api_key(self) -> None:
        env = os.environ.copy()
        env["ZHIXIAO_LIVE_EVAL"] = "1"
        env.pop("LLM_API_KEY", None)
        completed = subprocess.run(
            [sys.executable, str(ROOT / "run_live.py")],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("LLM_API_KEY", completed.stderr)

    def test_require_live_enabled_helper(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit) as raised:
                run_live.require_live_enabled()
            self.assertEqual(raised.exception.code, 2)

    def test_live_result_document_has_live_provenance(self) -> None:
        document = run_live.live_result_document([])
        self.assertEqual(document["status"], "live")
        self.assertEqual(document["evaluation_mode"], "live")
        self.assertEqual(document["metrics_source"], "live_agent_runtime")


if __name__ == "__main__":
    unittest.main()
