from __future__ import annotations

import unittest

from run_scenarios import load_json, summarize_results, validate_manifest, DEFAULT_MANIFEST


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


if __name__ == "__main__":
    unittest.main()
