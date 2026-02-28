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
        """Write config. Injects design_spec_path and issue_tracking_path into inputs."""
        config_text = EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8")
        # Example config may not have design_spec_path; inject after allowed_extensions
        if "design_spec_path:" not in config_text:
            config_text = config_text.replace(
                "  allowed_extensions:\n    - .csv\n    - .xlsx",
                f"  allowed_extensions:\n    - .csv\n    - .xlsx\n  design_spec_path: {design_spec_path}\n  issue_tracking_path: {issue_tracking_path}",
            )
        else:
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
            design_spec.write_text("title\nspec\n", encoding="utf-8")
            issue_tracking.write_text("title\nissue\n", encoding="utf-8")

            # Path outside project root (parent of temp_dir)
            outside_output = (
                Path(temp_dir).parent / "outside_project_run_summary.jsonl"
            ).resolve().as_posix()
            config_path = self._write_config(
                temp_dir,
                design_spec_path=design_spec.as_posix(),
                issue_tracking_path=issue_tracking.as_posix(),
                run_summary_file=outside_output,
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
        """Test that format accepts CSV/XLSX input via --input and processes normally."""
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
                    "--input",
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
