"""Tests for handlers.refine — spec quality review and improvement workflow."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from core.context import RuntimeContext
from handlers.refine.config import _get_refine_cfg
from handlers.refine.decomposition import (
    _build_decomposition_items,
    _compute_pairwise_cosine,
    _compute_sentence_variance,
    run_decomposition_check,
)
from handlers.refine.impl import (
    _find_col,
    _merge_all_items,
    _validate_required_columns,
    run_refine,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_HEADERS = [
    "spec_id",
    "module_tag",
    "module_role",
    "requirement",
    "acceptance_criteria",
]

_SAMPLE_ROWS: list[dict[str, str]] = [
    {
        "spec_id": "S1",
        "module_tag": "core",
        "module_role": "domain",
        "requirement": "The system shall validate user input appropriately.",
        "acceptance_criteria": "Input is validated.",
    },
    {
        "spec_id": "S2",
        "module_tag": "core",
        "module_role": "domain",
        "requirement": "The system shall return results quickly.",
        "acceptance_criteria": "Results are returned fast.",
    },
]

_PIKA_ROOT = Path(__file__).parent.parent


def _make_ctx(tmp: str, run_id: str = "test-run") -> RuntimeContext:
    return RuntimeContext(
        command="refine",
        dry_run=False,
        verbose=False,
        command_only_validation=False,
        run_id=run_id,
        project_root=tmp,
        config_path="config/config.yaml",
        input_overrides={},
    )


def _make_config(tmp: str, design_csv_path: str | None = None) -> dict[str, Any]:
    return {
        "agent": {"provider": "stub", "schema_validation_retries": 0},
        "project": {"name": "test", "root_dir": tmp},
        "prompts": {
            "prompt_file": str(_PIKA_ROOT / "prompts" / "PROMPT.yaml"),
        },
        "commands": {
            "refine": {
                "enabled": True,
                "ambiguity_detector": {"prompt_name": "spec_ambiguity_detector"},
                "testability_auditor": {"prompt_name": "spec_testability_auditor"},
                "spec_editor": {"prompt_name": "spec_editor"},
                "decomposition": {
                    "enabled": False,
                    "blocking": False,
                    "similarity_threshold": 0.85,
                    "variance_threshold": 0.15,
                },
                "inputs": {
                    "design_spec_path": design_csv_path or "",
                    "project_context_filename": "PROJECT_CONTEXT.md",
                },
                "outputs": {
                    "root_dir": {"path": str(Path(tmp) / "out"), "no_overwrite": False},
                    "design_spec_path": {
                        "path": str(Path(tmp) / "out" / "REFINED-SPEC.csv"),
                        "no_overwrite": False,
                    },
                },
            }
        },
    }


def _write_design_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [",".join(_SAMPLE_HEADERS)]
    for row in _SAMPLE_ROWS:
        lines.append(",".join(row[h] for h in _SAMPLE_HEADERS))
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_project_context(root: Path) -> None:
    (root / "PROJECT_CONTEXT.md").write_text("# Test project context", encoding="utf-8")


def _empty_agent_output() -> dict[str, Any]:
    return {"manual_resolution_items": []}


def _ambiguity_items_output() -> dict[str, Any]:
    return {
        "manual_resolution_items": [
            {
                "item_id": "AMB-001",
                "title": "Vague requirement",
                "spec_id": "S1",
                "field": "requirement",
                "vague_phrases": ["appropriately"],
                "suggested_improvement": "The system shall validate that input length <= 255 chars.",
                "options": [
                    {"option_id": "accept_suggestion", "label": "Accept", "effect": "Apply"},
                    {"option_id": "let_agent_edit", "label": "Let agent edit", "effect": "Call spec_editor"},
                    {"option_id": "skip", "label": "Skip", "effect": "Keep original"},
                ],
            }
        ]
    }


def _testability_items_output() -> dict[str, Any]:
    return {
        "manual_resolution_items": [
            {
                "item_id": "TEST-001",
                "title": "Untestable criteria",
                "spec_id": "S2",
                "field": "acceptance_criteria",
                "untestable_reason": "Too vague to automate.",
                "suggested_improvement": "Results are returned within 200ms under normal load.",
                "suggested_test_type": "integration",
                "options": [
                    {"option_id": "accept_suggestion", "label": "Accept", "effect": "Apply"},
                    {"option_id": "let_agent_edit", "label": "Let agent edit", "effect": "Call spec_editor"},
                    {"option_id": "skip", "label": "Skip", "effect": "Keep original"},
                ],
            }
        ]
    }


# ---------------------------------------------------------------------------
# Group A: Config
# ---------------------------------------------------------------------------

class RefineConfigTests(unittest.TestCase):
    """Tests for _get_refine_cfg() defaults and overrides."""

    def test_defaults_all_returned(self) -> None:
        cfg = _get_refine_cfg({})
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["ambiguity_detector_prompt_name"], "spec_ambiguity_detector")
        self.assertEqual(cfg["testability_auditor_prompt_name"], "spec_testability_auditor")
        self.assertEqual(cfg["spec_editor_prompt_name"], "spec_editor")
        self.assertTrue(cfg["decomposition_enabled"])
        self.assertFalse(cfg["decomposition_blocking"])
        self.assertAlmostEqual(cfg["similarity_threshold"], 0.85)
        self.assertAlmostEqual(cfg["variance_threshold"], 0.15)

    def test_enabled_false(self) -> None:
        cfg = _get_refine_cfg({"commands": {"refine": {"enabled": False}}})
        self.assertFalse(cfg["enabled"])

    def test_custom_prompt_names(self) -> None:
        config = {
            "commands": {
                "refine": {
                    "ambiguity_detector": {"prompt_name": "my_ambiguity"},
                    "testability_auditor": {"prompt_name": "my_testability"},
                    "spec_editor": {"prompt_name": "my_editor"},
                }
            }
        }
        cfg = _get_refine_cfg(config)
        self.assertEqual(cfg["ambiguity_detector_prompt_name"], "my_ambiguity")
        self.assertEqual(cfg["testability_auditor_prompt_name"], "my_testability")
        self.assertEqual(cfg["spec_editor_prompt_name"], "my_editor")

    def test_decomposition_blocking_flag(self) -> None:
        config = {"commands": {"refine": {"decomposition": {"blocking": True}}}}
        cfg = _get_refine_cfg(config)
        self.assertTrue(cfg["decomposition_blocking"])

    def test_custom_thresholds(self) -> None:
        config = {
            "commands": {
                "refine": {
                    "decomposition": {
                        "similarity_threshold": 0.90,
                        "variance_threshold": 0.20,
                    }
                }
            }
        }
        cfg = _get_refine_cfg(config)
        self.assertAlmostEqual(cfg["similarity_threshold"], 0.90)
        self.assertAlmostEqual(cfg["variance_threshold"], 0.20)

    def test_thresholds_clamped_to_unit_interval(self) -> None:
        config = {
            "commands": {
                "refine": {
                    "decomposition": {
                        "similarity_threshold": 2.0,
                        "variance_threshold": -0.5,
                    }
                }
            }
        }
        cfg = _get_refine_cfg(config)
        self.assertAlmostEqual(cfg["similarity_threshold"], 1.0)
        self.assertAlmostEqual(cfg["variance_threshold"], 0.0)


# ---------------------------------------------------------------------------
# Group B: Decomposition check
# ---------------------------------------------------------------------------

class DecompositionItemBuildTests(unittest.TestCase):
    """Tests for _build_decomposition_items() — item structure and options."""

    def test_split_candidate_item_structure(self) -> None:
        flags = {
            "split_candidates": [
                {"spec_id": "S1", "reason": "High variance.", "variance": 0.22}
            ],
            "merge_candidates": [],
        }
        items = _build_decomposition_items(flags)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["item_id"], "DECOMP-SPLIT-S1")
        self.assertEqual(item["spec_id"], "S1")
        self.assertEqual(item["issue_kind"], "split_candidate")
        option_ids = {o["option_id"] for o in item["options"]}
        self.assertEqual(option_ids, {"let_agent_edit", "skip"})

    def test_merge_candidate_item_structure(self) -> None:
        flags = {
            "split_candidates": [],
            "merge_candidates": [
                {"spec_ids": ["S1", "S2"], "reason": "High sim.", "similarity": 0.91}
            ],
        }
        items = _build_decomposition_items(flags)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertIn("DECOMP-MERGE", item["item_id"])
        self.assertEqual(item["spec_ids"], ["S1", "S2"])
        self.assertEqual(item["issue_kind"], "merge_candidate")
        option_ids = {o["option_id"] for o in item["options"]}
        self.assertEqual(option_ids, {"let_agent_edit", "skip"})

    def test_no_accept_suggestion_option(self) -> None:
        """Decomposition items must NOT offer accept_suggestion."""
        flags = {
            "split_candidates": [{"spec_id": "X1", "reason": "r", "variance": 0.2}],
            "merge_candidates": [],
        }
        for item in _build_decomposition_items(flags):
            option_ids = {o["option_id"] for o in item["options"]}
            self.assertNotIn("accept_suggestion", option_ids)

    def test_empty_flags_produce_no_items(self) -> None:
        flags = {"split_candidates": [], "merge_candidates": []}
        self.assertEqual(_build_decomposition_items(flags), [])


class DecompositionCheckSkipTests(unittest.TestCase):
    """Tests for run_decomposition_check() graceful fallback."""

    def test_skips_when_sentence_transformers_absent(self) -> None:
        with patch.dict(sys.modules, {"sentence_transformers": None}):
            result = run_decomposition_check(_SAMPLE_ROWS)
        self.assertTrue(result.get("skipped"))
        self.assertEqual(result["split_candidates"], [])
        self.assertEqual(result["merge_candidates"], [])

    def test_skips_on_import_error(self) -> None:
        import builtins
        real_import = builtins.__import__

        def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "sentence_transformers":
                raise ImportError("not installed")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = run_decomposition_check(_SAMPLE_ROWS)
        self.assertTrue(result.get("skipped"))


# ---------------------------------------------------------------------------
# Group C: Column validation
# ---------------------------------------------------------------------------

class RequiredColumnValidationTests(unittest.TestCase):
    """Tests for _validate_required_columns()."""

    def test_passes_when_all_present(self) -> None:
        _validate_required_columns(
            _SAMPLE_HEADERS,
            ["spec_id", "module_tag", "module_role", "requirement", "acceptance_criteria"],
        )

    def test_case_insensitive_match(self) -> None:
        headers = ["Spec_ID", "Module_Tag", "Module_Role", "Requirement", "Acceptance_Criteria"]
        _validate_required_columns(
            headers,
            ["spec_id", "module_tag", "module_role", "requirement", "acceptance_criteria"],
        )

    def test_raises_on_missing_column(self) -> None:
        headers = ["spec_id", "module_tag", "module_role"]
        with self.assertRaises(ValueError) as cm:
            _validate_required_columns(
                headers,
                ["spec_id", "module_tag", "module_role", "requirement", "acceptance_criteria"],
            )
        self.assertIn("requirement", str(cm.exception).lower())

    def test_error_message_lists_all_missing(self) -> None:
        with self.assertRaises(ValueError) as cm:
            _validate_required_columns([], ["spec_id", "requirement"])
        msg = str(cm.exception)
        self.assertIn("spec_id", msg)
        self.assertIn("requirement", msg)


# ---------------------------------------------------------------------------
# Group D: Item merging
# ---------------------------------------------------------------------------

class MergeAllItemsTests(unittest.TestCase):
    """Tests for _merge_all_items()."""

    def test_combines_all_sources(self) -> None:
        d = [{"item_id": "D1"}]
        a = [{"item_id": "A1"}]
        t = [{"item_id": "T1"}]
        result = _merge_all_items(d, a, t)
        self.assertEqual(len(result), 3)
        self.assertEqual([r["item_id"] for r in result], ["D1", "A1", "T1"])

    def test_all_empty_returns_empty(self) -> None:
        self.assertEqual(_merge_all_items([], [], []), [])

    def test_preserves_order_decomp_ambiguity_testability(self) -> None:
        decomp = [{"item_id": "decomp"}]
        ambiguity = [{"item_id": "amb"}]
        testability = [{"item_id": "test"}]
        result = _merge_all_items(decomp, ambiguity, testability)
        self.assertEqual(result[0]["item_id"], "decomp")
        self.assertEqual(result[1]["item_id"], "amb")
        self.assertEqual(result[2]["item_id"], "test")

    def test_partial_sources_combined(self) -> None:
        result = _merge_all_items([], [{"item_id": "A"}], [])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["item_id"], "A")


# ---------------------------------------------------------------------------
# Group E: run_refine integration (stub/mocked agents)
# ---------------------------------------------------------------------------

class RunRefineIntegrationTests(unittest.TestCase):
    """Integration tests for run_refine() using mocked agent calls."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.design_csv = Path(self.tmp) / "DESIGN-SPEC.csv"
        _write_design_csv(self.design_csv)
        _write_project_context(Path(self.tmp))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _config(self, **overrides: Any) -> dict[str, Any]:
        cfg = _make_config(self.tmp, str(self.design_csv))
        for k, v in overrides.items():
            cfg[k] = v
        return cfg

    def _ctx(self, run_id: str = "test-run") -> RuntimeContext:
        return _make_ctx(self.tmp, run_id)

    def _mock_both_agents(self, ambiguity_output: dict, testability_output: dict):
        """Context manager that mocks both parallel agent calls."""
        call_count: list[int] = [0]
        outputs = [ambiguity_output, testability_output]

        def fake_invoke(**_kwargs: Any) -> dict:
            idx = call_count[0] % 2
            call_count[0] += 1
            return outputs[idx]

        return patch(
            "handlers.refine.impl.invoke_agent_with_schema_retry",
            side_effect=fake_invoke,
        )

    # --- skipped / failed early exits ---

    def test_disabled_returns_skipped(self) -> None:
        cfg = self._config()
        cfg["commands"]["refine"]["enabled"] = False
        result = run_refine(cfg, self._ctx())
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["command"], "refine")

    def test_missing_design_spec_returns_skipped(self) -> None:
        cfg = self._config()
        cfg["commands"]["refine"]["inputs"]["design_spec_path"] = ""
        result = run_refine(cfg, self._ctx())
        self.assertEqual(result["status"], "skipped")

    def test_nonexistent_design_spec_returns_skipped(self) -> None:
        cfg = self._config()
        cfg["commands"]["refine"]["inputs"]["design_spec_path"] = "/no/such/file.csv"
        result = run_refine(cfg, self._ctx())
        self.assertEqual(result["status"], "skipped")

    def test_missing_required_column_returns_failed(self) -> None:
        bad_csv = Path(self.tmp) / "bad.csv"
        bad_csv.write_text("spec_id,module_tag\nS1,core\n", encoding="utf-8")
        cfg = self._config()
        cfg["commands"]["refine"]["inputs"]["design_spec_path"] = str(bad_csv)
        result = run_refine(cfg, self._ctx())
        self.assertEqual(result["status"], "failed")
        self.assertIn("module_role", result.get("reason", "").lower() + result.get("reason", ""))

    # --- 0 items → completed ---

    def test_zero_items_returns_completed(self) -> None:
        with self._mock_both_agents(_empty_agent_output(), _empty_agent_output()):
            result = run_refine(self._config(), self._ctx())
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["command"], "refine")
        self.assertEqual(result["specs_improved"], 0)

    def test_zero_items_writes_output_csv(self) -> None:
        output_path = Path(self.tmp) / "out" / "REFINED-SPEC.csv"
        with self._mock_both_agents(_empty_agent_output(), _empty_agent_output()):
            run_refine(self._config(), self._ctx())
        self.assertTrue(output_path.exists())

    def test_zero_items_output_csv_matches_input(self) -> None:
        output_path = Path(self.tmp) / "out" / "REFINED-SPEC.csv"
        with self._mock_both_agents(_empty_agent_output(), _empty_agent_output()):
            run_refine(self._config(), self._ctx())
        original = self.design_csv.read_text(encoding="utf-8")
        refined = output_path.read_text(encoding="utf-8")
        self.assertEqual(original.strip(), refined.strip())

    # --- N items → needs_resolution ---

    def test_items_returns_needs_resolution(self) -> None:
        with self._mock_both_agents(_ambiguity_items_output(), _testability_items_output()):
            result = run_refine(self._config(), self._ctx())
        self.assertEqual(result["status"], "needs_resolution")
        self.assertEqual(result["blocking_items"], 2)

    def test_items_writes_stage_json(self) -> None:
        run_dir = Path(self.tmp) / "out" / "agent_runs" / "refine" / "test-run"
        with self._mock_both_agents(_ambiguity_items_output(), _testability_items_output()):
            run_refine(self._config(), self._ctx())
        stage_file = run_dir / "manual_resolution" / "agent_review.json"
        self.assertTrue(stage_file.exists())
        data = json.loads(stage_file.read_text(encoding="utf-8"))
        self.assertEqual(len(data["items"]), 2)

    def test_items_writes_resolutions_yaml(self) -> None:
        run_dir = Path(self.tmp) / "out" / "agent_runs" / "refine" / "test-run"
        with self._mock_both_agents(_ambiguity_items_output(), _testability_items_output()):
            run_refine(self._config(), self._ctx())
        resolutions_file = run_dir / "manual_resolution" / "resolutions.yaml"
        self.assertTrue(resolutions_file.exists())

    def test_items_writes_run_meta_with_command(self) -> None:
        run_dir = Path(self.tmp) / "out" / "agent_runs" / "refine" / "test-run"
        with self._mock_both_agents(_ambiguity_items_output(), _testability_items_output()):
            run_refine(self._config(), self._ctx())
        run_meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(run_meta["command"], "refine")
        self.assertEqual(run_meta["run_id"], "test-run")

    # --- decomposition skipped gracefully ---

    def test_decomposition_skipped_when_library_absent(self) -> None:
        """Refine still completes when sentence-transformers is unavailable."""
        cfg = self._config()
        cfg["commands"]["refine"]["decomposition"]["enabled"] = True
        cfg["commands"]["refine"]["decomposition"]["blocking"] = True

        import builtins
        real_import = builtins.__import__

        def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "sentence_transformers":
                raise ImportError("not installed")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            with self._mock_both_agents(_empty_agent_output(), _empty_agent_output()):
                result = run_refine(cfg, self._ctx())

        self.assertIn(result["status"], {"completed", "needs_resolution"})

    def test_decomposition_flags_json_written(self) -> None:
        cfg = self._config()
        cfg["commands"]["refine"]["decomposition"]["enabled"] = True
        run_dir = Path(self.tmp) / "out" / "agent_runs" / "refine" / "test-run"

        import builtins
        real_import = builtins.__import__

        def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "sentence_transformers":
                raise ImportError("not installed")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            with self._mock_both_agents(_empty_agent_output(), _empty_agent_output()):
                run_refine(cfg, self._ctx())

        flags_file = run_dir / "decomposition_flags.json"
        self.assertTrue(flags_file.exists())

    # --- dry_run ---

    def test_dry_run_does_not_write_output_csv(self) -> None:
        output_path = Path(self.tmp) / "out" / "REFINED-SPEC.csv"
        ctx = RuntimeContext(
            command="refine",
            dry_run=True,
            verbose=False,
            command_only_validation=False,
            run_id="test-run",
            project_root=self.tmp,
            config_path="config/config.yaml",
        )
        with self._mock_both_agents(_empty_agent_output(), _empty_agent_output()):
            result = run_refine(self._config(), ctx)
        self.assertEqual(result["status"], "completed")
        self.assertFalse(output_path.exists())


