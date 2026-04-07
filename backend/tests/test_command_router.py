from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from core.command_router import dispatch
from core.contracts import get_design_spec_required_columns
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
        """Test that dispatch format raises when inputs not configured (no fallback)."""
        with self.assertRaises(ValueError) as ctx:
            dispatch("format", {}, self._make_ctx("format"))
        self.assertIn("Format command requires input", str(ctx.exception))

    def test_dispatch_format_returns_completed_with_valid_inputs(self) -> None:
        """Test that dispatch format returns completed when inputs exist."""
        root = Path(__file__).parent / "test_data_format_dispatch"
        root.mkdir(parents=True, exist_ok=True)
        csv_file = root / "design_spec.csv"
        csv_file.write_text("spec_id,title,requirement\nA1,Test,Do something\n", encoding="utf-8")
        try:
            config = {
                "project": {
                    "name": "test",
                    "root_dir": ".",
                    "state": {
                        "design_spec_path": "out/state/DESIGN-SPEC.csv",
                        "id_registry_path": "out/state/id_registry.json",
                        "sads_id_mapping_path": "out/state/sads_id_mapping.json",
                    },
                },
                "commands": {
                    "format": {
                        "enabled": True,
                        "deterministic": True,
                        "copy_before_write": True,
                        "inputs": {"design_spec_path": str(csv_file.relative_to(root))},
                        "outputs": {
                            "design_spec_path": {"path": "out/state/DESIGN-SPEC.csv", "no_overwrite": False},
                            "backups_dir": {"path": "out/backups", "no_overwrite": False},
                        },
                    },
                },
                "id_generation": {"id_registry": "out/state/id_registry.json"},
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
        """Format writes to commands.format.outputs.design_spec_path and backups go to backups_dir/format/."""
        root = Path(__file__).parent / "test_data_format_output"
        root.mkdir(parents=True, exist_ok=True)
        csv_file = root / "MySpec.csv"
        design_spec_path = root / "out" / "state" / "DESIGN-SPEC.csv"
        backups_dir = root / "out" / "backups"
        try:
            csv_file.write_text(
                "spec_id,title,requirement\nA1,Test,Do something\n", encoding="utf-8"
            )
            config = {
                "project": {
                    "name": "test",
                    "root_dir": ".",
                    "state": {
                        "design_spec_path": str(design_spec_path),
                        "id_registry_path": str(root / "out" / "state" / "id_registry.json"),
                        "sads_id_mapping_path": str(root / "out" / "state" / "sads_id_mapping.json"),
                    },
                },
                "commands": {
                    "format": {
                        "enabled": True,
                        "deterministic": True,
                        "copy_before_write": True,
                        "inputs": {"design_spec_path": str(csv_file)},
                        "outputs": {
                            "design_spec_path": {"path": str(design_spec_path), "no_overwrite": False},
                            "backups_dir": {"path": str(backups_dir), "no_overwrite": False},
                        },
                    },
                },
                "id_generation": {"id_registry": str(root / "state" / "id_registry.json")},
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
            self.assertTrue(design_spec_path.exists(), f"Expected {design_spec_path} to exist")
            # Second run: backup should go to backups_dir/format/
            result2 = dispatch("format", config, ctx)
            self.assertEqual(result2["status"], "completed")
            format_backups = backups_dir / "format"
            self.assertTrue(format_backups.is_dir(), f"Expected {format_backups} to exist")
            backups_list = list(format_backups.glob("DESIGN-SPEC_*.csv"))
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
                "project": {
                    "name": "test",
                    "root_dir": ".",
                    "state": {
                        "design_spec_path": str(csv_file),
                        "id_registry_path": str(root / "out" / "state" / "id_registry.json"),
                        "sads_id_mapping_path": str(root / "out" / "state" / "sads_id_mapping.json"),
                    },
                },
                "commands": {
                    "map": {
                        "enabled": True,

                        "inputs": {
                            "design_spec_path": str(csv_file),
                            "codebase_dir": ".",
                            "project_context_filename": "PROJECT_CONTEXT.md",
                        },
                        "outputs": {
                            "backups_dir": {"path": str(root / "out" / "backups"), "no_overwrite": False},
                        },
                    },
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
                "project": {
                    "name": "test",
                    "root_dir": ".",
                    "state": {
                        "design_spec_path": str(csv_file),
                        "id_registry_path": str(root / "out" / "state" / "id_registry.json"),
                        "sads_id_mapping_path": str(root / "out" / "state" / "sads_id_mapping.json"),
                    },
                },
                "commands": {
                    "map": {
                        "enabled": True,

                        "inputs": {
                            "design_spec_path": str(csv_file),
                            "codebase_dir": ".",
                            "project_context_filename": "PROJECT_CONTEXT.md",
                        },
                        "outputs": {
                            "backups_dir": {"path": str(root / "out" / "backups"), "no_overwrite": False},
                        },
                    },
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
                "project": {
                    "name": "test",
                    "root_dir": ".",
                    "state": {
                        "design_spec_path": "out/state/DESIGN-SPEC.csv",
                        "id_registry_path": "out/state/id_registry.json",
                        "sads_id_mapping_path": "out/state/sads_id_mapping.json",
                    },
                },
                "commands": {
                    "plan": {
                        "enabled": True,

                        "inputs": {
                            "srs_path": str(srs_file),
                            "project_context_filename": "PROJECT_CONTEXT.md",
                        },
                        "outputs": {"agent_runs_dir": {"path": str(out_dir), "no_overwrite": False}},
                    },
                },

            }
            result = dispatch(
                "plan",
                config,
                self._make_ctx("plan", project_root=str(root), dry_run=False),
            )
            self.assertEqual(result["command"], "plan")
            self.assertEqual(result["status"], "completed")
            # Outputs go to out/agent_runs/plan/
            plan_dir = out_dir / "plan"
            milestones = plan_dir / "plan_milestones.json"
            sads_csv = plan_dir / "plan_proposed_sads.csv"
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
                "project": {
                    "name": "test",
                    "root_dir": ".",
                    "state": {
                        "design_spec_path": str(csv_file),
                        "id_registry_path": str(root / "out" / "state" / "id_registry.json"),
                        "sads_id_mapping_path": str(root / "out" / "state" / "sads_id_mapping.json"),
                    },
                },
                "commands": {
                    "map": {
                        "enabled": True,

                        "inputs": {
                            "design_spec_path": str(csv_file),
                            "codebase_dir": ".",
                            "project_context_filename": "PROJECT_CONTEXT.md",
                        },
                        "outputs": {
                            "backups_dir": {"path": str(root / "out" / "backups"), "no_overwrite": False},
                            "logs_dir": {"path": str(root / "out" / "logs"), "no_overwrite": False},
                        },
                    },
                },
            }
            ctx = self._make_ctx("map", project_root=str(root))
            with self.assertRaises(SafetyPreconditionError) as exc_ctx:
                validate_command_preconditions("map", config, ctx)
            msg = str(exc_ctx.exception)
            self.assertIn("Missing required columns", msg)
            self.assertIn("requirement", msg)
            self.assertIn("map_status", msg)
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
                "project": {
                    "name": "test",
                    "root_dir": ".",
                    "state": {
                        "design_spec_path": str(root / "out" / "state" / "DESIGN-SPEC.csv"),
                        "id_registry_path": str(root / "out" / "state" / "id_registry.json"),
                        "sads_id_mapping_path": str(root / "out" / "state" / "sads_id_mapping.json"),
                    },
                },
                "commands": {
                    "plan": {
                        "enabled": True,

                        "inputs": {"project_context_filename": "PROJECT_CONTEXT.md"},
                        "outputs": {
                            "backups_dir": {"path": str(root / "out" / "backups"), "no_overwrite": False},
                            "logs_dir": {"path": str(root / "out" / "logs"), "no_overwrite": False},
                        },
                    },
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

    def test_preflight_refine_command_is_supported(self) -> None:
        """Preflight accepts refine for valid config/input instead of treating it as unsupported."""
        root = Path(__file__).parent / "test_data_preflight_refine"
        root.mkdir(parents=True, exist_ok=True)
        csv_file = root / "design_spec.csv"
        context_file = root / "PROJECT_CONTEXT.md"
        try:
            required = list(get_design_spec_required_columns())
            row = []
            for col in required:
                if col == "spec_id":
                    row.append("A1")
                elif col == "title":
                    row.append("Test title")
                elif col == "requirement":
                    row.append("Test requirement")
                else:
                    row.append("x")
            csv_file.write_text(
                ",".join(required) + "\n" + ",".join(row) + "\n",
                encoding="utf-8",
            )
            context_file.write_text(
                "### Purpose\nProject purpose.\n\n### Overview\nOverview.\n\n### Workflow\nWorkflow.\n",
                encoding="utf-8",
            )
            config = {
                "project": {
                    "name": "test",
                    "root_dir": ".",
                    "state": {
                        "design_spec_path": str(csv_file),
                        "id_registry_path": str(root / "out" / "state" / "id_registry.json"),
                        "sads_id_mapping_path": str(root / "out" / "state" / "sads_id_mapping.json"),
                    },
                },
                "commands": {
                    "refine": {
                        "enabled": True,
                        "inputs": {
                            "design_spec_path": str(csv_file),
                            "project_context_filename": "PROJECT_CONTEXT.md",
                        },
                        "outputs": {
                            "backups_dir": {"path": str(root / "out" / "backups"), "no_overwrite": False},
                            "logs_dir": {"path": str(root / "out" / "logs"), "no_overwrite": False},
                        },
                    },
                },
            }
            ctx = self._make_ctx("refine", project_root=str(root))
            validate_command_preconditions("refine", config, ctx)
        finally:
            if root.exists():
                shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
