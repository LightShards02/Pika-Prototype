"""Tests for handlers.resolve_plan manual-resolution persistence and resume vars."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.context import RuntimeContext
from handlers.resolve_plan import run_resolve_plan


class ResolvePlanHandlerTests(unittest.TestCase):
    """Tests for resolve_plan handler behavior."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="resolve-plan-handler-"))
        self.issue = self.tmp / "issue_tracking.csv"
        self.issue.write_text("issue_id,title\nI1,Example\n", encoding="utf-8")
        self.design = self.tmp / "design_spec.csv"
        self.design.write_text("spec_id,title,requirement\nA1,Example,Do X\n", encoding="utf-8")
        self.config = {
            "project": {
                "name": "test",
                "root_dir": ".",
                "state": {
                    "design_spec_path": str(self.design),
                    "id_registry_path": str(self.tmp / "out" / "state" / "id_registry.json"),
                    "sads_id_mapping_path": str(self.tmp / "out" / "state" / "sads_id_mapping.json"),
                },
            },

            "commands": {
                "resolve_plan": {
                    "enabled": True,
                    "inputs": {
                        "issue_tracking_path": str(self.issue),
                        "design_spec_path": str(self.design),
                    },
                    "outputs": {
                        "agent_runs_dir": {"path": "out/agent_runs", "no_overwrite": False},
                    },
                }
            },
        }

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    @patch("handlers.resolve_plan.invoke_agent_with_schema_retry")
    def test_blocked_run_writes_run_scoped_resolution_artifacts(self, mock_invoke) -> None:
        """Blocked resolve_plan run writes stage JSON and resolutions.yaml under run directory."""
        mock_invoke.return_value = {
            "manual_resolution_items": [
                {
                    "item_id": "MR-RP-1",
                    "title": "Ambiguous issue mapping",
                    "question": "Which spec should issue I1 map to?",
                    "options": [{"option_id": "opt_a", "label": "A1", "effect": "Map to A1"}],
                    "required": True,
                    "blocking_reason": "Insufficient context",
                }
            ]
        }
        ctx = RuntimeContext(
            command="resolve_plan",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-rp-block-1",
            project_root=str(self.tmp),
            config_path=str(self.tmp / "config.yaml"),
            resolved_decisions="## Resolved Decisions\n\n- [MR-0] Previous choice",
        )

        result = run_resolve_plan(self.config, ctx)
        self.assertEqual(result["status"], "blocked")
        run_dir = self.tmp / "out" / "agent_runs" / "resolve_plan" / "run-rp-block-1"
        self.assertTrue((run_dir / "manual_resolution" / "resolve_plan.json").exists())
        self.assertTrue((run_dir / "manual_resolution" / "resolutions.yaml").exists())
        run_meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(run_meta.get("blocked_at_stage"), "resolve_plan")
        self.assertEqual(run_meta.get("resolution_status"), "pending")

        call_vars = mock_invoke.call_args.kwargs["template_vars"]
        self.assertIn("manual_resolution_file", call_vars)
        self.assertIn("run_summary_file", call_vars)
        self.assertIn("resolved_decisions", call_vars)
        self.assertIn("manual_resolution", call_vars["manual_resolution_file"])
        self.assertTrue(call_vars["manual_resolution_file"].endswith("resolutions.yaml"))


if __name__ == "__main__":
    unittest.main()

