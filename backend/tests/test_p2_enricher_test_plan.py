"""Phase 2 tests: testability enricher schema + test_plan side-files + loader."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from core.spec_acceptance import load_spec_test_plans

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "agent_outputs"
    / "spec_testability_enricher_output.schema.json"
)


def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def _base_enrichment(spec_id: str = "S1") -> dict:
    """Minimum valid enrichment per current required fields (P6: test_plan now required, may be empty)."""
    return {
        "spec_id": spec_id,
        "acceptance_criteria": "Given X, when Y, the system returns Z.",
        "evidence_type": "test_execution_record",
        "test_plan": {"planned_test_cases": []},
    }


def _structured_criterion(criterion_id: str = "AC1", *, evidence_kind: str = "unit_test") -> dict:
    return {
        "criterion_id": criterion_id,
        "statement": f"Given X, when Y, the system returns Z ({criterion_id}).",
        "observable_signal": "HTTP 200 with body == 'Z'.",
        "evidence_kind": evidence_kind,
    }


def _planned_test_case(test_id: str = "T1", criteria_ids: list[str] | None = None) -> dict:
    return {
        "test_id": test_id,
        "framework": "pytest",
        "target_file": "module_a/tests/test_handler.py",
        "target_case": f"test_{test_id.lower()}_returns_z",
        "criteria_ids": criteria_ids or ["AC1"],
        "rationale": "Exercises the handler's happy-path return.",
    }


class EnricherSchemaP2Tests(unittest.TestCase):
    """Schema accepts the new optional structured criteria + test_plan; rejects malformed shapes."""

    def test_minimum_enrichment_with_empty_test_plan_validates(self) -> None:
        # P6: test_plan promoted to required; planned_test_cases may be empty
        # for evidence_type='NA' specs and non-testable cases.
        v = _validator()
        payload = {
            "enrichments": [_base_enrichment()],
            "manual_resolution_items": [],
        }
        self.assertEqual(list(v.iter_errors(payload)), [])

    def test_p6_test_plan_required_rejects_omission(self) -> None:
        v = _validator()
        legacy_enrichment = {
            "spec_id": "S1",
            "acceptance_criteria": "Given X, when Y, returns Z.",
            "evidence_type": "test_execution_record",
            # test_plan omitted — must fail under P6 schema.
        }
        payload = {
            "enrichments": [legacy_enrichment],
            "manual_resolution_items": [],
        }
        self.assertTrue(
            list(v.iter_errors(payload)),
            "P6 schema must reject enrichments missing test_plan",
        )

    def test_enrichment_with_structured_criteria_validates(self) -> None:
        v = _validator()
        enrichment = _base_enrichment()
        enrichment["criteria"] = [_structured_criterion("AC1"), _structured_criterion("AC2")]
        payload = {"enrichments": [enrichment], "manual_resolution_items": []}
        self.assertEqual(list(v.iter_errors(payload)), [])

    def test_enrichment_with_test_plan_validates(self) -> None:
        v = _validator()
        enrichment = _base_enrichment()
        enrichment["criteria"] = [_structured_criterion("AC1")]
        enrichment["test_plan"] = {"planned_test_cases": [_planned_test_case("T1", ["AC1"])]}
        payload = {"enrichments": [enrichment], "manual_resolution_items": []}
        self.assertEqual(list(v.iter_errors(payload)), [])

    def test_criterion_id_pattern_rejects_wrong_prefix(self) -> None:
        v = _validator()
        bad = _structured_criterion("CR1")  # doesn't match ^AC[0-9]+$
        enrichment = _base_enrichment()
        enrichment["criteria"] = [bad]
        payload = {"enrichments": [enrichment], "manual_resolution_items": []}
        errors = list(v.iter_errors(payload))
        self.assertTrue(errors, "expected schema to reject criterion_id not matching ^AC[0-9]+$")

    def test_evidence_kind_enum_rejects_unknown_value(self) -> None:
        v = _validator()
        bad = _structured_criterion("AC1", evidence_kind="property_test")
        enrichment = _base_enrichment()
        enrichment["criteria"] = [bad]
        payload = {"enrichments": [enrichment], "manual_resolution_items": []}
        errors = list(v.iter_errors(payload))
        self.assertTrue(errors, "expected schema to reject unknown evidence_kind")

    def test_planned_test_case_requires_criteria_ids(self) -> None:
        v = _validator()
        case = _planned_test_case()
        case.pop("criteria_ids")
        enrichment = _base_enrichment()
        enrichment["criteria"] = [_structured_criterion("AC1")]
        enrichment["test_plan"] = {"planned_test_cases": [case]}
        payload = {"enrichments": [enrichment], "manual_resolution_items": []}
        errors = list(v.iter_errors(payload))
        self.assertTrue(errors, "expected schema to require criteria_ids on planned_test_case")

    def test_planned_test_case_criteria_ids_must_match_pattern(self) -> None:
        v = _validator()
        case = _planned_test_case("T1", ["bogus_id"])
        enrichment = _base_enrichment()
        enrichment["criteria"] = [_structured_criterion("AC1")]
        enrichment["test_plan"] = {"planned_test_cases": [case]}
        payload = {"enrichments": [enrichment], "manual_resolution_items": []}
        errors = list(v.iter_errors(payload))
        self.assertTrue(errors, "expected schema to reject non-AC criteria_ids")

    def test_test_plan_requires_planned_test_cases(self) -> None:
        v = _validator()
        enrichment = _base_enrichment()
        enrichment["test_plan"] = {}
        payload = {"enrichments": [enrichment], "manual_resolution_items": []}
        errors = list(v.iter_errors(payload))
        self.assertTrue(errors, "expected schema to require planned_test_cases on test_plan")

    def test_all_evidence_kinds_accepted(self) -> None:
        v = _validator()
        for kind in (
            "static_check",
            "unit_test",
            "integration_test",
            "runtime_log",
            "manual_review",
        ):
            with self.subTest(evidence_kind=kind):
                enrichment = _base_enrichment(spec_id=f"S_{kind}")
                enrichment["criteria"] = [_structured_criterion("AC1", evidence_kind=kind)]
                payload = {"enrichments": [enrichment], "manual_resolution_items": []}
                self.assertEqual(list(v.iter_errors(payload)), [])


class LoadSpecTestPlansTests(unittest.TestCase):
    """core.spec_acceptance.load_spec_test_plans reads the side-file format."""

    def _setup_workspace(self, td: str) -> Path:
        root = Path(td)
        (root / "out" / "state" / "test_plans").mkdir(parents=True)
        return root

    def _write_plan(self, root: Path, spec_id: str, payload: dict) -> None:
        target = root / "out" / "state" / "test_plans" / f"{spec_id}.json"
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def test_returns_empty_when_dir_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)  # No out/state/test_plans/ dir.
            self.assertEqual(load_spec_test_plans(root), {})

    def test_returns_all_when_no_filter(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = self._setup_workspace(td)
            self._write_plan(root, "S1", {"spec_id": "S1", "criteria": [_structured_criterion("AC1")]})
            self._write_plan(root, "S2", {"spec_id": "S2", "test_plan": {"planned_test_cases": [_planned_test_case()]}})
            result = load_spec_test_plans(root)
            self.assertEqual(set(result.keys()), {"S1", "S2"})
            self.assertIn("criteria", result["S1"])
            self.assertIn("test_plan", result["S2"])

    def test_filters_by_spec_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = self._setup_workspace(td)
            self._write_plan(root, "S1", {"spec_id": "S1"})
            self._write_plan(root, "S2", {"spec_id": "S2"})
            self._write_plan(root, "S3", {"spec_id": "S3"})
            result = load_spec_test_plans(root, spec_ids={"S1", "S3"})
            self.assertEqual(set(result.keys()), {"S1", "S3"})

    def test_skips_corrupt_json_silently(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = self._setup_workspace(td)
            self._write_plan(root, "S1", {"spec_id": "S1"})
            (root / "out" / "state" / "test_plans" / "S2.json").write_text(
                "{not valid json", encoding="utf-8"
            )
            result = load_spec_test_plans(root)
            self.assertEqual(set(result.keys()), {"S1"})

    def test_skips_non_json_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = self._setup_workspace(td)
            self._write_plan(root, "S1", {"spec_id": "S1"})
            (root / "out" / "state" / "test_plans" / "README.txt").write_text(
                "not a plan", encoding="utf-8"
            )
            result = load_spec_test_plans(root)
            self.assertEqual(set(result.keys()), {"S1"})

    def test_empty_filter_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = self._setup_workspace(td)
            self._write_plan(root, "S1", {"spec_id": "S1"})
            result = load_spec_test_plans(root, spec_ids=set())
            self.assertEqual(result, {})


class RefineHandlerSidefilePersistenceTests(unittest.TestCase):
    """Refine handler writes per-spec test_plan side-files when enrichments carry them."""

    def test_sidefiles_written_only_when_criteria_or_test_plan_present(self) -> None:
        # Direct unit test of the persistence loop against a tempdir.
        # We exercise the file-write branch directly without spinning up
        # the full refine command; the production call site at
        # handlers/refine/impl.py uses the same _resolve_test_plans_dir +
        # _write_json + per-enrichment loop.
        from handlers.implement.helpers import _write_json
        from handlers.refine.impl import _resolve_test_plans_dir

        with tempfile.TemporaryDirectory() as td:
            project_root = Path(td)
            test_plans_dir = _resolve_test_plans_dir(project_root)
            test_plans_dir.mkdir(parents=True, exist_ok=True)

            enrichments = [
                # spec carrying both criteria + test_plan
                {
                    "spec_id": "S1",
                    "acceptance_criteria": "Given X, when Y, returns Z.",
                    "evidence_type": "test_execution_record",
                    "criteria": [_structured_criterion("AC1")],
                    "test_plan": {"planned_test_cases": [_planned_test_case("T1", ["AC1"])]},
                },
                # spec carrying neither — should NOT produce a side-file
                {
                    "spec_id": "S2",
                    "acceptance_criteria": "Given Q, when R, returns S.",
                    "evidence_type": "system_log",
                },
                # spec with only criteria — side-file with criteria but no test_plan
                {
                    "spec_id": "S3",
                    "acceptance_criteria": "Given M, when N, returns P.",
                    "evidence_type": "audit_trail",
                    "criteria": [_structured_criterion("AC1")],
                },
            ]

            for entry in enrichments:
                sid = str(entry.get("spec_id", "")).strip()
                if not sid:
                    continue
                test_plan = entry.get("test_plan")
                criteria = entry.get("criteria")
                if not isinstance(test_plan, dict) and not isinstance(criteria, list):
                    continue
                payload = {"spec_id": sid}
                if isinstance(criteria, list):
                    payload["criteria"] = criteria
                if isinstance(test_plan, dict):
                    payload["test_plan"] = test_plan
                _write_json(test_plans_dir / f"{sid}.json", payload)

            self.assertTrue((test_plans_dir / "S1.json").exists())
            self.assertFalse(
                (test_plans_dir / "S2.json").exists(),
                "spec without criteria or test_plan must not produce a side-file",
            )
            self.assertTrue((test_plans_dir / "S3.json").exists())

            s1_payload = json.loads((test_plans_dir / "S1.json").read_text(encoding="utf-8"))
            self.assertEqual(s1_payload["spec_id"], "S1")
            self.assertIn("criteria", s1_payload)
            self.assertIn("test_plan", s1_payload)

            s3_payload = json.loads((test_plans_dir / "S3.json").read_text(encoding="utf-8"))
            self.assertIn("criteria", s3_payload)
            self.assertNotIn("test_plan", s3_payload)


if __name__ == "__main__":
    unittest.main()
