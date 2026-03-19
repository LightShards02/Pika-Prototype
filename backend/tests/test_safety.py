from __future__ import annotations

import re
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
        agent_runs_dir: str | None = None,
        format_output_path: str | None = None,
    ) -> Path:
        """Write config. Injects design_spec_path into project.state, format inputs, and issue_tracking_path."""
        config_text = EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8")
        # project.state.design_spec_path
        config_text = re.sub(
            r"(\n  state:\n    design_spec_path:)\s*[^\n]+",
            rf"\1 {design_spec_path}",
            config_text,
            count=1,
        )
        # commands.format.inputs (format uses design_spec_path only)
        config_text = config_text.replace(
            "design_spec_path: raw-design-spec.csv",
            f"design_spec_path: {design_spec_path}",
        )
        # commands.resolve_plan.inputs.issue_tracking_path
        config_text = config_text.replace(
            "issue_tracking_path: out/issue_tracking.csv",
            f"issue_tracking_path: {issue_tracking_path}",
        )
        if log_dir is not None:
            config_text = config_text.replace("  log_dir: out/logs", f"  log_dir: {log_dir}")
        if agent_runs_dir is not None:
            config_text = config_text.replace(
                "path: out/agent_runs",
                f"path: {agent_runs_dir}",
                1,
            )
        if format_output_path is not None:
            config_text = config_text.replace(
                "path: out/state/DESIGN-SPEC.csv",
                f"path: {format_output_path}",
                1,
            )

        config_path = temp_dir / "config.yaml"
        config_path.write_text(config_text, encoding="utf-8")
        return config_path

    def test_format_fails_when_required_input_missing(self) -> None:
        """Test that format fails when required input missing."""
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
                [
                    "agent",
                    "format",
                    "--dry-run",
                    "--project-root",
                    str(temp_dir),
                    "--config",
                    str(config_path),
                ]
            )

            self.assertEqual(result.returncode, 1, msg=result.stderr)
            self.assertIn("Missing input file for 'format'", result.stderr)
            self.assertIn('"status":"failed"', result.stdout)

    def test_format_fails_when_log_dir_is_outside_project_root(self) -> None:
        """Test that format fails when log dir is outside project root."""
        with tempfile.TemporaryDirectory(prefix="safety-unwritable-log-") as raw_tmp:
            temp_dir = Path(raw_tmp)
            design_spec = temp_dir / "design_spec.csv"
            issue_tracking = temp_dir / "issue_tracking.csv"
            design_spec.write_text("title\nspec\n", encoding="utf-8")
            issue_tracking.write_text("title\nissue\n", encoding="utf-8")

            # Log dir outside project root (parent of temp_dir)
            invalid_log_dir = (
                Path(temp_dir).parent / "logs_outside_project"
            ).resolve().as_posix()

            config_path = self._write_config(
                temp_dir,
                design_spec_path=design_spec.as_posix(),
                issue_tracking_path=issue_tracking.as_posix(),
                log_dir=invalid_log_dir,
            )

            result = self._run_cli(
                [
                    "agent",
                    "format",
                    "--dry-run",
                    "--project-root",
                    str(temp_dir),
                    "--config",
                    str(config_path),
                ]
            )

            self.assertEqual(result.returncode, 1, msg=result.stderr)
            self.assertIn("Unsafe log_dir", result.stderr)
            self.assertIn('"status":"failed"', result.stdout)

    def test_format_rejects_output_path_outside_project_root(self) -> None:
        """Test that format rejects output path outside project root."""
        with tempfile.TemporaryDirectory(prefix="safety-outside-output-") as raw_tmp:
            temp_dir = Path(raw_tmp)
            design_spec = temp_dir / "design_spec.csv"
            issue_tracking = temp_dir / "issue_tracking.csv"
            design_spec.write_text(
                "spec_id,title,requirement\nA1,Test,Do something\n",
                encoding="utf-8",
            )
            issue_tracking.write_text("title\nissue\n", encoding="utf-8")

            # Format output path outside project root
            outside_output = (
                Path(temp_dir).parent / "outside_project_design_spec.csv"
            ).resolve().as_posix()
            config_path = self._write_config(
                temp_dir,
                design_spec_path=design_spec.as_posix(),
                issue_tracking_path=issue_tracking.as_posix(),
                format_output_path=outside_output,
            )

            result = self._run_cli(
                [
                    "agent",
                    "format",
                    "--dry-run",
                    "--project-root",
                    str(temp_dir),
                    "--config",
                    str(config_path),
                ]
            )

            self.assertEqual(result.returncode, 1, msg=result.stderr)
            self.assertIn("resolves outside project root", result.stderr)
            self.assertIn('"status":"failed"', result.stdout)

    def test_format_rejects_existing_output_when_no_overwrite_enabled(self) -> None:
        """Test that format rejects existing output when no overwrite enabled."""
        with tempfile.TemporaryDirectory(prefix="safety-no-overwrite-") as raw_tmp:
            temp_dir = Path(raw_tmp)
            design_spec = temp_dir / "design_spec.csv"
            issue_tracking = temp_dir / "issue_tracking.csv"
            design_spec.write_text("spec_id,title,requirement\nA1,Test,Do something\n", encoding="utf-8")
            issue_tracking.write_text("title\nissue\n", encoding="utf-8")

            # Create existing format output to trigger no-overwrite
            existing_output = temp_dir / "out" / "state" / "DESIGN-SPEC.csv"
            existing_output.parent.mkdir(parents=True, exist_ok=True)
            existing_output.write_text("already exists\n", encoding="utf-8")

            config_path = self._write_config(
                temp_dir,
                design_spec_path=design_spec.as_posix(),
                issue_tracking_path=issue_tracking.as_posix(),
            )

            # Set format outputs design_spec_path no_overwrite to true
            config_text = config_path.read_text(encoding="utf-8").replace(
                "design_spec_path:\n        path: out/state/DESIGN-SPEC.csv\n        no_overwrite: false",
                "design_spec_path:\n        path: out/state/DESIGN-SPEC.csv\n        no_overwrite: true",
            )
            config_path.write_text(config_text, encoding="utf-8")

            result = self._run_cli(
                [
                    "agent",
                    "format",
                    "--dry-run",
                    "--project-root",
                    str(temp_dir),
                    "--config",
                    str(config_path),
                ]
            )

            self.assertEqual(result.returncode, 1, msg=result.stderr)
            self.assertIn("no-overwrite is enabled", result.stderr)
            self.assertIn('"status":"failed"', result.stdout)

    def test_format_accepts_input_via_cli_override(self) -> None:
        """Test that format accepts CSV/XLSX input via --design-spec and processes normally."""
        with tempfile.TemporaryDirectory(prefix="safety-format-input-") as raw_tmp:
            temp_dir = Path(raw_tmp)
            csv_file = temp_dir / "spec.csv"
            csv_file.write_text(
                "spec_id,title,requirement\nA1,Test,Do something\n",
                encoding="utf-8",
            )
            issue_tracking = temp_dir / "issue_tracking.csv"
            issue_tracking.write_text("title\nissue\n", encoding="utf-8")

            config_path = self._write_config(
                temp_dir,
                design_spec_path=csv_file.as_posix(),
                issue_tracking_path=issue_tracking.as_posix(),
            )

            result = self._run_cli(
                [
                    "agent",
                    "format",
                    "--dry-run",
                    "--project-root",
                    str(temp_dir),
                    "--config",
                    str(config_path),
                    "--design-spec",
                    str(csv_file),
                ]
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn('"status":"completed"', result.stdout)

    def test_format_rejects_input_with_invalid_extension(self) -> None:
        """Test that format rejects input file with non-CSV/XLSX extension."""
        with tempfile.TemporaryDirectory(prefix="safety-format-bad-ext-") as raw_tmp:
            temp_dir = Path(raw_tmp)
            txt_file = temp_dir / "spec.txt"
            txt_file.write_text("spec_id,title\nA1,Test\n", encoding="utf-8")
            issue_tracking = temp_dir / "issue_tracking.csv"
            issue_tracking.write_text("title\nissue\n", encoding="utf-8")

            config_path = self._write_config(
                temp_dir,
                design_spec_path=txt_file.as_posix(),
                issue_tracking_path=issue_tracking.as_posix(),
            )

            result = self._run_cli(
                [
                    "agent",
                    "format",
                    "--dry-run",
                    "--project-root",
                    str(temp_dir),
                    "--config",
                    str(config_path),
                ]
            )

            self.assertEqual(result.returncode, 1, msg=result.stderr)
            self.assertIn("Format input must be CSV or XLSX", result.stderr)
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
                    "format",
                    "--command-only-validation",
                    "--project-root",
                    str(temp_dir),
                    "--config",
                    str(config_path),
                ]
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn('"status":"validated_only"', result.stdout)


if __name__ == "__main__":
    unittest.main()
