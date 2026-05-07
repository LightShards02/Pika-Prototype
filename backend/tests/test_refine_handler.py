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
    _REQUIRED_COLUMNS,
    _filter_by_consensus,
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
]

_SAMPLE_ROWS: list[dict[str, str]] = [
    {
        "spec_id": "S1",
        "module_tag": "core",
        "module_role": "domain",
        "requirement": "The system shall validate user input appropriately.",
    },
    {
        "spec_id": "S2",
        "module_tag": "core",
        "module_role": "domain",
        "requirement": "The system shall return results quickly.",
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
        "commands": {
            "refine": {
                "enabled": True,
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
    """Empty output for the merged testability enricher (full mode)."""
    return {"manual_resolution_items": [], "enrichments": []}


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
    """Output for the merged testability enricher — MR items target requirement only."""
    return {
        "manual_resolution_items": [
            {
                "item_id": "TEST-001",
                "title": "Requirement too vague for testable AC",
                "spec_id": "S2",
                "field": "requirement",
                "untestable_reason": "Requirement uses vague language that cannot produce a measurable AC.",
                "suggested_improvement": "The system shall return results within 200ms under normal load.",
                "suggested_test_type": "integration",
                "options": [
                    {"option_id": "accept_suggestion", "label": "Accept", "effect": "Apply"},
                    {"option_id": "let_agent_edit", "label": "Let agent edit", "effect": "Call spec_editor"},
                    {"option_id": "skip", "label": "Skip", "effect": "Keep original"},
                ],
            }
        ],
        "enrichments": [],
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
        self.assertEqual(cfg["testability_enricher_prompt_name"], "spec_testability_enricher")
        self.assertEqual(cfg["spec_editor_prompt_name"], "spec_editor")
        self.assertIn("spec_change_merger_prompt_name", cfg)
        self.assertTrue(cfg["decomposition_enabled"])
        self.assertFalse(cfg["decomposition_blocking"])
        self.assertAlmostEqual(cfg["similarity_threshold"], 0.85)
        self.assertAlmostEqual(cfg["variance_threshold"], 0.15)

    def test_enabled_false(self) -> None:
        cfg = _get_refine_cfg({"commands": {"refine": {"enabled": False}}})
        self.assertFalse(cfg["enabled"])

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
        _validate_required_columns(_SAMPLE_HEADERS, list(_REQUIRED_COLUMNS))

    def test_case_insensitive_match(self) -> None:
        headers = ["Spec_ID", "Module_Tag", "Module_Role", "Requirement"]
        _validate_required_columns(headers, list(_REQUIRED_COLUMNS))

    def test_raises_on_missing_column(self) -> None:
        headers = ["spec_id", "module_tag", "module_role"]
        with self.assertRaises(WorksetValidationError) as cm:
            _validate_required_columns(headers, list(_REQUIRED_COLUMNS))
        self.assertIn("requirement", str(cm.exception).lower())

    def test_accepts_optional_acceptance_criteria_column(self) -> None:
        """Input may omit acceptance_criteria; refine adds it when enriching."""
        headers = list(_SAMPLE_HEADERS) + ["acceptance_criteria"]
        _validate_required_columns(headers, list(_REQUIRED_COLUMNS))

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

    def _make_amb(self, spec_id: str, item_id: str = "AMB-001") -> dict:
        return {
            "item_id": item_id,
            "spec_id": spec_id,
            "title": "Vague requirement",
            "field": "requirement",
            "vague_phrases": ["should be fast"],
            "suggested_improvement": "rewrite",
            "options": [
                {"option_id": "accept_suggestion", "label": "Accept", "effect": "Apply"},
                {"option_id": "let_agent_edit", "label": "Agent", "effect": "Agent edits"},
                {"option_id": "skip", "label": "Skip", "effect": "No change"},
            ],
        }

    def _make_test(self, spec_id: str, item_id: str = "TEST-001") -> dict:
        return {
            "item_id": item_id,
            "spec_id": spec_id,
            "title": "Untestable criteria",
            "field": "acceptance_criteria",
            "untestable_reason": "No threshold",
            "suggested_improvement": "rewrite ac",
            "suggested_test_type": "integration",
            "options": [
                {"option_id": "accept_suggestion", "label": "Accept", "effect": "Apply"},
                {"option_id": "let_agent_edit", "label": "Agent", "effect": "Agent edits"},
                {"option_id": "skip", "label": "Skip", "effect": "No change"},
            ],
        }

    def test_all_empty_returns_empty(self) -> None:
        self.assertEqual(_merge_all_items([], [], []), [])

    def test_single_ambiguity_item_wraps_in_envelope(self) -> None:
        result = _merge_all_items([], [self._make_amb("A1001")], [])
        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertFalse(item["is_compound"])
        self.assertEqual(item["spec_id"], "A1001")
        self.assertEqual(len(item["concerns"]), 1)
        self.assertEqual(item["concerns"][0]["agent_type"], "ambiguity")

    def test_same_spec_id_creates_compound(self) -> None:
        amb = [self._make_amb("A1001")]
        test = [self._make_test("A1001")]
        result = _merge_all_items([], amb, test)
        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertTrue(item["is_compound"])
        self.assertEqual(item["item_id"], "merged_A1001")
        self.assertEqual(len(item["concerns"]), 2)
        types = {c["agent_type"] for c in item["concerns"]}
        self.assertEqual(types, {"ambiguity", "testability"})
        # Compound options should be item-level and include accept_both_improvements
        option_ids = {o["option_id"] for o in item["options"]}
        self.assertIn("accept_ambiguity", option_ids)
        self.assertIn("accept_testability", option_ids)
        self.assertIn("accept_both_improvements", option_ids)
        self.assertIn("let_agent_edit", option_ids)
        self.assertIn("skip", option_ids)

    def test_different_spec_ids_stay_separate(self) -> None:
        amb = [self._make_amb("A1001")]
        test = [self._make_test("A1002")]
        result = _merge_all_items([], amb, test)
        self.assertEqual(len(result), 2)
        self.assertFalse(result[0]["is_compound"])
        self.assertFalse(result[1]["is_compound"])

    def test_decomp_items_prepended_unchanged(self) -> None:
        decomp = [{"item_id": "DECOMP-001", "spec_id": "A1001"}]
        amb = [self._make_amb("A1002")]
        result = _merge_all_items(decomp, amb, [])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["item_id"], "DECOMP-001")
        # Decomp item is not wrapped in concerns envelope
        self.assertNotIn("concerns", result[0])

    def test_sorted_by_spec_id(self) -> None:
        amb = [self._make_amb("B2000"), self._make_amb("A1001", "AMB-002")]
        result = _merge_all_items([], amb, [])
        spec_ids = [r["spec_id"] for r in result]
        self.assertEqual(spec_ids, ["A1001", "B2000"])

    def test_concerns_preserve_fields(self) -> None:
        amb = [self._make_amb("A1001")]
        test = [self._make_test("A1001")]
        result = _merge_all_items([], amb, test)
        item = result[0]
        amb_concern = next(c for c in item["concerns"] if c["agent_type"] == "ambiguity")
        test_concern = next(c for c in item["concerns"] if c["agent_type"] == "testability")
        self.assertEqual(amb_concern["vague_phrases"], ["should be fast"])
        self.assertEqual(test_concern["untestable_reason"], "No threshold")
        self.assertEqual(test_concern["suggested_test_type"], "integration")


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
        """Context manager that mocks all parallel agent calls (N replicas each)."""

        def fake_invoke(prompt_name: str = "", **_kwargs: Any) -> dict:
            if "ambiguity" in prompt_name:
                return ambiguity_output
            return testability_output

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
        self.assertIn("specs_enriched", result)

    def test_zero_items_writes_output_csv(self) -> None:
        output_path = Path(self.tmp) / "out" / "REFINED-SPEC.csv"
        with self._mock_both_agents(_empty_agent_output(), _empty_agent_output()):
            run_refine(self._config(), self._ctx())
        self.assertTrue(output_path.exists())

    def test_zero_items_output_csv_contains_required_columns(self) -> None:
        """When 0 MR items, output CSV is written (may add AC/evidence_type columns)."""
        output_path = Path(self.tmp) / "out" / "REFINED-SPEC.csv"
        with self._mock_both_agents(_empty_agent_output(), _empty_agent_output()):
            run_refine(self._config(), self._ctx())
        content = output_path.read_text(encoding="utf-8")
        self.assertIn("spec_id", content.splitlines()[0])

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

    def test_testability_enricher_schema_is_valid_json(self) -> None:
        schema = self._load_schema("spec_testability_enricher_output")
        self.assertIn("properties", schema)

    def test_testability_triage_schema_is_valid_json(self) -> None:
        schema = self._load_schema("spec_testability_triage_output")
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

    def test_ambiguity_schema_rejects_non_requirement_field(self) -> None:
        schema = self._load_schema("spec_ambiguity_detector_output")
        for bad_field in ["acceptance_criteria", "title"]:
            self._validate_fails(schema, {
                "manual_resolution_items": [
                    {
                        "item_id": "AMB-001",
                        "title": "T",
                        "spec_id": "S1",
                        "field": bad_field,
                        "vague_phrases": ["x"],
                        "suggested_improvement": "y",
                        "options": [{"option_id": "skip", "label": "L", "effect": "E"}],
                    }
                ]
            })

    def test_testability_enricher_schema_accepts_empty(self) -> None:
        schema = self._load_schema("spec_testability_enricher_output")
        self._validate(schema, {"manual_resolution_items": [], "enrichments": []})

    def test_testability_enricher_schema_accepts_valid_enrichment(self) -> None:
        """Full-mode output with an enrichment entry for a clear requirement.

        P6: test_plan is required on enrichment_item; an empty
        planned_test_cases is allowed for evidence_type='NA' or non-testable
        specs but the field must be present.
        """
        schema = self._load_schema("spec_testability_enricher_output")
        self._validate(schema, {
            "enrichments": [
                {
                    "spec_id": "S1",
                    "acceptance_criteria": "Given valid input, when processed, the system returns 200.",
                    "evidence_type": "test_execution_record",
                    "test_plan": {"planned_test_cases": []},
                }
            ],
            "manual_resolution_items": [],
        })

    def test_testability_enricher_schema_accepts_mr_item_requirement_field(self) -> None:
        """Full-mode output with an MR item targeting requirement (vague requirement)."""
        schema = self._load_schema("spec_testability_enricher_output")
        self._validate(schema, {
            "enrichments": [],
            "manual_resolution_items": [
                {
                    "item_id": "TEST-001",
                    "title": "Requirement too vague for testable AC",
                    "spec_id": "S2",
                    "field": "requirement",
                    "untestable_reason": "Requirement uses vague language.",
                    "suggested_improvement": "The system shall return results within 200ms.",
                    "suggested_test_type": "integration",
                    "options": [
                        {"option_id": "accept_suggestion", "label": "Accept", "effect": "Apply"},
                    ],
                }
            ],
        })

    def test_testability_enricher_schema_rejects_ac_field(self) -> None:
        """MR items must target requirement only — acceptance_criteria field is rejected."""
        schema = self._load_schema("spec_testability_enricher_output")
        self._validate_fails(schema, {
            "enrichments": [],
            "manual_resolution_items": [
                {
                    "item_id": "TEST-001",
                    "title": "T",
                    "spec_id": "S2",
                    "field": "acceptance_criteria",
                    "untestable_reason": "Too vague.",
                    "suggested_improvement": "Returns within 200ms.",
                    "suggested_test_type": "integration",
                    "options": [{"option_id": "skip", "label": "L", "effect": "E"}],
                }
            ],
        })

    def test_testability_triage_schema_accepts_empty(self) -> None:
        schema = self._load_schema("spec_testability_triage_output")
        self._validate(schema, {"manual_resolution_items": []})

    def test_testability_triage_schema_rejects_ac_field(self) -> None:
        """Triage schema MR items must target requirement only."""
        schema = self._load_schema("spec_testability_triage_output")
        self._validate_fails(schema, {
            "manual_resolution_items": [
                {
                    "item_id": "TEST-001",
                    "title": "T",
                    "spec_id": "S2",
                    "field": "acceptance_criteria",
                    "untestable_reason": "Too vague.",
                    "suggested_improvement": "Returns within 200ms.",
                    "suggested_test_type": "integration",
                    "options": [{"option_id": "skip", "label": "L", "effect": "E"}],
                }
            ],
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

    def test_editor_schema_rejects_ac_field(self) -> None:
        """spec_editor field-level edits must target requirement only."""
        schema = self._load_schema("spec_editor_output")
        self._validate_fails(schema, {
            "edit_type": "field",
            "spec_id": "S1",
            "field": "acceptance_criteria",
            "new_text": "some text",
            "rationale": "reason",
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


class RefineEnrichmentApplicationTests(unittest.TestCase):
    """Group G2 — AC/evidence_type application from enrichments after consensus."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.design_csv = Path(self.tmp) / "DESIGN-SPEC.csv"
        _write_design_csv(self.design_csv)
        _write_project_context(Path(self.tmp))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _config(self) -> dict[str, Any]:
        return _make_config(self.tmp, str(self.design_csv))

    def _ctx(self, run_id: str = "enrich-run") -> RuntimeContext:
        return _make_ctx(self.tmp, run_id)

    def _mock_with_enrichment(self, enrichments: list[dict]) -> Any:
        """Mock agents: ambiguity returns empty, testability instance 0 returns enrichments."""
        call_count: dict[str, int] = {"testability": 0}

        def fake_invoke(prompt_name: str = "", template_vars: dict | None = None, **_kwargs: Any) -> dict:
            if "ambiguity" in prompt_name:
                return {"manual_resolution_items": []}
            call_count["testability"] += 1
            enrich_mode = (template_vars or {}).get("enrich_mode", "triage")
            if enrich_mode == "full":
                return {"enrichments": enrichments, "manual_resolution_items": []}
            return {"manual_resolution_items": []}

        return patch(
            "handlers.refine.impl.invoke_agent_with_schema_retry",
            side_effect=fake_invoke,
        )

    def test_enrichments_applied_to_output_csv(self) -> None:
        """When testability instance 0 returns enrichments, AC and evidence_type are written."""
        enrichments = [
            {"spec_id": "S1", "acceptance_criteria": "Given valid input, returns 200.", "evidence_type": "test_execution_record"},
            {"spec_id": "S2", "acceptance_criteria": "Given load test, returns within 200ms.", "evidence_type": "test_execution_record"},
        ]
        output_path = Path(self.tmp) / "out" / "REFINED-SPEC.csv"
        with self._mock_with_enrichment(enrichments):
            result = run_refine(self._config(), self._ctx())
        self.assertEqual(result["status"], "completed")
        content = output_path.read_text(encoding="utf-8")
        self.assertIn("returns 200", content)
        self.assertIn("200ms", content)
        self.assertIn("test_execution_record", content)

    def test_enrichment_skipped_for_flagged_specs(self) -> None:
        """Specs that appear in MR items are not enriched (MR takes priority)."""
        from handlers.refine.impl import _run_refine_agents
        from pathlib import Path as _P

        # Simulate: instance 0 returns both enrichment AND MR for same spec_id
        # Handler guard should suppress the enrichment
        flagged_spec = "S1"

        def fake_invoke(prompt_name: str = "", template_vars: dict | None = None, **_kwargs: Any) -> dict:
            if "ambiguity" in prompt_name:
                return {"manual_resolution_items": []}
            enrich_mode = (template_vars or {}).get("enrich_mode", "triage")
            if enrich_mode == "full":
                return {
                    "enrichments": [{"spec_id": flagged_spec, "acceptance_criteria": "Should NOT appear.", "evidence_type": "test_execution_record"}],
                    "manual_resolution_items": [
                        {
                            "item_id": "TEST-001",
                            "title": "Vague",
                            "spec_id": flagged_spec,
                            "field": "requirement",
                            "untestable_reason": "Too vague.",
                            "suggested_improvement": "Improved requirement.",
                            "suggested_test_type": "unit",
                            "options": [{"option_id": "skip", "label": "Skip", "effect": "No change"}],
                        }
                    ],
                }
            return {"manual_resolution_items": [
                {
                    "item_id": "TEST-001",
                    "title": "Vague",
                    "spec_id": flagged_spec,
                    "field": "requirement",
                    "untestable_reason": "Too vague.",
                    "suggested_improvement": "Improved requirement.",
                    "suggested_test_type": "unit",
                    "options": [{"option_id": "skip", "label": "Skip", "effect": "No change"}],
                }
            ]}

        with patch("handlers.refine.impl.invoke_agent_with_schema_retry", side_effect=fake_invoke):
            result = run_refine(self._config(), self._ctx())

        self.assertEqual(result["status"], "blocked")
        # Run enrichments.json and check flagged spec was not enriched
        run_dir = _P(self.tmp) / "out" / "agent_runs" / "refine" / "enrich-run"
        enrichments_file = run_dir / "enrichments.json"
        if enrichments_file.exists():
            import json as _json
            data = _json.loads(enrichments_file.read_text())
            enriched_spec_ids = {e["spec_id"] for e in data.get("enrichments", [])}
            self.assertNotIn(flagged_spec, enriched_spec_ids, "Flagged spec must not appear in enrichments")


class RefineCompoundResolutionTests(unittest.TestCase):
    """Group G3 — compound resolution: accept_both_improvements + accept_testability to requirement."""

    def _make_rows(self) -> list[dict[str, Any]]:
        return [{"spec_id": "S1", "module_tag": "core", "module_role": "domain",
                 "requirement": "The system should handle errors.", "acceptance_criteria": ""}]

    def _make_headers(self) -> list[str]:
        return ["spec_id", "module_tag", "module_role", "requirement", "acceptance_criteria"]

    def _make_compound_item(self) -> dict[str, Any]:
        return {
            "item_id": "merged_S1",
            "spec_id": "S1",
            "is_compound": True,
            "title": "Multiple issues: S1",
            "concerns": [
                {"item_id": "AMB-001", "agent_type": "ambiguity", "field": "requirement",
                 "title": "Vague", "vague_phrases": ["should handle"],
                 "suggested_improvement": "The system shall return a 400 error for invalid input."},
                {"item_id": "TEST-001", "agent_type": "testability", "field": "requirement",
                 "title": "Untestable", "untestable_reason": "No measurable outcome.",
                 "suggested_improvement": "The system shall log errors to system_log within 1s.",
                 "suggested_test_type": "integration"},
            ],
            "options": [
                {"option_id": "accept_ambiguity", "label": "Accept ambiguity fix", "effect": "Apply ambiguity suggestion to requirement field"},
                {"option_id": "accept_testability", "label": "Accept testability fix", "effect": "Apply testability suggestion to requirement field"},
                {"option_id": "accept_both_improvements", "label": "Accept both improvements", "effect": "Invoke merger"},
                {"option_id": "let_agent_edit", "label": "Let agent edit", "effect": "Agent edits"},
                {"option_id": "skip", "label": "Skip", "effect": "Leave unchanged"},
            ],
        }

    def test_accept_testability_applies_to_requirement(self) -> None:
        """accept_testability must apply to requirement, not acceptance_criteria."""
        from handlers.resolve import _apply_compound_resolution
        rows = self._make_rows()
        headers = self._make_headers()
        item = self._make_compound_item()
        item["chosen_option_id"] = "accept_testability"

        changes, updated_rows = _apply_compound_resolution(item, rows, headers, 0, [])
        self.assertEqual(changes, 1)
        self.assertEqual(updated_rows[0]["requirement"], "The system shall log errors to system_log within 1s.")
        # acceptance_criteria must NOT be touched
        self.assertEqual(updated_rows[0]["acceptance_criteria"], "")

    def test_accept_both_improvements_with_editor_output_applies_to_requirement(self) -> None:
        """accept_both_improvements with editor_output applies merged text to requirement."""
        from handlers.resolve import _apply_compound_resolution
        rows = self._make_rows()
        headers = self._make_headers()
        item = self._make_compound_item()
        item["chosen_option_id"] = "accept_both_improvements"
        item["editor_output"] = {
            "edit_type": "field",
            "spec_id": "S1",
            "field": "requirement",
            "new_text": "The system shall return a 400 error for invalid input and log errors within 1s.",
            "rationale": "Merged both fixes.",
        }

        changes, updated_rows = _apply_compound_resolution(item, rows, headers, 0, [])
        self.assertEqual(changes, 1)
        self.assertEqual(updated_rows[0]["requirement"], "The system shall return a 400 error for invalid input and log errors within 1s.")
        self.assertEqual(updated_rows[0]["acceptance_criteria"], "")

    def test_accept_both_improvements_without_editor_output_no_change(self) -> None:
        """accept_both_improvements with no editor_output makes no changes."""
        from handlers.resolve import _apply_compound_resolution
        rows = self._make_rows()
        headers = self._make_headers()
        item = self._make_compound_item()
        item["chosen_option_id"] = "accept_both_improvements"
        # No editor_output set

        original_req = rows[0]["requirement"]
        changes, updated_rows = _apply_compound_resolution(item, rows, headers, 0, [])
        self.assertEqual(changes, 0)
        self.assertEqual(updated_rows[0]["requirement"], original_req)


class RefineMergerFailureTests(unittest.TestCase):
    """Group G4 — merger agent failure in interactive loop returns gracefully."""

    def test_invoke_spec_change_merger_returns_none_on_error(self) -> None:
        """When merger agent raises, _invoke_spec_change_merger returns None."""
        import tempfile as _tf
        from handlers.resolve import _invoke_spec_change_merger

        with _tf.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()

            item = {
                "item_id": "merged_S1",
                "spec_id": "S1",
                "is_compound": True,
                "concerns": [],
            }
            config = {"agent": {"provider": "stub", "schema_validation_retries": 0}}
            ctx = _make_ctx(tmp)

            with patch("handlers.resolve.invoke_agent_with_schema_retry", side_effect=RuntimeError("agent failed")):
                result = _invoke_spec_change_merger(item, config, ctx, run_dir)

            self.assertIsNone(result)


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


# ---------------------------------------------------------------------------
# Group G: Consensus filtering
# ---------------------------------------------------------------------------

class ConsensusFilterTests(unittest.TestCase):
    """Tests for _filter_by_consensus()."""

    def test_all_instances_agree_keeps_item(self) -> None:
        instances = [
            [{"spec_id": "S1", "item_id": "AMB-001"}],
            [{"spec_id": "S1", "item_id": "AMB-002"}],
            [{"spec_id": "S1", "item_id": "AMB-003"}],
            [{"spec_id": "S1", "item_id": "AMB-004"}],
        ]
        result = _filter_by_consensus(instances, min_votes=3)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["spec_id"], "S1")

    def test_below_threshold_filters_out(self) -> None:
        instances = [
            [{"spec_id": "S1", "item_id": "AMB-001"}],
            [{"spec_id": "S1", "item_id": "AMB-002"}],
            [],
            [],
        ]
        result = _filter_by_consensus(instances, min_votes=3)
        self.assertEqual(len(result), 0)

    def test_exactly_at_threshold_keeps_item(self) -> None:
        instances = [
            [{"spec_id": "S1", "item_id": "AMB-001"}],
            [{"spec_id": "S1", "item_id": "AMB-002"}],
            [{"spec_id": "S1", "item_id": "AMB-003"}],
            [],
        ]
        result = _filter_by_consensus(instances, min_votes=3)
        self.assertEqual(len(result), 1)

    def test_mixed_spec_ids_partial_consensus(self) -> None:
        instances = [
            [{"spec_id": "S1", "item_id": "A1"}, {"spec_id": "S2", "item_id": "A2"}],
            [{"spec_id": "S1", "item_id": "B1"}],
            [{"spec_id": "S1", "item_id": "C1"}, {"spec_id": "S2", "item_id": "C2"}],
            [{"spec_id": "S2", "item_id": "D2"}],
        ]
        result = _filter_by_consensus(instances, min_votes=3)
        self.assertEqual(len(result), 2)
        spec_ids = {item["spec_id"] for item in result}
        self.assertEqual(spec_ids, {"S1", "S2"})

    def test_representative_from_first_instance(self) -> None:
        instances = [
            [{"spec_id": "S1", "item_id": "FIRST", "suggested_improvement": "first"}],
            [{"spec_id": "S1", "item_id": "SECOND", "suggested_improvement": "second"}],
            [{"spec_id": "S1", "item_id": "THIRD", "suggested_improvement": "third"}],
            [{"spec_id": "S1", "item_id": "FOURTH", "suggested_improvement": "fourth"}],
        ]
        result = _filter_by_consensus(instances, min_votes=3)
        self.assertEqual(result[0]["item_id"], "FIRST")

    def test_empty_instances_returns_empty(self) -> None:
        instances: list[list[dict[str, Any]]] = [[], [], [], []]
        result = _filter_by_consensus(instances, min_votes=3)
        self.assertEqual(result, [])

    def test_single_replica_threshold_one(self) -> None:
        instances = [[{"spec_id": "S1", "item_id": "A1"}]]
        result = _filter_by_consensus(instances, min_votes=1)
        self.assertEqual(len(result), 1)

    def test_duplicate_spec_id_in_single_instance_counts_once(self) -> None:
        instances = [
            [{"spec_id": "S1", "item_id": "A1"}, {"spec_id": "S1", "item_id": "A2"}],
            [],
            [],
            [],
        ]
        result = _filter_by_consensus(instances, min_votes=2)
        self.assertEqual(len(result), 0)

    def test_results_sorted_by_spec_id(self) -> None:
        instances = [
            [{"spec_id": "S3", "item_id": "A"}, {"spec_id": "S1", "item_id": "B"}],
            [{"spec_id": "S3", "item_id": "C"}, {"spec_id": "S1", "item_id": "D"}],
            [{"spec_id": "S3", "item_id": "E"}, {"spec_id": "S1", "item_id": "F"}],
        ]
        result = _filter_by_consensus(instances, min_votes=3)
        self.assertEqual([r["spec_id"] for r in result], ["S1", "S3"])


# ---------------------------------------------------------------------------
# Group G2: Config — agent_replicas and consensus_min_votes
# ---------------------------------------------------------------------------

class RefineConsensusConfigTests(unittest.TestCase):
    """Tests for agent_replicas and consensus_min_votes config parsing."""

    def test_agent_replicas_default(self) -> None:
        cfg = _get_refine_cfg({})
        self.assertEqual(cfg["agent_replicas"], 4)

    def test_consensus_min_votes_default(self) -> None:
        cfg = _get_refine_cfg({})
        self.assertEqual(cfg["consensus_min_votes"], 3)

    def test_custom_agent_replicas(self) -> None:
        config = {"commands": {"refine": {"agent_replicas": 6}}}
        cfg = _get_refine_cfg(config)
        self.assertEqual(cfg["agent_replicas"], 6)

    def test_agent_replicas_minimum_one(self) -> None:
        config = {"commands": {"refine": {"agent_replicas": 0}}}
        cfg = _get_refine_cfg(config)
        self.assertEqual(cfg["agent_replicas"], 1)

    def test_consensus_min_votes_clamped_to_replicas(self) -> None:
        config = {"commands": {"refine": {"agent_replicas": 2, "consensus_min_votes": 5}}}
        cfg = _get_refine_cfg(config)
        self.assertEqual(cfg["consensus_min_votes"], 2)

    def test_consensus_min_votes_minimum_one(self) -> None:
        config = {"commands": {"refine": {"consensus_min_votes": 0}}}
        cfg = _get_refine_cfg(config)
        self.assertEqual(cfg["consensus_min_votes"], 1)

    def test_invalid_replicas_falls_back_to_default(self) -> None:
        config = {"commands": {"refine": {"agent_replicas": "bad"}}}
        cfg = _get_refine_cfg(config)
        self.assertEqual(cfg["agent_replicas"], 4)


# ---------------------------------------------------------------------------
# Group G3: Consensus integration in full pipeline
# ---------------------------------------------------------------------------

class RefineConsensusIntegrationTests(unittest.TestCase):
    """Integration tests for consensus filtering in the full refine pipeline."""

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

    def test_low_agreement_items_filtered_out(self) -> None:
        """Items flagged by fewer than consensus_min_votes instances are dropped."""
        call_count = {"ambiguity": 0, "testability": 0}

        def fake_invoke(prompt_name: str = "", **_kwargs: Any) -> dict:
            if "ambiguity" in prompt_name:
                call_count["ambiguity"] += 1
                # Only first instance flags S1
                if call_count["ambiguity"] == 1:
                    return _ambiguity_items_output()
                return _empty_agent_output()
            call_count["testability"] += 1
            return _empty_agent_output()

        with patch(
            "handlers.refine.impl.invoke_agent_with_schema_retry",
            side_effect=fake_invoke,
        ):
            result = run_refine(self._config(), self._ctx())

        # S1 only flagged by 1/4 instances (< 3), so filtered out
        self.assertEqual(result["status"], "completed")
        self.assertIn("specs_enriched", result)

    def test_high_agreement_items_kept(self) -> None:
        """Items flagged by >= consensus_min_votes instances are kept."""
        call_count = {"ambiguity": 0}

        def fake_invoke(prompt_name: str = "", **_kwargs: Any) -> dict:
            if "ambiguity" in prompt_name:
                call_count["ambiguity"] = call_count.get("ambiguity", 0) + 1
                # First 3 instances flag S1 (meets threshold of 3)
                if call_count["ambiguity"] <= 3:
                    return _ambiguity_items_output()
                return _empty_agent_output()
            return _empty_agent_output()

        with patch(
            "handlers.refine.impl.invoke_agent_with_schema_retry",
            side_effect=fake_invoke,
        ):
            result = run_refine(self._config(), self._ctx())

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocking_items"], 1)

    def test_consensus_meta_json_written(self) -> None:
        """consensus_meta.json is written with pre/post counts."""
        def fake_invoke(prompt_name: str = "", **_kwargs: Any) -> dict:
            if "ambiguity" in prompt_name:
                return _ambiguity_items_output()
            return _empty_agent_output()

        run_dir = Path(self.tmp) / "out" / "agent_runs" / "refine" / "test-run"
        with patch(
            "handlers.refine.impl.invoke_agent_with_schema_retry",
            side_effect=fake_invoke,
        ):
            run_refine(self._config(), self._ctx())

        meta_path = run_dir / "consensus_meta.json"
        self.assertTrue(meta_path.exists())
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertEqual(meta["agent_replicas"], 4)
        self.assertEqual(meta["consensus_min_votes"], 3)
        # 4 instances each return 1 ambiguity item
        self.assertEqual(meta["ambiguity_pre_consensus"], 4)
        self.assertEqual(meta["ambiguity_post_consensus"], 1)

    def test_per_instance_output_files_written(self) -> None:
        """Individual per-instance output files are written."""
        def fake_invoke(prompt_name: str = "", **_kwargs: Any) -> dict:
            return _empty_agent_output()

        run_dir = Path(self.tmp) / "out" / "agent_runs" / "refine" / "test-run"
        with patch(
            "handlers.refine.impl.invoke_agent_with_schema_retry",
            side_effect=fake_invoke,
        ):
            run_refine(self._config(), self._ctx())

        for i in range(4):
            self.assertTrue((run_dir / f"ambiguity_output_{i}.json").exists())
            self.assertTrue((run_dir / f"testability_output_{i}.json").exists())


# ---------------------------------------------------------------------------
# Group I: Phase-only modes
# ---------------------------------------------------------------------------

class PhaseOnlyModeTests(unittest.TestCase):
    """Tests for --load-validate-only, --decomposition-only, and --agents-only modes."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.tmp = self._tmp_dir.name
        self.design_csv = Path(self.tmp) / "DESIGN-SPEC.csv"
        _write_design_csv(self.design_csv)
        _write_project_context(Path(self.tmp))

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def _config(self, decomposition_enabled: bool = False, decomposition_blocking: bool = False) -> dict[str, Any]:
        cfg = _make_config(self.tmp, str(self.design_csv))
        cfg["commands"]["refine"]["decomposition"]["enabled"] = decomposition_enabled
        cfg["commands"]["refine"]["decomposition"]["blocking"] = decomposition_blocking
        return cfg

    def _ctx(self, phase_only: str | None = None, run_id: str = "test-run") -> RuntimeContext:
        return RuntimeContext(
            command="refine",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id=run_id,
            project_root=self.tmp,
            config_path="config/config.yaml",
            input_overrides={"design_spec_path": str(self.design_csv)},
            phase_only=phase_only,
        )

    def _mock_agents(self, output: dict[str, Any] | None = None):
        return patch(
            "handlers.refine.impl.invoke_agent_with_schema_retry",
            return_value=output or _empty_agent_output(),
        )

    # -------------------------------------------------------------------
    # load_validate_only
    # -------------------------------------------------------------------

    def test_load_validate_only_returns_correct_status(self) -> None:
        result = run_refine(self._config(), self._ctx("load_validate_only"))
        self.assertEqual(result["status"], "load_validate_only")
        self.assertEqual(result["command"], "refine")

    def test_load_validate_only_returns_spec_count(self) -> None:
        result = run_refine(self._config(), self._ctx("load_validate_only"))
        self.assertEqual(result["spec_count"], len(_SAMPLE_ROWS))

    def test_load_validate_only_returns_design_spec_path(self) -> None:
        result = run_refine(self._config(), self._ctx("load_validate_only"))
        self.assertIn("design_spec_path", result)
        self.assertTrue(result["design_spec_path"].endswith(".csv"))

    def test_load_validate_only_does_not_create_run_dir(self) -> None:
        run_dir = Path(self.tmp) / "out" / "agent_runs" / "refine" / "test-run"
        run_refine(self._config(), self._ctx("load_validate_only"))
        self.assertFalse(run_dir.exists())

    def test_load_validate_only_does_not_invoke_agents(self) -> None:
        with self._mock_agents() as mock_agent:
            run_refine(self._config(), self._ctx("load_validate_only"))
        mock_agent.assert_not_called()

    def test_load_validate_only_invalid_csv_returns_failed(self) -> None:
        bad_csv = Path(self.tmp) / "bad.csv"
        bad_csv.write_text("spec_id,module_tag\nS1,core\n", encoding="utf-8")
        ctx = RuntimeContext(
            command="refine",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="test-run",
            project_root=self.tmp,
            config_path="config/config.yaml",
            input_overrides={"design_spec_path": str(bad_csv)},
            phase_only="load_validate_only",
        )
        result = run_refine(self._config(), ctx)
        self.assertEqual(result["status"], "failed")

    def test_load_validate_only_missing_file_returns_skipped(self) -> None:
        ctx = RuntimeContext(
            command="refine",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="test-run",
            project_root=self.tmp,
            config_path="config/config.yaml",
            input_overrides={"design_spec_path": str(Path(self.tmp) / "no_such_file.csv")},
            phase_only="load_validate_only",
        )
        result = run_refine(self._config(), ctx)
        self.assertEqual(result["status"], "skipped")

    # -------------------------------------------------------------------
    # decomposition_only
    # -------------------------------------------------------------------

    def _decomp_patch(self, split: int = 0, merge: int = 0, skipped: bool = False):
        return patch(
            "handlers.refine.impl.run_decomposition_check",
            return_value={
                "split_candidates": [{"spec_id": f"S{i}", "variance": 0.2, "reason": "r"} for i in range(split)],
                "merge_candidates": [{"spec_ids": [f"S{i}", f"S{i+1}"], "similarity": 0.9, "reason": "r"} for i in range(merge)],
                "skipped": skipped,
            },
        )

    def test_decomposition_only_returns_correct_status(self) -> None:
        with self._decomp_patch():
            result = run_refine(self._config(), self._ctx("decomposition_only"))
        self.assertEqual(result["status"], "decomposition_only")
        self.assertEqual(result["command"], "refine")

    def test_decomposition_only_returns_run_id(self) -> None:
        with self._decomp_patch():
            result = run_refine(self._config(), self._ctx("decomposition_only", run_id="decomp-run"))
        self.assertEqual(result["run_id"], "decomp-run")

    def test_decomposition_only_returns_candidate_counts(self) -> None:
        with self._decomp_patch(split=1, merge=2):
            result = run_refine(self._config(), self._ctx("decomposition_only"))
        self.assertEqual(result["split_candidates"], 1)
        self.assertEqual(result["merge_candidates"], 2)
        self.assertFalse(result["skipped"])

    def test_decomposition_only_creates_run_dir_and_flags_file(self) -> None:
        run_dir = Path(self.tmp) / "out" / "agent_runs" / "refine" / "test-run"
        with self._decomp_patch():
            run_refine(self._config(), self._ctx("decomposition_only"))
        self.assertTrue((run_dir / "decomposition_flags.json").exists())

    def test_decomposition_only_runs_even_when_disabled_in_config(self) -> None:
        with self._decomp_patch() as mock_decomp:
            result = run_refine(self._config(decomposition_enabled=False), self._ctx("decomposition_only"))
        mock_decomp.assert_called_once()
        self.assertEqual(result["status"], "decomposition_only")

    def test_decomposition_only_does_not_invoke_agents(self) -> None:
        with self._decomp_patch():
            with self._mock_agents() as mock_agent:
                run_refine(self._config(), self._ctx("decomposition_only"))
        mock_agent.assert_not_called()

    def test_decomposition_only_bypasses_blocking_gate(self) -> None:
        with self._decomp_patch(split=1):
            result = run_refine(
                self._config(decomposition_blocking=True),
                self._ctx("decomposition_only"),
            )
        self.assertEqual(result["status"], "decomposition_only")

    def test_decomposition_only_invalid_csv_returns_failed(self) -> None:
        bad_csv = Path(self.tmp) / "bad.csv"
        bad_csv.write_text("spec_id,module_tag\nS1,core\n", encoding="utf-8")
        ctx = RuntimeContext(
            command="refine",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="test-run",
            project_root=self.tmp,
            config_path="config/config.yaml",
            input_overrides={"design_spec_path": str(bad_csv)},
            phase_only="decomposition_only",
        )
        result = run_refine(self._config(), ctx)
        self.assertEqual(result["status"], "failed")

    # -------------------------------------------------------------------
    # agents_only
    # -------------------------------------------------------------------

    def test_agents_only_no_issues_returns_completed(self) -> None:
        with self._mock_agents(_empty_agent_output()):
            result = run_refine(self._config(), self._ctx("agents_only"))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["command"], "refine")

    def test_agents_only_with_items_returns_blocked(self) -> None:
        with self._mock_agents(_ambiguity_items_output()):
            result = run_refine(self._config(), self._ctx("agents_only"))
        self.assertEqual(result["status"], "blocked")

    def test_agents_only_skips_decomposition_even_when_enabled_in_config(self) -> None:
        with patch("handlers.refine.impl.run_decomposition_check") as mock_decomp:
            with self._mock_agents(_empty_agent_output()):
                run_refine(self._config(decomposition_enabled=True), self._ctx("agents_only"))
        mock_decomp.assert_not_called()

    def test_agents_only_writes_skipped_decomposition_flags(self) -> None:
        run_dir = Path(self.tmp) / "out" / "agent_runs" / "refine" / "test-run"
        with self._mock_agents(_empty_agent_output()):
            run_refine(self._config(), self._ctx("agents_only"))
        flags_path = run_dir / "decomposition_flags.json"
        self.assertTrue(flags_path.exists())
        data = json.loads(flags_path.read_text(encoding="utf-8"))
        self.assertTrue(data.get("skipped"))

    def test_agents_only_creates_run_meta(self) -> None:
        run_dir = Path(self.tmp) / "out" / "agent_runs" / "refine" / "test-run"
        with self._mock_agents(_empty_agent_output()):
            run_refine(self._config(), self._ctx("agents_only"))
        self.assertTrue((run_dir / "run_meta.json").exists())

    def test_agents_only_completed_output_shape_matches_normal(self) -> None:
        with self._mock_agents(_empty_agent_output()):
            normal = run_refine(self._config(), self._ctx(None, run_id="normal-run"))
        with self._mock_agents(_empty_agent_output()):
            agents_only = run_refine(self._config(), self._ctx("agents_only", run_id="agents-run"))
        self.assertEqual(normal["status"], agents_only["status"])
        self.assertEqual(set(normal.keys()), set(agents_only.keys()))


if __name__ == "__main__":
    unittest.main()
