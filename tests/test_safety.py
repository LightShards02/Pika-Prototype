from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "cli.py"
EXAMPLE_CONFIG_PATH = REPO_ROOT / "config" / "config.example.yaml"


class SafetyRailTests(unittest.TestCase):
    """Test cases for safety rail."""
    def _run_cli(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        """Run cli."""
        return subprocess.run(
            [sys.executable, str(CLI_PATH), *args],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def _write_config(
        self,
        temp_dir: Path,
        *,
        design_spec_path: str,
        issue_tracking_path: str,
        log_dir: str | None = None,
        run_summary_file: str | None = None,
    ) -> Path:
        """Write config."""
        config_text = EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8")
        config_text = config_text.replace(
            "  design_spec_path: data/design_spec.csv",
            f"  design_spec_path: {design_spec_path}",
        )
        config_text = config_text.replace(
            "  issue_tracking_path: data/issue_tracking.csv",
            f"  issue_tracking_path: {issue_tracking_path}",
        )
        if log_dir is not None:
            config_text = config_text.replace("  log_dir: out/logs", f"  log_dir: {log_dir}")
        if run_summary_file is not None:
            config_text = config_text.replace(
                "    path: out/agent_runs/run_summary.jsonl",
                f"    path: {run_summary_file}",
            )

        config_path = temp_dir / "config.yaml"
        config_path.write_text(config_text, encoding="utf-8")
        return config_path

    def test_load_fails_when_required_input_missing(self) -> None:
        """Test that load fails when required input missing."""
        with tempfile.TemporaryDirectory(prefix="safety-missing-input-") as raw_tmp:
            temp_dir = Path(raw_tmp)
            issue_tracking = temp_dir / "issue_tracking.csv"
            issue_tracking.write_text("title\nissue\n", encoding="utf-8")

            missing_design_spec = temp_dir / "does_not_exist.csv"
            config_path = self._write_config(
                temp_dir,
                design_spec_path=missing_design_spec.as_posix(),
                issue_tracking_path=issue_tracking.as_posix(),
            )

            result = self._run_cli(
                ["agent", "load", "--dry-run", "--config", str(config_path)]
            )

            self.assertEqual(result.returncode, 1, msg=result.stderr)
            self.assertIn("Missing input file for 'load'", result.stderr)
            self.assertIn('"status":"failed"', result.stdout)

    def test_load_fails_when_log_dir_is_outside_project_root(self) -> None:
        """Test that load fails when log dir is outside project root."""
        with tempfile.TemporaryDirectory(prefix="safety-unwritable-log-") as raw_tmp:
            temp_dir = Path(raw_tmp)
            design_spec = temp_dir / "design_spec.csv"
            issue_tracking = temp_dir / "issue_tracking.csv"
            design_spec.write_text("title\nspec\n", encoding="utf-8")
            issue_tracking.write_text("title\nissue\n", encoding="utf-8")

            blocker_file = temp_dir / "blocked-parent"
            blocker_file.write_text("this is a file", encoding="utf-8")
            invalid_log_dir = (blocker_file / "logs").as_posix()

            config_path = self._write_config(
                temp_dir,
                design_spec_path=design_spec.as_posix(),
                issue_tracking_path=issue_tracking.as_posix(),
                log_dir=invalid_log_dir,
            )

            result = self._run_cli(
                ["agent", "load", "--dry-run", "--config", str(config_path)]
            )

            self.assertEqual(result.returncode, 1, msg=result.stderr)
            self.assertIn("Unsafe log_dir", result.stderr)
            self.assertIn('"status":"failed"', result.stdout)

    def test_load_rejects_output_path_outside_project_root(self) -> None:
        """Test that load rejects output path outside project root."""
        with tempfile.TemporaryDirectory(prefix="safety-outside-output-") as raw_tmp:
            temp_dir = Path(raw_tmp)
            design_spec = temp_dir / "design_spec.csv"
            issue_tracking = temp_dir / "issue_tracking.csv"
            design_spec.write_text("title\nspec\n", encoding="utf-8")
            issue_tracking.write_text("title\nissue\n", encoding="utf-8")

            outside_output = (temp_dir / "outside_run_summary.jsonl").resolve().as_posix()
            config_path = self._write_config(
                temp_dir,
                design_spec_path=design_spec.as_posix(),
                issue_tracking_path=issue_tracking.as_posix(),
                run_summary_file=outside_output,
            )

            result = self._run_cli(
                ["agent", "load", "--dry-run", "--config", str(config_path)]
            )

            self.assertEqual(result.returncode, 1, msg=result.stderr)
            self.assertIn("resolves outside project root", result.stderr)
            self.assertIn('"status":"failed"', result.stdout)

    def test_load_rejects_existing_output_when_no_overwrite_enabled(self) -> None:
        """Test that load rejects existing output when no overwrite enabled."""
        with tempfile.TemporaryDirectory(prefix="safety-no-overwrite-") as raw_tmp:
            temp_dir = Path(raw_tmp)
            design_spec = temp_dir / "design_spec.csv"
            issue_tracking = temp_dir / "issue_tracking.csv"
            design_spec.write_text("title\nspec\n", encoding="utf-8")
            issue_tracking.write_text("title\nissue\n", encoding="utf-8")

            existing_output = REPO_ROOT / "out" / "test-no-overwrite" / f"{uuid.uuid4().hex}.jsonl"
            existing_output.parent.mkdir(parents=True, exist_ok=True)
            existing_output.write_text("already exists\n", encoding="utf-8")

            config_path = self._write_config(
                temp_dir,
                design_spec_path=design_spec.as_posix(),
                issue_tracking_path=issue_tracking.as_posix(),
                run_summary_file=existing_output.as_posix(),
            )

            config_text = config_path.read_text(encoding="utf-8").replace(
                f"  run_summary_file:\n    path: {existing_output.as_posix()}\n    no_overwrite: false",
                f"  run_summary_file:\n    path: {existing_output.as_posix()}\n    no_overwrite: true",
            )
            config_path.write_text(config_text, encoding="utf-8")

            result = self._run_cli(
                ["agent", "load", "--dry-run", "--config", str(config_path)]
            )

            self.assertEqual(result.returncode, 1, msg=result.stderr)
            self.assertIn("no-overwrite is enabled", result.stderr)
            self.assertIn('"status":"failed"', result.stdout)

    def test_command_only_validation_bypasses_safety_rails(self) -> None:
        """Test that command only validation bypasses safety rails."""
        with tempfile.TemporaryDirectory(prefix="safety-validation-bypass-") as raw_tmp:
            temp_dir = Path(raw_tmp)
            missing_design_spec = temp_dir / "missing_design.csv"
            missing_issue_tracking = temp_dir / "missing_issue.csv"

            blocker_file = temp_dir / "blocked-parent"
            blocker_file.write_text("this is a file", encoding="utf-8")
            invalid_log_dir = (blocker_file / "logs").as_posix()

            config_path = self._write_config(
                temp_dir,
                design_spec_path=missing_design_spec.as_posix(),
                issue_tracking_path=missing_issue_tracking.as_posix(),
                log_dir=invalid_log_dir,
            )

            result = self._run_cli(
                [
                    "agent",
                    "load",
                    "--command-only-validation",
                    "--config",
                    str(config_path),
                ]
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn('"status":"validated_only"', result.stdout)


if __name__ == "__main__":
    unittest.main()
