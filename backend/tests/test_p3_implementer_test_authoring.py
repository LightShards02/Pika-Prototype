"""Phase 3 tests: implementer schema authored_test_cases + brief slicing + config."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from handlers.implement.batching import _build_batches, _build_briefs
from handlers.implement.config import _get_impl_cfg

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "agent_outputs"
    / "implement_output.schema.json"
)


def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def _spec_payload_with_overrides(spec_id: str, **spec_overrides) -> dict:
    base = {
        "summary": "Implements feature.",
        "diff_refs": ["d1"],
        "mapped_classes_functions": [],
        "mapped_test_cases": [],
    }
    base.update(spec_overrides)
    return {
        "run_summary": {"status": "success"},
        "diff_plan": [
            {
                "diff_id": "d1",
                "diff_path": "patches/d1.diff",
                "touched_files": ["mod/file.py"],
                "owner_spec_id": spec_id,
                "related_spec_ids": [spec_id],
                "file_path": "mod/file.py",
                "op": "modify",
            }
        ],
        spec_id: base,
    }


class AuthoredTestCasesSchemaTests(unittest.TestCase):
    def test_authored_test_cases_optional_omission_validates(self) -> None:
        v = _validator()
        payload = _spec_payload_with_overrides("S1")
        self.assertEqual(list(v.iter_errors(payload)), [])

    def test_authored_test_cases_well_formed_entry_validates(self) -> None:
        v = _validator()
        payload = _spec_payload_with_overrides(
            "S1",
            authored_test_cases=[
                {
                    "framework": "pytest",
                    "test_file": "mod/tests/test_foo.py",
                    "test_case": "test_handler_returns_z",
                    "covers_criteria_ids": ["AC1", "AC2"],
                    "diff_id": "d1",
                }
            ],
        )
        self.assertEqual(list(v.iter_errors(payload)), [])

    def test_covers_criteria_ids_pattern_rejects_non_ac(self) -> None:
        v = _validator()
        payload = _spec_payload_with_overrides(
            "S1",
            authored_test_cases=[
                {
                    "framework": "pytest",
                    "test_file": "f.py",
                    "test_case": "t",
                    "covers_criteria_ids": ["bogus"],
                    "diff_id": "d1",
                }
            ],
        )
        self.assertTrue(list(v.iter_errors(payload)))

    def test_covers_criteria_ids_min_items(self) -> None:
        v = _validator()
        payload = _spec_payload_with_overrides(
            "S1",
            authored_test_cases=[
                {
                    "framework": "pytest",
                    "test_file": "f.py",
                    "test_case": "t",
                    "covers_criteria_ids": [],
                    "diff_id": "d1",
                }
            ],
        )
        self.assertTrue(list(v.iter_errors(payload)))

    def test_authored_test_case_requires_diff_id(self) -> None:
        v = _validator()
        bad = {
            "framework": "pytest",
            "test_file": "f.py",
            "test_case": "t",
            "covers_criteria_ids": ["AC1"],
        }
        payload = _spec_payload_with_overrides("S1", authored_test_cases=[bad])
        self.assertTrue(list(v.iter_errors(payload)))


class BuildBriefsAcTestPlanSlicingTests(unittest.TestCase):
    """_build_briefs slices AC + test_plan maps per batch."""

    def _setup_two_batch_inputs(self) -> tuple:
        rows = [
            {"spec_id": "A1001", "module_tag": "API", "module_role": "api"},
            {"spec_id": "A1002", "module_tag": "API", "module_role": "api"},
        ]
        module_plans = {
            "API": {
                "module_tag": "API",
                "planned_anchors": [
                    {
                        "anchor_kind": "new_symbol",
                        "anchor_materialization_kind": "runtime_logic",
                        "planned_file_path": "API/a.py",
                        "spec_ids": ["A1001"],
                    },
                    {
                        "anchor_kind": "new_symbol",
                        "anchor_materialization_kind": "runtime_logic",
                        "planned_file_path": "API/b.py",
                        "spec_ids": ["A1002"],
                    },
                ],
            }
        }
        batch_plan = _build_batches(
            rows, [], {"max_specs_per_batch": 1, "max_files": 10},
            anchor_plans=module_plans,
        )
        impl = {
            "forbidden_paths": [],
            "budgets": {"max_specs_per_batch": 1, "max_files": 10},
            "verification_commands": [],
        }
        return rows, module_plans, batch_plan, impl

    def test_per_batch_slicing_includes_only_batch_specs(self) -> None:
        rows, module_plans, batch_plan, impl = self._setup_two_batch_inputs()
        ac_map = {
            "A1001": {"acceptance_criteria": "Given X, returns Z.", "evidence_type": "test_execution_record"},
            "A1002": {"acceptance_criteria": "Given Y, returns W.", "evidence_type": "system_log"},
        }
        tp_map = {
            "A1001": {"planned_test_cases": [{"test_id": "T1", "framework": "pytest", "target_file": "API/tests/test_a.py", "target_case": "test_a", "criteria_ids": ["AC1"], "rationale": "x"}]},
            # A1002 deliberately missing — confirms slicing tolerates partial coverage.
        }
        briefs = _build_briefs(
            rows, module_plans, [], [], batch_plan, impl,
            acceptance_criteria_map=ac_map, test_plan_map=tp_map,
        )

        a1001_brief = next(b for b in briefs if b["spec_rows"][0]["spec_id"] == "A1001")
        a1002_brief = next(b for b in briefs if b["spec_rows"][0]["spec_id"] == "A1002")

        self.assertEqual(set(a1001_brief["acceptance_criteria_for_batch"].keys()), {"A1001"})
        self.assertEqual(set(a1001_brief["test_plan_for_batch"].keys()), {"A1001"})

        self.assertEqual(set(a1002_brief["acceptance_criteria_for_batch"].keys()), {"A1002"})
        # A1002 had no test_plan in the input map → empty slice for that batch.
        self.assertEqual(a1002_brief["test_plan_for_batch"], {})

    def test_default_when_maps_are_none(self) -> None:
        rows, module_plans, batch_plan, impl = self._setup_two_batch_inputs()
        briefs = _build_briefs(rows, module_plans, [], [], batch_plan, impl)
        for brief in briefs:
            self.assertIn("acceptance_criteria_for_batch", brief)
            self.assertIn("test_plan_for_batch", brief)
            self.assertEqual(brief["acceptance_criteria_for_batch"], {})
            self.assertEqual(brief["test_plan_for_batch"], {})


class ImplementCfgTestAuthoringTests(unittest.TestCase):
    def _cfg(self, implementer_overrides: dict | None = None) -> dict:
        impl_block: dict = {
            "design_spec_path": "out/state/REFINED-SPEC.csv",
            "test_spec_path": "out/state/test_spec.csv",
        }
        if implementer_overrides is not None:
            impl_block["implementer"] = implementer_overrides
        return {"commands": {"implement": impl_block}}

    def test_default_author_tests_is_false(self) -> None:
        impl = _get_impl_cfg(self._cfg())
        self.assertFalse(impl["author_tests"])
        self.assertEqual(
            impl["test_authoring_required_for_evidence_kinds"],
            ["integration_test", "unit_test"],
        )

    def test_author_tests_true_from_implementer_block(self) -> None:
        impl = _get_impl_cfg(self._cfg({"author_tests": True}))
        self.assertTrue(impl["author_tests"])

    def test_test_authoring_kinds_filters_bogus_values(self) -> None:
        impl = _get_impl_cfg(
            self._cfg(
                {
                    "test_authoring_required_for_evidence_kinds": [
                        "unit_test",
                        "bogus_kind",
                        "manual_review",
                    ]
                }
            )
        )
        # Bogus filtered out; valid kinds preserved (sorted).
        self.assertEqual(
            impl["test_authoring_required_for_evidence_kinds"],
            ["manual_review", "unit_test"],
        )

    def test_test_authoring_kinds_empty_falls_back_to_default(self) -> None:
        impl = _get_impl_cfg(
            self._cfg(
                {"test_authoring_required_for_evidence_kinds": ["bogus_only"]}
            )
        )
        # Default tuple order is preserved when fallback fires after empty set.
        self.assertEqual(
            impl["test_authoring_required_for_evidence_kinds"],
            ["unit_test", "integration_test"],
        )

    def test_test_authoring_kinds_non_list_falls_back_to_default(self) -> None:
        impl = _get_impl_cfg(
            self._cfg({"test_authoring_required_for_evidence_kinds": "unit_test"})
        )
        # Non-list raw → reset to default tuple → sorted.
        self.assertEqual(
            impl["test_authoring_required_for_evidence_kinds"],
            ["integration_test", "unit_test"],
        )


if __name__ == "__main__":
    unittest.main()
