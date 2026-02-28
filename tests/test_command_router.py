from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from core.command_router import dispatch
from core.context import RuntimeContext
from core.errors import SafetyPreconditionError
from core.safety import validate_command_preconditions


class CommandRouterTests(unittest.TestCase):
    """Test cases for command router."""
    def _make_ctx(
        self,
        command: str,
        project_root: str = "/tmp/project",
        dry_run: bool = True,
    ) -> RuntimeContext:
        """Create ctx."""
        return RuntimeContext(
            command=command,
            dry_run=dry_run,
            verbose=False,
            command_only_validation=False,
            run_id="run-123",
            project_root=project_root,
            config_path=f"{project_root}/config.yaml",
        )

    def test_dispatch_format_returns_skipped_when_no_inputs(self) -> None:
        """Test that dispatch format returns skipped when inputs not configured."""
        result = dispatch("format", {}, self._make_ctx("format"))
        self.assertEqual(result["command"], "format")
        self.assertEqual(result["status"], "skipped")
        self.assertIn("reason", result)

    def test_dispatch_format_returns_completed_with_valid_inputs(self) -> None:
        """Test that dispatch format returns completed when inputs exist."""
        root = Path(__file__).parent / "test_data_format_dispatch"
        root.mkdir(parents=True, exist_ok=True)
        csv_file = root / "design_spec.csv"
        csv_file.write_text("spec_id,title,requirement\nA1,Test,Do something\n", encoding="utf-8")
        try:
            config = {
                "inputs": {"design_spec_path": str(csv_file.relative_to(root))},
                "csv_contracts": {
                    "design_spec": {
                        "add_if_missing": [
                            "spec_id",
                            "module_tag",
                            "subunit",
                            "mapped_code_symbols",
                            "mapped_confidence",
                            "mapped_consistency_score",
                            "mapped_problems",
                            "index_status",
                            "assumptions",
                            "last_indexed_at",
                        ]
                    },
                    "issue_tracking": {"add_if_missing": []},
                },
            }
            result = dispatch("format", config, self._make_ctx("format", project_root=str(root)))
            self.assertEqual(result["command"], "format")
            self.assertEqual(result["status"], "completed")
        finally:
            csv_file.unlink(missing_ok=True)
            root.rmdir()

    def test_dispatch_format_writes_formatted_stem_csv_and_backup_in_format_subdir(
        self,
    ) -> None:
        """Format writes formatted_{stem}.csv and backups go to backups_dir/format/."""
        root = Path(__file__).parent / "test_data_format_output"
        root.mkdir(parents=True, exist_ok=True)
        csv_file = root / "MySpec.csv"
        normalized_dir = root / "out" / "normalized"
        backups_dir = root / "out" / "backups"
        try:
            csv_file.write_text(
                "spec_id,title,requirement\nA1,Test,Do something\n", encoding="utf-8"
            )
            config = {
                "inputs": {"design_spec_path": str(csv_file)},
                "outputs": {
                    "normalized_dir": {"path": str(normalized_dir), "no_overwrite": False},
                    "backups_dir": {"path": str(backups_dir), "no_overwrite": False},
                },
                "commands": {"format": {"copy_before_write": True}},
                "csv_contracts": {
                    "design_spec": {
                        "add_if_missing": [
                            "spec_id",
                            "module_tag",
                            "subunit",
                            "mapped_code_symbols",
                            "mapped_confidence",
                            "mapped_consistency_score",
                            "mapped_problems",
                            "index_status",
                            "assumptions",
                            "last_indexed_at",
                        ]
                    },
                    "issue_tracking": {"add_if_missing": []},
                },
                "id_generation": {"registry_path": str(root / "state" / "id_registry.json")},
            }
            ctx = self._make_ctx("format", project_root=str(root), dry_run=False)
            ctx = RuntimeContext(
                command=ctx.command,
                dry_run=ctx.dry_run,
                verbose=ctx.verbose,
                command_only_validation=ctx.command_only_validation,
                run_id="abc12345",
                project_root=ctx.project_root,
                config_path=ctx.config_path,
                input_overrides={"design_spec_path": str(csv_file)},
            )
            result = dispatch("format", config, ctx)
            self.assertEqual(result["status"], "completed")
            out_file = normalized_dir / "formatted_MySpec.csv"
            self.assertTrue(out_file.exists(), f"Expected {out_file} to exist")
            # Second run: backup should go to backups_dir/format/
            result2 = dispatch("format", config, ctx)
            self.assertEqual(result2["status"], "completed")
            format_backups = backups_dir / "format"
            self.assertTrue(format_backups.is_dir(), f"Expected {format_backups} to exist")
            backups_list = list(format_backups.glob("formatted_MySpec_*.csv"))
            self.assertGreater(len(backups_list), 0, "Expected at least one backup file")
        finally:
            if root.exists():
                shutil.rmtree(root, ignore_errors=True)

    def test_dispatch_map_returns_skipped_when_no_inputs(self) -> None:
        """Test that dispatch map returns skipped when inputs not configured."""
        result = dispatch("map", {}, self._make_ctx("map"))
        self.assertEqual(result["command"], "map")
        self.assertEqual(result["status"], "skipped")
        self.assertIn("reason", result)

    def test_dispatch_map_returns_completed_with_valid_inputs(self) -> None:
        """Test that dispatch map returns completed when inputs exist and PROJECT_CONTEXT.md in project root."""
        root = Path(__file__).parent / "test_data_map"
        root.mkdir(parents=True, exist_ok=True)
        csv_file = root / "design_spec.csv"
        context_file = root / "PROJECT_CONTEXT.md"
        try:
            csv_file.write_text(
                "spec_id,subunit,title,requirement\nA1,S1,Test,Do something\n",
                encoding="utf-8",
            )
            context_file.write_text("# Project Context\nTest context for map.\n", encoding="utf-8")
            config = {
                "inputs": {
                    "design_spec_path": str(csv_file),
                    "project_context_filename": "PROJECT_CONTEXT.md",
                },
                "csv_contracts": {
                    "design_spec": {
                        "add_if_missing": [
                            "spec_id",
                            "module_tag",
                            "subunit",
                            "mapped_code_symbols",
                            "mapped_confidence",
                            "mapped_consistency_score",
                            "mapped_problems",
                            "index_status",
                            "assumptions",
                            "last_indexed_at",
                        ]
                    },
                    "issue_tracking": {"add_if_missing": []},
                },
            }
            result = dispatch("map", config, self._make_ctx("map", project_root=str(root)))
            self.assertEqual(result["command"], "map")
            self.assertEqual(result["status"], "completed")
        finally:
            if root.exists():
                shutil.rmtree(root, ignore_errors=True)

    def test_dispatch_map_raises_when_project_context_missing(self) -> None:
        """Map raises SafetyPreconditionError when project context file not found."""
        root = Path(__file__).parent / "test_data_map_no_context"
        root.mkdir(parents=True, exist_ok=True)
        csv_file = root / "design_spec.csv"
        try:
            csv_file.write_text(
                "spec_id,subunit,title,requirement\nA1,S1,Test\n",
                encoding="utf-8",
            )
            config = {
                "inputs": {
                    "design_spec_path": str(csv_file),
                    "project_context_filename": "PROJECT_CONTEXT.md",
                },
                "csv_contracts": {
                    "design_spec": {
                        "add_if_missing": [
                            "spec_id",
                            "module_tag",
                            "subunit",
                            "mapped_code_symbols",
                            "mapped_confidence",
                            "mapped_consistency_score",
                            "mapped_problems",
                            "index_status",
                            "assumptions",
                            "last_indexed_at",
                        ]
                    },
                    "issue_tracking": {"add_if_missing": []},
                },
            }
            with self.assertRaises(SafetyPreconditionError) as ctx:
                dispatch("map", config, self._make_ctx("map", project_root=str(root)))
            self.assertIn("Project context file not found", str(ctx.exception))
            self.assertIn("--project-context", str(ctx.exception))
        finally:
            if root.exists():
                shutil.rmtree(root, ignore_errors=True)

    def test_dispatch_unknown_raises_value_error(self) -> None:
        """Test that dispatch unknown raises value error."""
        with self.assertRaises(ValueError) as ctx:
            dispatch("unknown", {}, self._make_ctx("unknown"))
        self.assertEqual(str(ctx.exception), "Unknown command: unknown")

    def test_dispatch_plan_returns_skipped_when_no_srs(self) -> None:
        """Test that dispatch plan returns skipped when srs_path not configured."""
        result = dispatch("plan", {}, self._make_ctx("plan"))
        self.assertEqual(result["command"], "plan")
        self.assertEqual(result["status"], "skipped")

    def test_dispatch_plan_returns_completed_with_valid_inputs(self) -> None:
        """Test that dispatch plan returns completed when srs_path exists and PROJECT_CONTEXT.md in root."""
        root = Path(__file__).parent / "test_data_plan"
        root.mkdir(parents=True, exist_ok=True)
        srs_file = root / "srs.md"
        context_file = root / "PROJECT_CONTEXT.md"
        out_dir = root / "out" / "agent_runs"
        try:
            srs_file.write_text("# SRS\nRequirement: do X\n", encoding="utf-8")
            context_file.write_text("# Project Context\nTest context.\n", encoding="utf-8")
            config = {
                "inputs": {
                    "srs_path": str(srs_file),
                    "project_context_filename": "PROJECT_CONTEXT.md",
                },
                "outputs": {"agent_runs_dir": {"path": str(out_dir), "no_overwrite": False}},
                "schemas": {"plan_output": "schemas/agent_outputs/plan_output.schema.json"},
                "project": {"name": "test", "root_dir": "."},
            }
            result = dispatch(
                "plan",
                config,
                self._make_ctx("plan", project_root=str(root), dry_run=False),
            )
            self.assertEqual(result["command"], "plan")
            self.assertEqual(result["status"], "completed")
            milestones = out_dir / "plan_milestones.json"
            sads_csv = out_dir / "plan_proposed_sads.csv"
            self.assertTrue(milestones.exists(), f"Expected {milestones} to exist")
            self.assertTrue(sads_csv.exists(), f"Expected {sads_csv} to exist")
        finally:
            if root.exists():
                shutil.rmtree(root, ignore_errors=True)

    def test_dispatch_resolve_plan_returns_skipped_when_no_issue_tracker(self) -> None:
        """Test that dispatch resolve_plan returns skipped when issue_tracking_path missing."""
        result = dispatch("resolve_plan", {}, self._make_ctx("resolve_plan"))
        self.assertEqual(result["command"], "resolve_plan")
        self.assertEqual(result["status"], "skipped")

    def test_preflight_csv_contract_fails_when_design_spec_missing_columns(self) -> None:
        """Preflight fails with clear error when design_spec missing required columns."""
        root = Path(__file__).parent / "test_data_preflight_csv"
        root.mkdir(parents=True, exist_ok=True)
        csv_file = root / "design_spec.csv"
        context_file = root / "PROJECT_CONTEXT.md"
        try:
            csv_file.write_text("spec_id,title\nA1,Test\n", encoding="utf-8")
            context_file.write_text(
                "### Purpose\nProject purpose.\n\n### Overview\nOverview.\n\n### Workflow\nWorkflow.\n",
                encoding="utf-8",
            )
            config = {
                "inputs": {
                    "design_spec_path": str(csv_file),
                    "project_context_filename": "PROJECT_CONTEXT.md",
                },
                "outputs": {
                    "normalized_dir": {"path": str(root / "out" / "normalized"), "no_overwrite": False},
                    "backups_dir": {"path": str(root / "out" / "backups"), "no_overwrite": False},
                    "logs_dir": {"path": str(root / "out" / "logs"), "no_overwrite": False},
                },
            }
            ctx = self._make_ctx("map", project_root=str(root))
            with self.assertRaises(SafetyPreconditionError) as exc_ctx:
                validate_command_preconditions("map", config, ctx)
            msg = str(exc_ctx.exception)
            self.assertIn("Missing required columns", msg)
            self.assertIn("requirement", msg)
            self.assertIn("index_status", msg)
        finally:
            if root.exists():
                shutil.rmtree(root, ignore_errors=True)

    def test_preflight_project_context_contract_fails_when_sections_missing(self) -> None:
        """Preflight fails when PROJECT_CONTEXT.md missing Purpose, Overview, or Workflow."""
        root = Path(__file__).parent / "test_data_preflight_context"
        root.mkdir(parents=True, exist_ok=True)
        context_file = root / "PROJECT_CONTEXT.md"
        try:
            context_file.write_text("# Project\nOnly a title, no Purpose/Overview/Workflow.\n", encoding="utf-8")
            config = {
                "inputs": {"project_context_filename": "PROJECT_CONTEXT.md"},
                "outputs": {
                    "normalized_dir": {"path": str(root / "out" / "normalized"), "no_overwrite": False},
                    "backups_dir": {"path": str(root / "out" / "backups"), "no_overwrite": False},
                    "logs_dir": {"path": str(root / "out" / "logs"), "no_overwrite": False},
                },
            }
            ctx = self._make_ctx("plan", project_root=str(root))
            with self.assertRaises(SafetyPreconditionError) as exc_ctx:
                validate_command_preconditions("plan", config, ctx)
            msg = str(exc_ctx.exception)
            self.assertIn("purpose", msg)
            self.assertIn("overview", msg)
            self.assertIn("workflow", msg)
        finally:
            if root.exists():
                shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
