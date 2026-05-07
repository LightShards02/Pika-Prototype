"""Phase 4 tests: reviewer schemas, synthesis pass, config, demotion rule."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from handlers.implement.config import _get_impl_cfg
from handlers.implement.reviewer import (
    AXIS_NAMES,
    PerSpecResult,
    amendment_id_for,
    synthesize_reviewer_output,
)

SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "schemas" / "agent_outputs"


def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(
        json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))
    )


def _axis_findings_all_pass() -> list[dict]:
    return [
        {"axis": axis, "status": "pass", "summary": f"{axis} ok."}
        for axis in AXIS_NAMES
    ]


def _per_spec(
    spec_id: str,
    axis_status: dict[str, str] | None = None,
    *,
    offending: dict[str, list[str]] | None = None,
    minor: list[dict] | None = None,
    block: dict | None = None,
) -> PerSpecResult:
    statuses = {axis: "pass" for axis in AXIS_NAMES}
    if axis_status:
        statuses.update(axis_status)
    findings: list[dict] = []
    for axis in AXIS_NAMES:
        entry = {
            "axis": axis,
            "status": statuses[axis],
            "summary": f"{axis} for {spec_id}",
        }
        if offending and axis in offending:
            entry["offending_criterion_ids"] = list(offending[axis])
        findings.append(entry)
    return PerSpecResult(
        spec_id=spec_id,
        axis_findings=findings,
        minor_findings=list(minor or []),
        block_recommendation=block,
    )


class PerSpecReviewerSchemaTests(unittest.TestCase):
    def test_minimal_per_spec_validates(self) -> None:
        v = _validator("reviewer_per_spec_output.schema.json")
        payload = {"spec_id": "S1", "axis_findings": _axis_findings_all_pass()}
        self.assertEqual(list(v.iter_errors(payload)), [])

    def test_axis_findings_must_have_four_entries(self) -> None:
        v = _validator("reviewer_per_spec_output.schema.json")
        payload = {
            "spec_id": "S1",
            "axis_findings": _axis_findings_all_pass()[:3],
        }
        self.assertTrue(list(v.iter_errors(payload)))

    def test_axis_enum_rejects_unknown(self) -> None:
        v = _validator("reviewer_per_spec_output.schema.json")
        bad = _axis_findings_all_pass()
        bad[0]["axis"] = "performance"
        payload = {"spec_id": "S1", "axis_findings": bad}
        self.assertTrue(list(v.iter_errors(payload)))

    def test_block_recommendation_kind_enum(self) -> None:
        v = _validator("reviewer_per_spec_output.schema.json")
        payload = {
            "spec_id": "S1",
            "axis_findings": _axis_findings_all_pass(),
            "block_recommendation": {"kind": "bogus", "reason": "x"},
        }
        self.assertTrue(list(v.iter_errors(payload)))


class FullReviewerSchemaTests(unittest.TestCase):
    def test_approve_branch_validates(self) -> None:
        v = _validator("reviewer_output.schema.json")
        payload = {
            "response_kind": "approve",
            "axis_findings": _axis_findings_all_pass(),
            "criteria_assessment": [
                {
                    "spec_id": "S1",
                    "criterion_id": "AC1",
                    "satisfied": True,
                    "evidence_summary": "All axes pass.",
                }
            ],
        }
        self.assertEqual(list(v.iter_errors(payload)), [])

    def test_amend_branch_validates(self) -> None:
        v = _validator("reviewer_output.schema.json")
        payload = {
            "response_kind": "amend",
            "axis_findings": _axis_findings_all_pass(),
            "amendment_packet": {
                "packet_id": "AMD_B0_iter1",
                "target_spec_ids": ["S1"],
                "amendments": [
                    {
                        "amendment_id": "S1::AC1::code",
                        "spec_id": "S1",
                        "criterion_id": "AC1",
                        "axis": "code",
                        "defect_summary": "code fails AC1",
                        "required_change": "Implement code that satisfies criterion AC1.",
                    }
                ],
            },
        }
        self.assertEqual(list(v.iter_errors(payload)), [])

    def test_manual_block_branch_validates(self) -> None:
        v = _validator("reviewer_output.schema.json")
        payload = {
            "response_kind": "manual_block",
            "axis_findings": _axis_findings_all_pass(),
            "manual_resolution_items": [
                {
                    "item_id": "reviewer_ambiguity_S1",
                    "title": "Reviewer ambiguity (specs: S1)",
                    "question": "How to proceed?",
                    "options": [
                        {"option_id": "edit_specs", "label": "Edit", "effect": "..."}
                    ],
                    "blocking_reason": "Spec is ambiguous.",
                    "kind": "ambiguity",
                }
            ],
        }
        self.assertEqual(list(v.iter_errors(payload)), [])

    def test_approve_rejects_amendment_packet(self) -> None:
        v = _validator("reviewer_output.schema.json")
        payload = {
            "response_kind": "approve",
            "axis_findings": _axis_findings_all_pass(),
            "criteria_assessment": [
                {
                    "spec_id": "S1",
                    "criterion_id": "AC1",
                    "satisfied": True,
                    "evidence_summary": "ok",
                }
            ],
            "amendment_packet": {
                "packet_id": "x",
                "target_spec_ids": ["S1"],
                "amendments": [],
            },
        }
        self.assertTrue(list(v.iter_errors(payload)))

    def test_amendment_id_pattern_enforced(self) -> None:
        v = _validator("reviewer_output.schema.json")
        payload = {
            "response_kind": "amend",
            "axis_findings": _axis_findings_all_pass(),
            "amendment_packet": {
                "packet_id": "p",
                "target_spec_ids": ["S1"],
                "amendments": [
                    {
                        "amendment_id": "bogus_id",
                        "spec_id": "S1",
                        "criterion_id": "AC1",
                        "axis": "code",
                        "defect_summary": "x",
                        "required_change": "y",
                    }
                ],
            },
        }
        self.assertTrue(list(v.iter_errors(payload)))


class AmendmentIdTests(unittest.TestCase):
    def test_amendment_id_is_canonical_string(self) -> None:
        self.assertEqual(amendment_id_for("S5", "AC2", "code"), "S5::AC2::code")

    def test_amendment_id_stable_regardless_of_required_change(self) -> None:
        # The required_change LLM-prose isn't part of identity.
        # Fingerprint depends only on (spec_id, criterion_id, axis).
        a = amendment_id_for("S1", "AC1", "test_evidence")
        b = amendment_id_for("S1", "AC1", "test_evidence")
        self.assertEqual(a, b)


class SynthesisDecisionTreeTests(unittest.TestCase):
    def test_all_pass_yields_approve(self) -> None:
        out = synthesize_reviewer_output(
            [_per_spec("S1"), _per_spec("S2")],
            iteration_index=1,
            batch_id="B0",
        )
        self.assertEqual(out["response_kind"], "approve")
        self.assertEqual(len(out["axis_findings"]), 4)
        for entry in out["axis_findings"]:
            self.assertEqual(entry["status"], "pass")

    def test_axis1_fail_yields_amend(self) -> None:
        result = _per_spec(
            "S1",
            {"code": "fail"},
            offending={"code": ["AC1"]},
        )
        out = synthesize_reviewer_output(
            [result], iteration_index=1, batch_id="B0",
        )
        self.assertEqual(out["response_kind"], "amend")
        amendments = out["amendment_packet"]["amendments"]
        self.assertEqual(len(amendments), 1)
        self.assertEqual(amendments[0]["amendment_id"], "S1::AC1::code")

    def test_demotion_axis1_passes_axis3_fails_yields_approve_with_minor(self) -> None:
        result = _per_spec(
            "S1",
            {"test_code": "fail"},
            offending={"test_code": ["AC2"]},
        )
        out = synthesize_reviewer_output(
            [result], iteration_index=1, batch_id="B0",
        )
        self.assertEqual(out["response_kind"], "approve")
        # Demoted finding lands in minor_findings.
        self.assertIn("minor_findings", out)
        minors = out["minor_findings"]
        self.assertTrue(any(m["axis"] == "test_code" and m["spec_id"] == "S1" for m in minors))

    def test_demotion_does_not_apply_when_axis1_also_fails(self) -> None:
        result = _per_spec(
            "S1",
            {"code": "fail", "test_code": "fail", "test_evidence": "fail"},
            offending={"code": ["AC1"], "test_code": ["AC1"], "test_evidence": ["AC1"]},
        )
        out = synthesize_reviewer_output(
            [result], iteration_index=1, batch_id="B0",
        )
        self.assertEqual(out["response_kind"], "amend")
        amendment_ids = {a["amendment_id"] for a in out["amendment_packet"]["amendments"]}
        # All three axis failures produce amendments because axis1 also failed.
        self.assertEqual(amendment_ids, {"S1::AC1::code", "S1::AC1::test_code", "S1::AC1::test_evidence"})

    def test_demotion_per_spec_independent(self) -> None:
        # S1: axis1 passes → axis3 fails demoted to minor.
        # S2: axis1 fails AND axis3 fails → both amend.
        s1 = _per_spec("S1", {"test_code": "fail"}, offending={"test_code": ["AC1"]})
        s2 = _per_spec(
            "S2",
            {"code": "fail", "test_code": "fail"},
            offending={"code": ["AC1"], "test_code": ["AC1"]},
        )
        out = synthesize_reviewer_output(
            [s1, s2], iteration_index=1, batch_id="B0",
        )
        self.assertEqual(out["response_kind"], "amend")
        amendment_ids = {a["amendment_id"] for a in out["amendment_packet"]["amendments"]}
        self.assertEqual(amendment_ids, {"S2::AC1::code", "S2::AC1::test_code"})
        minors = out.get("minor_findings", [])
        # S1's axis3 finding is in minor_findings.
        self.assertTrue(
            any(m["spec_id"] == "S1" and m["axis"] == "test_code" for m in minors)
        )

    def test_per_spec_minor_findings_passed_through(self) -> None:
        s1 = _per_spec(
            "S1",
            minor=[
                {"axis": "code", "criterion_id": "AC1", "summary": "Could be tighter."}
            ],
        )
        out = synthesize_reviewer_output(
            [s1], iteration_index=1, batch_id="B0",
        )
        self.assertEqual(out["response_kind"], "approve")
        self.assertIn("minor_findings", out)
        emitted = out["minor_findings"]
        self.assertTrue(
            any(
                m["spec_id"] == "S1"
                and m["axis"] == "code"
                and m["summary"] == "Could be tighter."
                for m in emitted
            )
        )

    def test_block_recommendation_ambiguity_yields_manual_block(self) -> None:
        s1 = _per_spec(
            "S1",
            block={"kind": "ambiguity", "reason": "AC contradicts itself."},
        )
        out = synthesize_reviewer_output(
            [s1], iteration_index=1, batch_id="B0",
        )
        self.assertEqual(out["response_kind"], "manual_block")
        items = out["manual_resolution_items"]
        self.assertEqual(items[0]["kind"], "ambiguity")

    def test_mutual_scope_conflict_yields_scope_conflict_block(self) -> None:
        s1 = _per_spec(
            "S1",
            block={"kind": "scope_conflict", "reason": "S1 vs S2", "conflicting_spec_ids": ["S2"]},
        )
        s2 = _per_spec(
            "S2",
            block={"kind": "scope_conflict", "reason": "S2 vs S1", "conflicting_spec_ids": ["S1"]},
        )
        out = synthesize_reviewer_output(
            [s1, s2], iteration_index=1, batch_id="B0",
        )
        self.assertEqual(out["response_kind"], "manual_block")
        self.assertEqual(out["manual_resolution_items"][0]["kind"], "scope_conflict")

    def test_one_sided_scope_conflict_falls_back_to_ambiguity(self) -> None:
        # S1 says scope_conflict with S2, but S2 doesn't reciprocate.
        s1 = _per_spec(
            "S1",
            block={"kind": "scope_conflict", "reason": "S1 vs S2", "conflicting_spec_ids": ["S2"]},
        )
        s2 = _per_spec("S2")
        out = synthesize_reviewer_output(
            [s1, s2], iteration_index=1, batch_id="B0",
        )
        self.assertEqual(out["response_kind"], "manual_block")
        self.assertEqual(out["manual_resolution_items"][0]["kind"], "ambiguity")

    def test_insufficient_evidence_with_escalate_yields_block(self) -> None:
        s1 = _per_spec("S1", {"code": "insufficient_evidence"})
        out = synthesize_reviewer_output(
            [s1], iteration_index=1, batch_id="B0",
            escalate_on_axes_insufficient_evidence=True,
        )
        self.assertEqual(out["response_kind"], "manual_block")

    def test_insufficient_evidence_without_escalate_yields_approve(self) -> None:
        s1 = _per_spec("S1", {"code": "insufficient_evidence"})
        out = synthesize_reviewer_output(
            [s1], iteration_index=1, batch_id="B0",
            escalate_on_axes_insufficient_evidence=False,
        )
        self.assertEqual(out["response_kind"], "approve")

    def test_synthesized_output_validates_against_full_schema(self) -> None:
        v = _validator("reviewer_output.schema.json")
        out = synthesize_reviewer_output(
            [_per_spec("S1"), _per_spec("S2")],
            iteration_index=1,
            batch_id="B0",
        )
        self.assertEqual(list(v.iter_errors(out)), [])

    def test_synthesized_amend_validates_against_full_schema(self) -> None:
        v = _validator("reviewer_output.schema.json")
        result = _per_spec(
            "S1",
            {"code": "fail"},
            offending={"code": ["AC1"]},
        )
        out = synthesize_reviewer_output(
            [result], iteration_index=1, batch_id="B0",
            criteria_text_lookup={"S1": {"AC1": "Given X, returns Z."}},
        )
        self.assertEqual(list(v.iter_errors(out)), [])


class ReviewerConfigTests(unittest.TestCase):
    def _cfg(self, reviewer_overrides: dict | None = None, verification_overrides: dict | None = None) -> dict:
        impl_block: dict = {
            "design_spec_path": "out/state/REFINED-SPEC.csv",
            "test_spec_path": "out/state/test_spec.csv",
        }
        if reviewer_overrides is not None:
            impl_block["reviewer"] = reviewer_overrides
        if verification_overrides is not None:
            impl_block["verification"] = verification_overrides
        return {"commands": {"implement": impl_block}}

    def test_reviewer_defaults(self) -> None:
        impl = _get_impl_cfg(self._cfg())
        rv = impl["reviewer"]
        self.assertFalse(rv["enabled"])
        self.assertEqual(rv["max_iterations"], 2)
        self.assertEqual(rv["max_parallel_per_spec"], 4)
        self.assertEqual(rv["per_spec_max_total_seconds"], 180)
        self.assertTrue(rv["escalate_on_axes_insufficient_evidence"])
        self.assertTrue(rv["demote_verification_to_evidence"])
        self.assertEqual(impl["verification_timeout_seconds"], 300)

    def test_reviewer_overrides_respected(self) -> None:
        impl = _get_impl_cfg(
            self._cfg(
                reviewer_overrides={
                    "enabled": True,
                    "max_iterations": 5,
                    "max_parallel_per_spec": 8,
                    "per_spec_max_total_seconds": 60,
                    "escalate_on_axes_insufficient_evidence": False,
                    "demote_verification_to_evidence": False,
                },
                verification_overrides={"timeout_seconds": 600},
            )
        )
        rv = impl["reviewer"]
        self.assertTrue(rv["enabled"])
        self.assertEqual(rv["max_iterations"], 5)
        self.assertEqual(rv["max_parallel_per_spec"], 8)
        self.assertEqual(rv["per_spec_max_total_seconds"], 60)
        self.assertFalse(rv["escalate_on_axes_insufficient_evidence"])
        self.assertFalse(rv["demote_verification_to_evidence"])
        self.assertEqual(impl["verification_timeout_seconds"], 600)

    def test_invalid_int_falls_back_to_default(self) -> None:
        impl = _get_impl_cfg(
            self._cfg(reviewer_overrides={"max_iterations": -1, "max_parallel_per_spec": "x"})
        )
        rv = impl["reviewer"]
        self.assertEqual(rv["max_iterations"], 2)
        self.assertEqual(rv["max_parallel_per_spec"], 4)


if __name__ == "__main__":
    unittest.main()
