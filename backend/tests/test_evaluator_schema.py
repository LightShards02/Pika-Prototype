"""Tests for code_eval_output.schema.json shape validation."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "agent_outputs"
    / "code_eval_output.schema.json"
)


def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


class CodeEvalOutputSchemaTests(unittest.TestCase):
    def test_minimal_passing_payload_validates(self) -> None:
        v = _validator()
        payload = {
            "passed": True,
            "criteria_assessment": [
                {
                    "spec_id": "S1",
                    "satisfied": True,
                    "evidence_summary": "syntax_check passed; AC met by login()",
                }
            ],
            "overall_rationale": "All specs satisfied.",
            "run_summary": {"status": "success"},
        }
        self.assertEqual(list(v.iter_errors(payload)), [])

    def test_missing_required_top_level_fails(self) -> None:
        v = _validator()
        payload = {
            "passed": True,
            "criteria_assessment": [],
            "run_summary": {"status": "success"},
        }
        errors = list(v.iter_errors(payload))
        self.assertTrue(any("overall_rationale" in str(e.message) for e in errors))

    def test_failed_spec_requires_severity_enum(self) -> None:
        v = _validator()
        payload = {
            "passed": False,
            "failed_specs": [
                {
                    "spec_id": "S1",
                    "reason": "missing audit emit",
                    "severity": "catastrophic",  # invalid enum
                }
            ],
            "criteria_assessment": [
                {
                    "spec_id": "S1",
                    "satisfied": False,
                    "evidence_summary": "no audit call observed",
                }
            ],
            "overall_rationale": "blocker present.",
            "run_summary": {"status": "failed"},
        }
        errors = list(v.iter_errors(payload))
        self.assertTrue(any("catastrophic" in str(e.message) or "enum" in str(e.message) for e in errors))

    def test_criterion_assessment_requires_evidence_summary_nonempty(self) -> None:
        v = _validator()
        payload = {
            "passed": True,
            "criteria_assessment": [
                {"spec_id": "S1", "satisfied": True, "evidence_summary": ""}
            ],
            "overall_rationale": "ok",
            "run_summary": {"status": "success"},
        }
        errors = list(v.iter_errors(payload))
        self.assertTrue(errors)

    def test_run_summary_status_enum(self) -> None:
        v = _validator()
        payload = {
            "passed": True,
            "criteria_assessment": [
                {"spec_id": "S1", "satisfied": True, "evidence_summary": "ok"}
            ],
            "overall_rationale": "ok",
            "run_summary": {"status": "weird"},
        }
        errors = list(v.iter_errors(payload))
        self.assertTrue(errors)
        self.assertTrue(
            any("weird" in str(e.message) or "enum" in str(e.message) for e in errors)
        )


if __name__ == "__main__":
    unittest.main()
