"""Tests for strict resume validation in cli._execute_command."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import _execute_command


class CliResumeValidationTests(unittest.TestCase):
    """Tests for CLI --resume validation behavior."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cli-resume-"))
        self.config_path = self.tmp / "config.yaml"
        self.config_path.write_text("project: {}\n", encoding="utf-8")

        self.config_data = {
            "project": {
                "name": "test",
                "root_dir": ".",
                "state": {
                    "design_spec_path": str(self.tmp / "out" / "state" / "DESIGN-SPEC.csv"),
                    "id_registry_path": str(self.tmp / "out" / "state" / "id_registry.json"),
                    "sads_id_mapping_path": str(self.tmp / "out" / "state" / "sads_id_mapping.json"),
                },
            },
            "prompts": {"prompt_file": "prompts/PROMPT.yaml"},
            "commands": {
                "plan": {
                    "enabled": True,
                    "inputs": {
                        "srs_path": str(self.tmp / "srs.md"),
                        "project_context_filename": "PROJECT_CONTEXT.md",
                    },
                    "outputs": {
                        "agent_runs_dir": {"path": "out/agent_runs", "no_overwrite": False},
                    },
                }
            },
        }
        (self.tmp / "srs.md").write_text("# SRS\n", encoding="utf-8")
        (self.tmp / "PROJECT_CONTEXT.md").write_text(
            "## Purpose\nx\n\n## Overview\nx\n\n## Workflow\nx\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_run_meta(self, run_id: str, blocked_at_stage: str = "plan") -> Path:
        run_dir = self.tmp / "out" / "agent_runs" / "plan" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "run_meta.json").write_text(
            (
                "{\n"
                '  "command": "plan",\n'
                f'  "run_id": "{run_id}",\n'
                f'  "blocked_at_stage": "{blocked_at_stage}",\n'
                '  "completed_stages": ["load_inputs"],\n'
                '  "resolution_status": "pending"\n'
                "}\n"
            ),
            encoding="utf-8",
        )
        return run_dir

    def _write_resolutions_yaml(self, run_dir: Path, *, chosen_option_id: str | None) -> None:
        manual_dir = run_dir / "manual_resolution"
        manual_dir.mkdir(parents=True, exist_ok=True)
        chosen = f'"{chosen_option_id}"' if chosen_option_id else ""
        (manual_dir / "resolutions.yaml").write_text(
            (
                'run_id: "run"\n'
                'command: "plan"\n'
                'blocked_at_stage: "plan"\n'
                'generated_at: "2026-03-06T12:00:00"\n'
                "items:\n"
                '  - item_id: "MR-1"\n'
                '    source: "agent"\n'
                "    required: true\n"
                "    options:\n"
                '      - option_id: "opt_a"\n'
                '        label: "Use A"\n'
                f"    chosen_option_id: {chosen}\n"
                "    free_text:\n"
            ),
            encoding="utf-8",
        )

    def _write_validation_edit_spec_resolutions_yaml(self, run_dir: Path, *, manual_edit: bool) -> None:
        manual_dir = run_dir / "manual_resolution"
        manual_dir.mkdir(parents=True, exist_ok=True)
        edit_text = '"Updated requirement text"' if manual_edit else ""
        (manual_dir / "resolutions.yaml").write_text(
            (
                'run_id: "run"\n'
                'command: "implement"\n'
                'blocked_at_stage: "contract_field_consistency"\n'
                'generated_at: "2026-03-06T12:00:00"\n'
                "items:\n"
                '  - item_id: "field_mismatch_c1_A1_date_range"\n'
                '    source: "validation"\n'
                "    required: true\n"
                '    resolution_mode: "edit_spec"\n'
                "    options: []\n"
                f"    chosen_option_id: {('manual_edit' if manual_edit else '')}\n"
                f"    manual_edit_text: {edit_text}\n"
                '    manual_edit_spec_id: "A1"\n'
                '    manual_edit_field: "requirement"\n'
            ),
            encoding="utf-8",
        )

    @patch("cli._emit_summary")
    @patch("cli.dispatch")
    @patch("cli.init_run_logger")
    @patch("cli.validate_command_preconditions")
    @patch("cli.load_and_validate_config")
    def test_resume_fails_when_resolutions_not_fully_resolved(
        self,
        mock_load_config,
        mock_validate_preconditions,
        mock_init_logger,
        mock_dispatch,
        mock_emit_summary,
    ) -> None:
        """CLI resume rejects unresolved resolutions.yaml."""
        _ = mock_validate_preconditions, mock_init_logger, mock_emit_summary
        mock_load_config.return_value = self.config_data
        mock_dispatch.return_value = {"status": "completed"}

        run_id = "run-unresolved"
        run_dir = self._write_run_meta(run_id)
        self._write_resolutions_yaml(run_dir, chosen_option_id=None)

        with self.assertRaises(ValueError) as ctx:
            _execute_command(
                "plan",
                config=str(self.config_path),
                project_root=str(self.tmp),
                dry_run=True,
                verbose=False,
                command_only_validation=False,
                resume_run_id=run_id,
            )

        self.assertIn("not fully resolved", str(ctx.exception))
        mock_dispatch.assert_not_called()

    @patch("cli._emit_summary")
    @patch("cli.dispatch")
    @patch("cli.init_run_logger")
    @patch("cli.validate_command_preconditions")
    @patch("cli.load_and_validate_config")
    def test_resume_passes_and_injects_resolved_decisions(
        self,
        mock_load_config,
        mock_validate_preconditions,
        mock_init_logger,
        mock_dispatch,
        mock_emit_summary,
    ) -> None:
        """CLI resume proceeds when resolutions are fully resolved."""
        _ = mock_validate_preconditions, mock_init_logger, mock_emit_summary
        mock_load_config.return_value = self.config_data
        mock_dispatch.return_value = {"status": "completed"}

        run_id = "run-resolved"
        run_dir = self._write_run_meta(run_id)
        self._write_resolutions_yaml(run_dir, chosen_option_id="opt_a")

        _execute_command(
            "plan",
            config=str(self.config_path),
            project_root=str(self.tmp),
            dry_run=True,
            verbose=False,
            command_only_validation=False,
            resume_run_id=run_id,
        )

        self.assertTrue(mock_dispatch.called)
        router_ctx = mock_dispatch.call_args.args[2]
        self.assertEqual(router_ctx.resume_run_id, run_id)
        self.assertIsNotNone(router_ctx.resolved_decisions)
        self.assertIn("Resolved Decisions", router_ctx.resolved_decisions or "")

    @patch("cli._emit_summary")
    @patch("cli.dispatch")
    @patch("cli.init_run_logger")
    @patch("cli.validate_command_preconditions")
    @patch("cli.load_and_validate_config")
    @patch("cli.typer.secho")
    def test_resume_passes_for_validation_edit_spec_with_manual_edit(
        self,
        mock_secho,
        mock_load_config,
        mock_validate_preconditions,
        mock_init_logger,
        mock_dispatch,
        mock_emit_summary,
    ) -> None:
        """CLI resume accepts validation edit-spec items when manual_edit_text is set."""
        _ = mock_validate_preconditions, mock_init_logger, mock_emit_summary
        mock_load_config.return_value = self.config_data
        mock_dispatch.return_value = {"status": "completed"}

        run_id = "run-edit-spec-ack"
        run_dir = self._write_run_meta(run_id, blocked_at_stage="contract_field_consistency")
        self._write_validation_edit_spec_resolutions_yaml(run_dir, manual_edit=True)

        _execute_command(
            "plan",
            config=str(self.config_path),
            project_root=str(self.tmp),
            dry_run=True,
            verbose=False,
            command_only_validation=False,
            resume_run_id=run_id,
        )

        self.assertTrue(mock_dispatch.called)
        self.assertTrue(mock_secho.called)
        warning = mock_secho.call_args.args[0] if mock_secho.call_args and mock_secho.call_args.args else ""
        self.assertIn("manual spec edits", warning)


if __name__ == "__main__":
    unittest.main()
