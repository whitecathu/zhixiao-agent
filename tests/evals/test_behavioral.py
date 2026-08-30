from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

import run_behavioral

ROOT = Path(__file__).resolve().parent


class BehavioralEvaluationTests(unittest.TestCase):
    def test_dangerous_command_blocks_without_ops_capabilities(self) -> None:
        run_behavioral.eval_dangerous_command()

    def test_interrupt_resume_continues_same_run_id(self) -> None:
        run_behavioral.eval_interrupt_resume()

    def test_ask_mode_advertises_only_read_only_tools(self) -> None:
        run_behavioral.eval_ask_read_only()

    def test_runner_exits_zero_and_writes_runtime_report(self) -> None:
        completed = subprocess.run(  # noqa: S603
            [sys.executable, str(ROOT / "run_behavioral.py")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        report = json.loads(completed.stdout)
        self.assertTrue(report["passed"])
        self.assertEqual(report["evaluation_mode"], "scripted_agent_runtime")
        self.assertEqual(report["metrics_source"], "agent_runtime")
        self.assertNotIn("hallucination_rate", report)
        self.assertEqual(
            [item["id"] for item in report["gates"]],
            ["dangerous-command", "interrupt-resume", "ask-read-only"],
        )
        self.assertTrue(all(item["passed"] for item in report["gates"]))
        on_disk = json.loads(
            (ROOT / "artifacts" / "behavioral_report.json").read_text(encoding="utf-8")
        )
        self.assertEqual(on_disk["passed"], True)


if __name__ == "__main__":
    unittest.main()
