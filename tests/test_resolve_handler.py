"""Tests for handlers.resolve (interactive manual resolution)."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from core.context import RuntimeContext
from handlers.resolve import run_resolve


class ResolveHandlerTests(unittest.TestCase):
    """Tests for run_resolve."""

    def test_fails_when_run_id_missing(self) -> None:
        """Returns failed when run_id is not provided."""
        ctx = RuntimeContext(
            command="resolve",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="",
            project_root="/tmp",
            config_path="/tmp/config.yaml",
            input_overrides={},
        )
        config = {}
        result = run_resolve(config, ctx)
        self.assertEqual(result["status"], "failed")
        self.assertIn("run_id", result["reason"])

    def test_fails_when_no_blocked_run_found(self) -> None:
        """Returns failed when no blocked run exists for run_id."""
        with tempfile.TemporaryDirectory() as tmp:
            ctx = RuntimeContext(
                command="resolve",
                dry_run=False,
                verbose=False,
                command_only_validation=False,
                run_id="nonexistent-run-123",
                project_root=tmp,
                config_path=str(Path(tmp) / "config.yaml"),
                input_overrides={"run_id": "nonexistent-run-123"},
            )
            config = {
                "project": {"root_dir": "."},
                "commands": {
                    "implement": {
                        "outputs": {"agent_runs_dir": {"path": "out/agent_runs"}},
                    },
                },
            }
            result = run_resolve(config, ctx)
            self.assertEqual(result["status"], "failed")
            self.assertIn("No blocked run", result["reason"])

    def test_edit_spec_item_resolves_with_done_ack(self) -> None:
        """Validation edit-spec items are acknowledged via DONE input."""
        with tempfile.TemporaryDirectory() as tmp:
            run_id = "run-edit-spec-123"
            run_dir = Path(tmp) / "out" / "agent_runs" / "implement" / run_id
            manual_dir = run_dir / "manual_resolution"
            manual_dir.mkdir(parents=True, exist_ok=True)

            (run_dir / "run_meta.json").write_text(
                json.dumps(
                    {
                        "command": "implement",
                        "run_id": run_id,
                        "blocked_at_stage": "contract_field_consistency",
                        "completed_stages": ["load", "catalog", "unified_planner"],
                        "resolution_status": "pending",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            (manual_dir / "resolutions.yaml").write_text(
                yaml.dump(
                    {
                        "run_id": run_id,
                        "command": "implement",
                        "blocked_at_stage": "contract_field_consistency",
                        "generated_at": "2026-03-06T12:00:00",
                        "items": [
                            {
                                "item_id": "field_mismatch_c1_A1_date_range",
                                "source": "validation",
                                "required": True,
                                "question": "Edit spec A1 to align contract fields.",
                                "resolution_mode": "edit_spec",
                                "options": [],
                                "chosen_option_id": None,
                                "manual_edit_text": None,
                                "manual_edit_spec_id": None,
                                "manual_edit_field": None,
                                "spec_id": "A1",
                                "spec_amendment_hints": [
                                    {
                                        "spec_id": "A1",
                                        "field": "requirement",
                                        "suggestion": "Replace date_range with date_range_start/date_range_end",
                                        "confidence": 1.0,
                                    },
                                ],
                            },
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            ctx = RuntimeContext(
                command="resolve",
                dry_run=False,
                verbose=False,
                command_only_validation=False,
                run_id=run_id,
                project_root=tmp,
                config_path=str(Path(tmp) / "config.yaml"),
                input_overrides={"run_id": run_id},
            )
            config = {
                "project": {"root_dir": "."},
                "commands": {
                    "implement": {
                        "outputs": {"agent_runs_dir": {"path": "out/agent_runs"}},
                    },
                },
            }

            fake_in = io.StringIO("M\nUpdated requirement text\n")
            fake_out = io.StringIO()
            with patch("sys.stdin", fake_in), patch("sys.stdout", fake_out):
                result = run_resolve(config, ctx)

            self.assertEqual(result["status"], "completed")
            out_text = fake_out.getvalue()
            self.assertIn("Edit spec A1", out_text)
            self.assertIn("Hints", out_text)
            self.assertIn("M (manual edit)", out_text)

            loaded = yaml.safe_load((manual_dir / "resolutions.yaml").read_text(encoding="utf-8"))
            item = loaded["items"][0]
            self.assertEqual(item.get("manual_edit_text"), "Updated requirement text")
            self.assertEqual(item.get("manual_edit_spec_id"), "A1")

    def test_quit_on_edit_spec_item_returns_quit_status(self) -> None:
        """Typing Q on a non-agent edit-spec item quits and returns status 'quit'."""
        with tempfile.TemporaryDirectory() as tmp:
            run_id = "run-quit-edit-spec-123"
            run_dir = Path(tmp) / "out" / "agent_runs" / "implement" / run_id
            manual_dir = run_dir / "manual_resolution"
            manual_dir.mkdir(parents=True, exist_ok=True)

            run_meta_path = run_dir / "run_meta.json"
            run_meta_path.write_text(
                json.dumps(
                    {
                        "command": "implement",
                        "run_id": run_id,
                        "blocked_at_stage": "contract_field_consistency",
                        "resolution_status": "pending",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            (manual_dir / "resolutions.yaml").write_text(
                yaml.dump(
                    {
                        "run_id": run_id,
                        "command": "implement",
                        "blocked_at_stage": "contract_field_consistency",
                        "items": [
                            {
                                "item_id": "field_mismatch_c1_A1",
                                "source": "validation",
                                "resolution_mode": "edit_spec",
                                "options": [],
                                "question": "Edit spec A1.",
                            },
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            ctx = RuntimeContext(
                command="resolve",
                dry_run=False,
                verbose=False,
                command_only_validation=False,
                run_id=run_id,
                project_root=tmp,
                config_path=str(Path(tmp) / "config.yaml"),
                input_overrides={"run_id": run_id},
            )
            config = {
                "project": {"root_dir": "."},
                "commands": {
                    "implement": {
                        "outputs": {"agent_runs_dir": {"path": "out/agent_runs"}},
                    },
                },
            }

            fake_in = io.StringIO("Q\n")
            fake_out = io.StringIO()
            with patch("sys.stdin", fake_in), patch("sys.stdout", fake_out):
                result = run_resolve(config, ctx)

            self.assertEqual(result["status"], "quit")
            self.assertEqual(result["command"], "resolve")
            self.assertIn("quit", result.get("reason", ""))
            self.assertEqual(result["run_id"], run_id)

            run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
            self.assertEqual(run_meta.get("resolution_status"), "pending")

            out_text = fake_out.getvalue()
            self.assertIn("Q quit", out_text)

    def test_quit_on_agent_item_returns_quit_status(self) -> None:
        """Typing Q on an agent item with options quits and returns status 'quit'."""
        with tempfile.TemporaryDirectory() as tmp:
            run_id = "run-quit-agent-456"
            run_dir = Path(tmp) / "out" / "agent_runs" / "implement" / run_id
            manual_dir = run_dir / "manual_resolution"
            manual_dir.mkdir(parents=True, exist_ok=True)

            (run_dir / "run_meta.json").write_text(
                json.dumps(
                    {"command": "implement", "run_id": run_id, "resolution_status": "pending"},
                    indent=2,
                ),
                encoding="utf-8",
            )
            (manual_dir / "resolutions.yaml").write_text(
                yaml.dump(
                    {
                        "run_id": run_id,
                        "command": "implement",
                        "items": [
                            {
                                "item_id": "agent-choice-1",
                                "source": "agent",
                                "question": "Choose an option.",
                                "options": [
                                    {"option_id": "opt_a", "label": "Option A"},
                                    {"option_id": "opt_b", "label": "Option B"},
                                ],
                            },
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            ctx = RuntimeContext(
                command="resolve",
                dry_run=False,
                verbose=False,
                command_only_validation=False,
                run_id=run_id,
                project_root=tmp,
                config_path=str(Path(tmp) / "config.yaml"),
                input_overrides={"run_id": run_id},
            )
            config = {
                "project": {"root_dir": "."},
                "commands": {
                    "implement": {
                        "outputs": {"agent_runs_dir": {"path": "out/agent_runs"}},
                    },
                },
            }

            fake_in = io.StringIO("Q\n")
            fake_out = io.StringIO()
            with patch("sys.stdin", fake_in), patch("sys.stdout", fake_out):
                result = run_resolve(config, ctx)

            self.assertEqual(result["status"], "quit")
            self.assertEqual(result["command"], "resolve")
            self.assertIn("quit", result.get("reason", ""))

            out_text = fake_out.getvalue()
            self.assertIn("Q quit", out_text)
            # Agent items without let_agent_edit still show O option
            self.assertIn("O", out_text)

    def test_quit_lowercase_accepted(self) -> None:
        """Lowercase 'q' is accepted as quit (input is case-insensitive)."""
        with tempfile.TemporaryDirectory() as tmp:
            run_id = "run-quit-lower-789"
            run_dir = Path(tmp) / "out" / "agent_runs" / "implement" / run_id
            manual_dir = run_dir / "manual_resolution"
            manual_dir.mkdir(parents=True, exist_ok=True)

            (run_dir / "run_meta.json").write_text(
                json.dumps({"command": "implement", "run_id": run_id}, indent=2),
                encoding="utf-8",
            )
            (manual_dir / "resolutions.yaml").write_text(
                yaml.dump(
                    {
                        "run_id": run_id,
                        "command": "implement",
                        "items": [
                            {
                                "item_id": "item1",
                                "source": "validation",
                                "resolution_mode": "edit_spec",
                                "options": [],
                                "question": "Edit spec.",
                            },
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            ctx = RuntimeContext(
                command="resolve",
                dry_run=False,
                verbose=False,
                command_only_validation=False,
                run_id=run_id,
                project_root=tmp,
                config_path=str(Path(tmp) / "config.yaml"),
                input_overrides={"run_id": run_id},
            )
            config = {
                "project": {"root_dir": "."},
                "commands": {
                    "implement": {
                        "outputs": {"agent_runs_dir": {"path": "out/agent_runs"}},
                    },
                },
            }

            fake_in = io.StringIO("q\n")
            fake_out = io.StringIO()
            with patch("sys.stdin", fake_in), patch("sys.stdout", fake_out):
                result = run_resolve(config, ctx)

            self.assertEqual(result["status"], "quit")
