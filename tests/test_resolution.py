"""Tests for core.resolution module."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.resolution import (
    RESOLUTION_SOURCE_AGENT,
    RESOLUTION_SOURCE_VALIDATION,
    build_resolved_decisions_context,
    clear_resolution_item,
    generate_resolution_template,
    load_resolution_file,
    update_resolution_item,
    validate_resolutions,
)


class GenerateResolutionTemplateTests(unittest.TestCase):
    """Tests for generate_resolution_template."""

    def test_generates_yaml_with_items(self) -> None:
        """Template includes run metadata and items with source."""
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            items = [
                {
                    "item_id": "MR-TEST-1",
                    "title": "Test Item",
                    "question": "Choose one",
                    "options": [
                        {"option_id": "opt_a", "label": "Option A", "effect": "Effect A"},
                        {"option_id": "opt_b", "label": "Option B", "effect": "Effect B"},
                    ],
                    "required": True,
                    "blocking_reason": "Test block",
                },
            ]
            path = generate_resolution_template(
                run_dir=run_dir,
                stage="unified_planner",
                items=items,
                command="implement",
                run_id="run-001",
                source=RESOLUTION_SOURCE_AGENT,
            )
            self.assertTrue(path.exists())
            self.assertEqual(path.name, "resolutions.yaml")
            self.assertTrue((run_dir / "manual_resolution" / "resolutions.yaml").exists())

    def test_agent_items_have_free_text_field(self) -> None:
        """Agent source items get free_text field."""
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            items = [{"item_id": "MR-1", "title": "T", "question": "Q", "options": [], "required": True}]
            generate_resolution_template(
                run_dir=run_dir,
                stage="test",
                items=items,
                command="implement",
                run_id="r1",
                source=RESOLUTION_SOURCE_AGENT,
            )
            data = load_resolution_file(run_dir)
            self.assertIsNotNone(data)
            self.assertIn("free_text", data["items"][0])


class LoadResolutionFileTests(unittest.TestCase):
    """Tests for load_resolution_file."""

    def test_returns_none_when_missing(self) -> None:
        """Returns None when file does not exist."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(load_resolution_file(Path(tmp)))


class ValidateResolutionsTests(unittest.TestCase):
    """Tests for validate_resolutions."""

    def test_valid_when_all_required_have_chosen_option(self) -> None:
        """Validation passes when required items have chosen_option_id."""
        template = {
            "items": [
                {
                    "item_id": "MR-1",
                    "required": True,
                    "source": RESOLUTION_SOURCE_VALIDATION,
                    "chosen_option_id": "opt_a",
                    "options": [{"option_id": "opt_a", "label": "A"}],
                },
            ],
        }
        valid, errors = validate_resolutions(template)
        self.assertTrue(valid)
        self.assertEqual(errors, [])

    def test_invalid_when_required_missing_chosen(self) -> None:
        """Validation fails when required item has no chosen_option_id."""
        template = {
            "items": [
                {
                    "item_id": "MR-1",
                    "required": True,
                    "source": RESOLUTION_SOURCE_VALIDATION,
                    "chosen_option_id": None,
                    "options": [{"option_id": "opt_a", "label": "A"}],
                },
            ],
        }
        valid, errors = validate_resolutions(template)
        self.assertFalse(valid)
        self.assertIn("MR-1", errors[0])

    def test_validation_edit_spec_requires_acknowledged(self) -> None:
        """Validation edit_spec items require acknowledged=true."""
        template = {
            "items": [
                {
                    "item_id": "MR-EDIT-1",
                    "required": True,
                    "source": RESOLUTION_SOURCE_VALIDATION,
                    "resolution_mode": "edit_spec",
                    "options": [],
                    "chosen_option_id": None,
                    "manual_edit_text": None,
                },
            ],
        }
        valid, errors = validate_resolutions(template)
        self.assertFalse(valid)
        self.assertIn("manual_edit", errors[0])

    def test_validation_edit_spec_accepts_manual_edit(self) -> None:
        """Validation edit_spec items pass when manual_edit_text is set."""
        template = {
            "items": [
                {
                    "item_id": "MR-EDIT-1",
                    "required": True,
                    "source": RESOLUTION_SOURCE_VALIDATION,
                    "resolution_mode": "edit_spec",
                    "options": [],
                    "chosen_option_id": None,
                    "manual_edit_text": "Updated requirement text",
                },
            ],
        }
        valid, errors = validate_resolutions(template)
        self.assertTrue(valid)
        self.assertEqual(errors, [])

    def test_agent_item_accepts_free_text(self) -> None:
        """Agent items can use free_text instead of chosen_option_id."""
        template = {
            "items": [
                {
                    "item_id": "MR-1",
                    "required": True,
                    "source": RESOLUTION_SOURCE_AGENT,
                    "chosen_option_id": None,
                    "free_text": "Custom resolution",
                    "options": [],
                },
            ],
        }
        valid, errors = validate_resolutions(template)
        self.assertTrue(valid)


