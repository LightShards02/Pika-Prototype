"""Tests for handlers.refine — spec quality review and improvement workflow."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from core.context import RuntimeContext
from core.errors import WorksetValidationError
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
    _resume_refine,
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
        with self.assertRaises(WorksetValidationError) as cm:
            _validate_required_columns(
                headers,
                ["spec_id", "module_tag", "module_role", "requirement", "acceptance_criteria"],
            )
        self.assertIn("requirement", str(cm.exception).lower())

    def test_error_message_lists_all_missing(self) -> None:
        with self.assertRaises(WorksetValidationError) as cm:
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

    # --- N items → blocked ---

    def test_items_returns_blocked(self) -> None:
        with self._mock_both_agents(_ambiguity_items_output(), _testability_items_output()):
            result = run_refine(self._config(), self._ctx())
        self.assertEqual(result["status"], "blocked")
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

    def test_decomposition_flags_json_written(self) -> None:
        """Decomposition check writes decomposition_flags.json when enabled."""
        cfg = self._config()
        cfg["commands"]["refine"]["decomposition"]["enabled"] = True
        run_dir = Path(self.tmp) / "out" / "agent_runs" / "refine" / "test-run"

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


class RefineResumeTests(unittest.TestCase):
    """Group H — resume logic in run_refine / _resume_refine."""

    def _run_dir(self, tmp: str, run_id: str) -> Path:
        return Path(tmp) / "out" / "agent_runs" / "refine" / run_id

    def _write_run_meta(self, run_dir: Path, meta: dict[str, Any]) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "run_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    def test_run_refine_with_resume_run_id_delegates_to_resume(self) -> None:
        """run_refine with resume_run_id set calls _resume_refine."""
        with tempfile.TemporaryDirectory() as tmp:
            config = _make_config(tmp)
            ctx = RuntimeContext(
                command="refine",
                dry_run=False,
                verbose=False,
                command_only_validation=False,
                run_id="new-run",
                project_root=tmp,
                config_path="config/config.yaml",
                input_overrides={},
                resume_run_id="missing-run-id",
            )

            result = run_refine(config, ctx)

            # Should fail gracefully because run_id doesn't exist
            self.assertEqual(result["status"], "failed")
            self.assertIn("missing-run-id", result["reason"])

    def test_resume_refine_nonexistent_run_raises_resume_error(self) -> None:
        """_resume_refine with unknown run_id raises ResumeError."""
        from core.errors import ResumeError

        with tempfile.TemporaryDirectory() as tmp:
            config = _make_config(tmp)
            ctx = _make_ctx(tmp)

            with self.assertRaises(ResumeError) as cm:
                _resume_refine(config, ctx, Path(tmp), "ghost-run-99")
            self.assertIn("ghost-run-99", str(cm.exception))

    def test_resume_refine_no_blocked_or_failed_raises_resume_error(self) -> None:
        """_resume_refine with no blocked_at_stage or failed_at_stage raises ResumeError."""
        from core.errors import ResumeError

        with tempfile.TemporaryDirectory() as tmp:
            run_id = "pending-run"
            run_dir = self._run_dir(tmp, run_id)
            self._write_run_meta(run_dir, {
                "command": "refine",
                "run_id": run_id,
                "resolution_status": "pending",
            })
            config = _make_config(tmp)
            ctx = _make_ctx(tmp)

            with self.assertRaises(ResumeError) as cm:
                _resume_refine(config, ctx, Path(tmp), run_id)
            self.assertIn("not resumable", str(cm.exception))

    def test_resume_refine_unknown_blocked_stage_raises_resume_error(self) -> None:
        """_resume_refine with an unrecognised blocked_at_stage raises ResumeError."""
        from core.errors import ResumeError

        with tempfile.TemporaryDirectory() as tmp:
            run_id = "weird-stage-run"
            run_dir = self._run_dir(tmp, run_id)
            self._write_run_meta(run_dir, {
                "command": "refine",
                "run_id": run_id,
                "blocked_at_stage": "unknown_stage",
                "resolution_status": "resolved",
            })
            config = _make_config(tmp)
            ctx = _make_ctx(tmp)

            with self.assertRaises(ResumeError) as cm:
                _resume_refine(config, ctx, Path(tmp), run_id)
            self.assertIn("unknown_stage", str(cm.exception))

    def test_resume_refine_agent_review_returns_completed_immediately(self) -> None:
        """_resume_refine after agent_review block: resolve already applied, return completed."""
        with tempfile.TemporaryDirectory() as tmp:
            run_id = "agent-review-run"
            run_dir = self._run_dir(tmp, run_id)
            out_csv = str(Path(tmp) / "out" / "REFINED-SPEC.csv")
            self._write_run_meta(run_dir, {
                "command": "refine",
                "run_id": run_id,
                "blocked_at_stage": "agent_review",
                "resolution_status": "resolved",
                "output_design_spec_path": out_csv,
            })
            config = _make_config(tmp)
            ctx = _make_ctx(tmp)

            result = _resume_refine(config, ctx, Path(tmp), run_id)

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["run_id"], run_id)
            self.assertEqual(result["output_path"], out_csv)

    def test_resume_refine_decomposition_missing_output_csv_raises_resume_error(self) -> None:
        """_resume_refine after decomposition block with no output CSV raises ResumeError."""
        from core.errors import ResumeError

        with tempfile.TemporaryDirectory() as tmp:
            run_id = "decomp-run-no-csv"
            run_dir = self._run_dir(tmp, run_id)
            self._write_run_meta(run_dir, {
                "command": "refine",
                "run_id": run_id,
                "blocked_at_stage": "decomposition",
                "resolution_status": "resolved",
                # output_design_spec_path deliberately absent
            })
            config = _make_config(tmp)
            ctx = _make_ctx(tmp)

            with self.assertRaises(ResumeError) as cm:
                _resume_refine(config, ctx, Path(tmp), run_id)
            self.assertIn("output_design_spec_path", str(cm.exception))

    def test_resume_refine_decomposition_runs_agents_and_completes(self) -> None:
        """_resume_refine after decomposition block loads restructured CSV and runs agents."""
        with tempfile.TemporaryDirectory() as tmp:
            run_id = "decomp-run-ok"
            run_dir = self._run_dir(tmp, run_id)

            # Write the restructured CSV that resolve would have produced
            restructured = Path(tmp) / "out" / "RESTRUCTURED-SPEC.csv"
            _write_design_csv(restructured)
            _write_project_context(Path(tmp))

            out_csv = str(Path(tmp) / "out" / "REFINED-SPEC.csv")
            self._write_run_meta(run_dir, {
                "command": "refine",
                "run_id": run_id,
                "input_design_spec_path": str(restructured),
                "output_design_spec_path": str(restructured),
                "blocked_at_stage": "decomposition",
                "resolution_status": "resolved",
                "completed_stages": ["decomposition"],
            })

            config = _make_config(tmp, design_csv_path=str(restructured))
            # Override output path to our tmp location
            config["commands"]["refine"]["outputs"]["design_spec_path"] = {
                "path": out_csv,
                "no_overwrite": False,
            }
            ctx = _make_ctx(tmp, run_id=run_id)

            with patch(
                "handlers.refine.impl.invoke_agent_with_schema_retry",
                return_value=_empty_agent_output(),
            ):
                result = _resume_refine(config, ctx, Path(tmp), run_id)

            # Agents found no issues → completed, output CSV copied
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["run_id"], run_id)
            self.assertTrue(Path(result["output_path"]).exists())

    def test_resume_refine_decomposition_agents_find_items_blocks_again(self) -> None:
        """_resume_refine after decomposition block: agents find items → blocked at agent_review."""
        with tempfile.TemporaryDirectory() as tmp:
            run_id = "decomp-run-more-issues"
            run_dir = self._run_dir(tmp, run_id)

            restructured = Path(tmp) / "out" / "RESTRUCTURED-SPEC.csv"
            _write_design_csv(restructured)
            _write_project_context(Path(tmp))

            self._write_run_meta(run_dir, {
                "command": "refine",
                "run_id": run_id,
                "input_design_spec_path": str(restructured),
                "output_design_spec_path": str(restructured),
                "blocked_at_stage": "decomposition",
                "resolution_status": "resolved",
                "completed_stages": ["decomposition"],
            })

            config = _make_config(tmp, design_csv_path=str(restructured))
            ctx = _make_ctx(tmp, run_id=run_id)

            with patch(
                "handlers.refine.impl.invoke_agent_with_schema_retry",
                return_value=_ambiguity_items_output(),
            ):
                result = _resume_refine(config, ctx, Path(tmp), run_id)

            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["blocking_stage"], "agent_review")
            self.assertGreater(result["blocking_items"], 0)


if __name__ == "__main__":
    unittest.main()