# ---------------------------------------------------------------------------
# Group F: Schema validation
# ---------------------------------------------------------------------------

class SchemaValidationTests(unittest.TestCase):
    """Tests that the JSON schema files are valid and accept/reject correctly."""

    _SCHEMA_DIR = _PIKA_ROOT / "schemas" / "agent_outputs"

    def _load_schema(self, name: str) -> dict[str, Any]:
        path = self._SCHEMA_DIR / f"{name}.schema.json"
        self.assertTrue(path.exists(), f"Schema not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _validate(self, schema: dict, instance: Any) -> None:
        import jsonschema  # type: ignore[import]

        jsonschema.validate(instance, schema)

    def _validate_fails(self, schema: dict, instance: Any) -> None:
        import jsonschema

        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)

    def test_ambiguity_schema_is_valid_json(self) -> None:
        schema = self._load_schema("spec_ambiguity_detector_output")
        self.assertIn("properties", schema)

    def test_testability_schema_is_valid_json(self) -> None:
        schema = self._load_schema("spec_testability_auditor_output")
        self.assertIn("properties", schema)

    def test_editor_schema_is_valid_json(self) -> None:
        schema = self._load_schema("spec_editor_output")
        self.assertIn("oneOf", schema)

    def test_ambiguity_schema_accepts_empty_items(self) -> None:
        schema = self._load_schema("spec_ambiguity_detector_output")
        self._validate(schema, {"manual_resolution_items": []})

    def test_ambiguity_schema_accepts_valid_item(self) -> None:
        schema = self._load_schema("spec_ambiguity_detector_output")
        self._validate(schema, {
            "manual_resolution_items": [
                {
                    "item_id": "AMB-001",
                    "title": "Vague requirement",
                    "spec_id": "S1",
                    "field": "requirement",
                    "vague_phrases": ["appropriately"],
                    "suggested_improvement": "Clear text.",
                    "options": [
                        {"option_id": "accept_suggestion", "label": "Accept", "effect": "Apply"},
                    ],
                }
            ]
        })

    def test_ambiguity_schema_rejects_unknown_field_enum(self) -> None:
        schema = self._load_schema("spec_ambiguity_detector_output")
        self._validate_fails(schema, {
            "manual_resolution_items": [
                {
                    "item_id": "AMB-001",
                    "title": "T",
                    "spec_id": "S1",
                    "field": "title",  # not in enum
                    "vague_phrases": ["x"],
                    "suggested_improvement": "y",
                    "options": [{"option_id": "skip", "label": "L", "effect": "E"}],
                }
            ]
        })

    def test_testability_schema_accepts_empty_items(self) -> None:
        schema = self._load_schema("spec_testability_auditor_output")
        self._validate(schema, {"manual_resolution_items": []})

    def test_testability_schema_accepts_valid_item(self) -> None:
        schema = self._load_schema("spec_testability_auditor_output")
        self._validate(schema, {
            "manual_resolution_items": [
                {
                    "item_id": "TEST-001",
                    "title": "Untestable",
                    "spec_id": "S2",
                    "field": "acceptance_criteria",
                    "untestable_reason": "Too vague.",
                    "suggested_improvement": "Returns within 200ms.",
                    "suggested_test_type": "integration",
                    "options": [
                        {"option_id": "accept_suggestion", "label": "Accept", "effect": "Apply"},
                    ],
                }
            ]
        })

    def test_editor_schema_field_mode_validates(self) -> None:
        schema = self._load_schema("spec_editor_output")
        self._validate(schema, {
            "edit_type": "field",
            "spec_id": "S1",
            "field": "requirement",
            "new_text": "Validates input length <= 255 chars.",
            "rationale": "Made measurable.",
        })

    def test_editor_schema_structural_mode_validates(self) -> None:
        schema = self._load_schema("spec_editor_output")
        self._validate(schema, {
            "edit_type": "structural",
            "rationale": "Split into two specs.",
            "edits": [
                {
                    "action": "add",
                    "spec_id": "S1a",
                    "row_data": {
                        "spec_id": "S1a",
                        "module_tag": "core",
                        "module_role": "domain",
                        "requirement": "Part A.",
                        "acceptance_criteria": "A passes.",
                    },
                },
                {"action": "delete", "spec_id": "S1"},
            ],
        })

    def test_editor_schema_rejects_invalid_edit_type(self) -> None:
        schema = self._load_schema("spec_editor_output")
        self._validate_fails(schema, {
            "edit_type": "unknown",
            "spec_id": "S1",
            "field": "requirement",
            "new_text": "x",
            "rationale": "y",
        })

    def test_editor_schema_rejects_structural_with_no_edits(self) -> None:
        schema = self._load_schema("spec_editor_output")
        self._validate_fails(schema, {
            "edit_type": "structural",
            "rationale": "reason",
            "edits": [],  # minItems: 1
        })


if __name__ == "__main__":
    unittest.main()