class BuildResolvedDecisionsContextTests(unittest.TestCase):
    """Tests for build_resolved_decisions_context."""

    def test_formats_chosen_option(self) -> None:
        """Uses option label when chosen_option_id is set."""
        resolutions = {
            "items": [
                {
                    "item_id": "MR-1",
                    "chosen_option_id": "opt_a",
                    "free_text": None,
                    "options": [
                        {"option_id": "opt_a", "label": "Use date_range_start/end", "effect": "Aligns to A1057"},
                    ],
                },
            ],
        }
        ctx = build_resolved_decisions_context(resolutions)
        self.assertIn("MR-1", ctx)
        self.assertIn("date_range_start/end", ctx)
        self.assertIn("Aligns to A1057", ctx)

    def test_formats_free_text(self) -> None:
        """Uses free_text when non-empty."""
        resolutions = {
            "items": [
                {
                    "item_id": "MR-1",
                    "chosen_option_id": None,
                    "free_text": "Custom answer",
                    "options": [],
                },
            ],
        }
        ctx = build_resolved_decisions_context(resolutions)
        self.assertIn("MR-1", ctx)
        self.assertIn("Custom answer", ctx)


class UpdateResolutionItemTests(unittest.TestCase):
    """Tests for update_resolution_item."""

    def test_updates_chosen_option(self) -> None:
        """update_resolution_item sets chosen_option_id."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resolutions.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
            import yaml
            data = {
                "run_id": "r1",
                "items": [
                    {"item_id": "MR-1", "chosen_option_id": None, "options": [{"option_id": "opt_a", "label": "A"}]},
                ],
            }
            path.write_text(yaml.dump(data), encoding="utf-8")
            update_resolution_item(path, 0, "opt_a", None)
            loaded = yaml.safe_load(path.read_text())
            self.assertEqual(loaded["items"][0]["chosen_option_id"], "opt_a")

    def test_updates_manual_edit_for_edit_spec_item(self) -> None:
        """update_resolution_item can set manual_edit_text for edit-spec items."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resolutions.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
            import yaml

            data = {
                "run_id": "r1",
                "items": [
                    {
                        "item_id": "MR-EDIT-1",
                        "source": RESOLUTION_SOURCE_VALIDATION,
                        "resolution_mode": "edit_spec",
                        "options": [],
                        "chosen_option_id": None,
                        "manual_edit_text": None,
                        "manual_edit_spec_id": None,
                        "manual_edit_field": None,
                    },
                ],
            }
            path.write_text(yaml.dump(data), encoding="utf-8")
            update_resolution_item(
                path, 0, None, None,
                manual_edit_text="Fixed requirement",
                manual_edit_spec_id="SPEC-001",
                manual_edit_field="requirement",
            )
            loaded = yaml.safe_load(path.read_text())
            self.assertEqual(loaded["items"][0]["manual_edit_text"], "Fixed requirement")
            self.assertEqual(loaded["items"][0]["manual_edit_spec_id"], "SPEC-001")
            self.assertEqual(loaded["items"][0]["chosen_option_id"], "manual_edit")

            clear_resolution_item(path, 0)
            loaded = yaml.safe_load(path.read_text())
            self.assertIsNone(loaded["items"][0]["manual_edit_text"])
