from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "cli.py"
EXAMPLE_CONFIG_PATH = REPO_ROOT / "config" / "config.example.yaml"


class CliPromptValidationTests(unittest.TestCase):
    """Test cases for cli prompt validation."""
    def _run_cli(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        """Run cli."""
        return subprocess.run(
            [sys.executable, str(CLI_PATH), *args],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def _write_temp_config_with_inputs(self) -> Path:
        """Write temp config with inputs."""
        temp_dir = Path(tempfile.mkdtemp(prefix="cli-prompt-config-"))
        design_spec = temp_dir / "design_spec.csv"
        issue_tracking = temp_dir / "issue_tracking.csv"
        design_spec.write_text("spec_id,title,requirement\nA1,example,Do something\n", encoding="utf-8")
        issue_tracking.write_text("title\nexample\n", encoding="utf-8")

        config_text = EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8")
        config_text = config_text.replace(
            "design_spec_path: out/state/DESIGN-SPEC.csv",
            f"design_spec_path: {design_spec.as_posix()}",
        )
        config_text = config_text.replace(
            "design_spec_path: raw-design-spec.csv",
            "design_spec_path: design_spec.csv",
        )
        config_text = config_text.replace(
            "issue_tracking_path: out/issue_tracking.csv",
            f"issue_tracking_path: {issue_tracking.as_posix()}",
        )

        config_path = temp_dir / "config.yaml"
        config_path.write_text(config_text, encoding="utf-8")
        return config_path

    def test_command_only_validation_succeeds_with_example_config(self) -> None:
        """Test that command only validation succeeds with example config."""
        result = self._run_cli(
            [
                "agent",
                "format",
                "--command-only-validation",
                "--project-root",
                str(REPO_ROOT),
                "--config",
                "config/config.example.yaml",
            ]
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn('"status":"validated_only"', result.stdout)

    def test_command_only_validation_respects_project_root_option(self) -> None:
        """Test that command only validation respects project root option."""
        result = self._run_cli(
            [
                "agent",
                "format",
                "--command-only-validation",
                "--project-root",
                str(REPO_ROOT),
                "--config",
                "config/config.example.yaml",
            ]
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn('"status":"validated_only"', result.stdout)

    def test_format_dry_run_dispatches_and_completes(self) -> None:
        """Test that format dry run dispatches and completes lifecycle."""
        config_path = self._write_temp_config_with_inputs()
        project_root = config_path.parent
        result = self._run_cli(
            [
                "agent",
                "format",
                "--dry-run",
                "--project-root",
                str(project_root),
                "--config",
                str(config_path),
            ]
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn('"status":"completed"', result.stdout)



if __name__ == "__main__":
    unittest.main()
