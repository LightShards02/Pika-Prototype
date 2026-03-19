"""Tests for handlers.plan manual-resolution persistence and resume template vars."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.context import RuntimeContext
from handlers.plan import _build_template_vars, run_plan


class PlanHandlerTests(unittest.TestCase):
    """Tests for run_plan behavior."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="plan-handler-"))
        self.srs = self.tmp / "srs.md"
        self.srs.write_text("# SRS\n", encoding="utf-8")
        (self.tmp / "PROJECT_CONTEXT.md").write_text(
            "## Purpose\nx\n\n## Overview\nx\n\n## Workflow\nx\n",
            encoding="utf-8",
        )
        self.config = {
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
                    "prompt_name": "project_designer",
                    "inputs": {
                        "srs_path": str(self.srs),
                        "codebase_dir": ".",
                        "project_context_filename": "PROJECT_CONTEXT.md",
                    },
                    "outputs": {
                        "agent_runs_dir": {"path": "out/agent_runs", "no_overwrite": False},
                        "agent_artifacts_dir": {"path": "out/agent_artifacts", "no_overwrite": False},
                    },
                }
            },
        }

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    @patch("handlers.plan.invoke_agent_with_schema_retry")
    def test_run_plan_blocked_writes_run_scoped_resolution_artifacts(self, mock_invoke) -> None:
        """Blocked plan run writes stage JSON and resolutions.yaml under run directory."""
        mock_invoke.return_value = {
            "manual_resolution_items": [
                {
                    "item_id": "MR-PLAN-1",
                    "title": "Clarify requirement",
                    "question": "Which option should be used?",
                    "options": [{"option_id": "opt_a", "label": "A", "effect": "Use A"}],
                    "required": True,
                    "blocking_reason": "Ambiguous spec",
                }
            ]
        }
        ctx = RuntimeContext(
            command="plan",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-plan-block-1",
            project_root=str(self.tmp),
            config_path=str(self.tmp / "config.yaml"),
        )

        result = run_plan(self.config, ctx)
        self.assertEqual(result["status"], "blocked")
        run_dir = self.tmp / "out" / "agent_runs" / "plan" / "run-plan-block-1"
        self.assertTrue((run_dir / "manual_resolution" / "plan.json").exists())
        self.assertTrue((run_dir / "manual_resolution" / "resolutions.yaml").exists())
        run_meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(run_meta.get("blocked_at_stage"), "plan")
        self.assertEqual(run_meta.get("resolution_status"), "pending")

    def test_build_template_vars_include_run_scoped_resolution_path_and_decisions(self) -> None:
        """plan template vars include run-scoped resolutions.yaml and resolved_decisions."""
        ctx = RuntimeContext(
            command="plan",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-plan-vars-1",
            project_root=str(self.tmp),
            config_path=str(self.tmp / "config.yaml"),
            resolved_decisions="## Resolved Decisions\n\n- [MR-1] Use A",
        )
        vars_ = _build_template_vars(
            self.config,
            self.tmp,
            ctx,
            {"srs_content": "# SRS"},
        )
        path = Path(vars_["manual_resolution_file"])
        self.assertEqual(path.name, "resolutions.yaml")
        self.assertIn("run-plan-vars-1", path.parts)
        self.assertIn("manual_resolution", path.parts)
        self.assertEqual(vars_["resolved_decisions"], "## Resolved Decisions\n\n- [MR-1] Use A")


if __name__ == "__main__":
    unittest.main()

