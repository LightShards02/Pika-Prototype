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
        design_spec.write_text("title\nexample\n", encoding="utf-8")
        issue_tracking.write_text("title\nexample\n", encoding="utf-8")

        config_text = EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8")
        config_text = config_text.replace(
            "  design_spec_path: data/design_spec.csv",
            f"  design_spec_path: {design_spec.as_posix()}",
        )
        config_text = config_text.replace(
            "  issue_tracking_path: data/issue_tracking.csv",
            f"  issue_tracking_path: {issue_tracking.as_posix()}",
        )

        config_path = temp_dir / "config.yaml"
        config_path.write_text(config_text, encoding="utf-8")
        return config_path

    def test_command_only_validation_succeeds_with_example_config(self) -> None:
        """Test that command only validation succeeds with example config."""
        result = self._run_cli(
            [
                "agent",
                "load",
                "--command-only-validation",
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
                "load",
                "--command-only-validation",
                "--project-root",
                str(REPO_ROOT),
                "--config",
                "config/config.example.yaml",
            ]
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn('"status":"validated_only"', result.stdout)

    def test_load_dry_run_dispatches_and_initializes(self) -> None:
        """Test that load dry run dispatches and initializes."""
        config_path = self._write_temp_config_with_inputs()
        result = self._run_cli(
            [
                "agent",
                "load",
                "--dry-run",
                "--config",
                str(config_path),
            ]
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn('"status":"initialized"', result.stdout)

    def test_command_only_validation_fails_when_prompt_file_missing(self) -> None:
        """Test that command only validation fails when prompt file missing."""
        with tempfile.TemporaryDirectory(prefix="cli-prompt-fail-") as tmpdir:
            tmp_config_path = Path(tmpdir) / "config.yaml"
            config_text = EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8")
            missing_prompt_path = (Path(tmpdir) / "does_not_exist.yaml").as_posix()
            config_text = config_text.replace(
                "  prompt_file: prompts/PROMPT.yaml",
                f"  prompt_file: {missing_prompt_path}",
            )
            tmp_config_path.write_text(config_text, encoding="utf-8")

            result = self._run_cli(
                [
                    "agent",
                    "load",
                    "--command-only-validation",
                    "--config",
                    str(tmp_config_path),
                ]
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Prompt file not found", result.stderr)
        self.assertIn('"status":"failed"', result.stdout)


if __name__ == "__main__":
    unittest.main()
