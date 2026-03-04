from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "cli.py"
EXAMPLE_CONFIG_PATH = REPO_ROOT / "config" / "config.example.yaml"


class CliLoggingTests(unittest.TestCase):
    """Test cases for cli logging."""
    def _run_cli(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        """Run cli."""
        return subprocess.run(
            [sys.executable, str(CLI_PATH), *args],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def _extract_summary(self, stdout: str) -> dict:
        """Extract summary."""
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                return json.loads(line)
        self.fail(f"No JSON summary found in stdout:\n{stdout}")

    def _write_temp_config(self, *, logs_dir: Path, temp_dir: Path | None = None) -> Path:
        """Write temp config."""
        if temp_dir is None:
            temp_dir = Path(tempfile.mkdtemp(prefix="cli-logging-config-"))
        design_spec = temp_dir / "design_spec.csv"
        issue_tracking = temp_dir / "issue_tracking.csv"
        design_spec.write_text(
            "spec_id,title,requirement\nA1,Example,Do something\n",
            encoding="utf-8",
        )
        issue_tracking.write_text("title\nexample\n", encoding="utf-8")
        (temp_dir / "PROJECT_CONTEXT.md").write_text("# Project\n", encoding="utf-8")
        temp_config = temp_dir / "config.yaml"
        config_text = EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8")
        config_text = config_text.replace(
            "  log_dir: out/logs",
            f"  log_dir: {logs_dir.as_posix()}",
        )
        config_text = config_text.replace(
            "design_spec_path: out/state/DESIGN-SPEC.csv",
            f"design_spec_path: {design_spec.as_posix()}",
        )
        config_text = config_text.replace(
            "design_spec_path: raw-design-spec.csv",
            f"design_spec_path: {design_spec.as_posix()}",
        )
        config_text = config_text.replace(
            "issue_tracking_path: out/issue_tracking.csv",
            f"issue_tracking_path: {issue_tracking.as_posix()}",
        )
        temp_config.write_text(config_text, encoding="utf-8")
        return temp_config

    def test_format_dry_run_creates_per_run_log_file(self) -> None:
        """Test that format dry run creates per run log file."""
        temp_dir = Path(tempfile.mkdtemp(prefix="cli-logging-config-"))
        logs_dir = temp_dir / "out" / "test-logs" / uuid.uuid4().hex
        config_path = self._write_temp_config(logs_dir=logs_dir, temp_dir=temp_dir)

        result = self._run_cli(
            [
                "agent",
                "format",
                "--dry-run",
                "--project-root",
                str(config_path.parent),
                "--config",
                str(config_path),
            ]
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        summary = self._extract_summary(result.stdout)
        run_id = summary.get("run_id")
        self.assertIsInstance(run_id, str)
        self.assertTrue(run_id)

        log_file = logs_dir / f"format_{run_id}.log"
        self.assertTrue(log_file.exists())

        entries = [
            json.loads(line)
            for line in log_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        events = [entry.get("event") for entry in entries]
        self.assertIn("command_start", events)
        self.assertIn("command_end", events)

    def test_command_only_validation_creates_no_run_log_file(self) -> None:
        """Test that command only validation creates no run log file."""
        temp_dir = Path(tempfile.mkdtemp(prefix="cli-logging-config-"))
        logs_dir = temp_dir / "out" / "test-logs" / uuid.uuid4().hex
        config_path = self._write_temp_config(logs_dir=logs_dir, temp_dir=temp_dir)

        result = self._run_cli(
            [
                "agent",
                "format",
                "--command-only-validation",
                "--project-root",
                str(config_path.parent),
                "--config",
                str(config_path),
            ]
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        summary = self._extract_summary(result.stdout)
        self.assertEqual(summary.get("status"), "validated_only")
        self.assertIsNone(summary.get("run_id"))
        self.assertFalse(logs_dir.exists())


if __name__ == "__main__":
    unittest.main()
