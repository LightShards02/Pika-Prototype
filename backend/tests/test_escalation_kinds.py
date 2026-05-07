"""Tests for typed escalation taxonomy on manual_resolution_items (Phase 1)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from core.constants import EscalationKind
from handlers.implement.evaluator import eval_failures_to_resolution_items
from handlers.implement.helpers import _manual_block

SCHEMAS_DIR = (
    Path(__file__).resolve().parents[1] / "schemas" / "agent_outputs"
)


def _write_initial_run_meta(run_dir: Path, command: str = "implement") -> Path:
    """Initialize a minimal run_meta.json so _manual_block can update it."""
    path = run_dir / "run_meta.json"
    path.write_text(
        json.dumps(
            {"command": command, "run_id": "test-run", "completed_stages": []},
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _make_item(item_id: str, *, kind: str | None = None) -> dict:
    """Build a minimal valid MR item; optionally set kind."""
    item = {
        "item_id": item_id,
        "title": f"Title {item_id}",
        "question": f"Q for {item_id}?",
        "options": [
            {"option_id": "accept", "label": "Accept", "effect": "Continue."}
        ],
        "blocking_reason": "Need user input.",
    }
    if kind is not None:
        item["kind"] = kind
    return item


class ManualBlockEscalationKindsTests(unittest.TestCase):
    def test_items_without_kind_default_to_generic_in_run_meta(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "manual_resolution").mkdir()
            _write_initial_run_meta(run_dir)

            items = [_make_item("I1"), _make_item("I2")]
            blocked = _manual_block(
                None,
                run_dir / "manual_resolution",
                "stage_x",
                run_dir=run_dir,
                command="implement",
                run_id="test-run",
                completed_stages=["a", "b"],
                items=items,
            )

            self.assertTrue(blocked)
            run_meta = json.loads(
                (run_dir / "run_meta.json").read_text(encoding="utf-8")
            )
            self.assertEqual(run_meta["blocked_at_stage"], "stage_x")
            self.assertEqual(run_meta["resolution_status"], "pending")
            self.assertEqual(run_meta["escalation_kinds"], ["generic"])

    def test_mixed_kinds_aggregated_sorted_and_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "manual_resolution").mkdir()
            _write_initial_run_meta(run_dir)

            items = [
                _make_item("I1", kind=EscalationKind.AMBIGUITY.value),
                _make_item("I2", kind=EscalationKind.SCOPE_CONFLICT.value),
                _make_item("I3", kind=EscalationKind.AMBIGUITY.value),
                _make_item("I4"),  # no kind → generic
            ]
            _manual_block(
                None,
                run_dir / "manual_resolution",
                "stage_y",
                run_dir=run_dir,
                command="implement",
                run_id="test-run",
                completed_stages=[],
                items=items,
            )

            run_meta = json.loads(
                (run_dir / "run_meta.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                run_meta["escalation_kinds"],
                ["ambiguity", "generic", "scope_conflict"],
            )

    def test_no_items_returns_false_and_does_not_set_escalation_kinds(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "manual_resolution").mkdir()
            _write_initial_run_meta(run_dir)

            blocked = _manual_block(
                None,
                run_dir / "manual_resolution",
                "stage_z",
                run_dir=run_dir,
                command="implement",
                run_id="test-run",
                completed_stages=[],
                items=[],
            )

            self.assertFalse(blocked)
            run_meta = json.loads(
                (run_dir / "run_meta.json").read_text(encoding="utf-8")
            )
            self.assertNotIn("escalation_kinds", run_meta)
            self.assertNotIn("blocked_at_stage", run_meta)

    def test_kind_persists_in_stage_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "manual_resolution").mkdir()
            _write_initial_run_meta(run_dir)

            item = _make_item("I1", kind=EscalationKind.LOOP_LIMIT_EXCEEDED.value)
            _manual_block(
                None,
                run_dir / "manual_resolution",
                "stage_q",
                run_dir=run_dir,
                command="implement",
                run_id="test-run",
                completed_stages=[],
                items=[item],
            )

            stage_json = json.loads(
                (run_dir / "manual_resolution" / "stage_q.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(stage_json["items"][0]["kind"], "loop_limit_exceeded")


class EvalFailuresToResolutionItemsKindTests(unittest.TestCase):
    def test_every_emitted_item_carries_code_eval_failure_kind(self) -> None:
        failed_specs = [
            {"spec_id": "S1", "severity": "blocker", "reason": "broken"},
            {"spec_id": "S2", "severity": "minor", "reason": "small thing"},
        ]
        items = eval_failures_to_resolution_items(failed_specs)
        self.assertEqual(len(items), 2)
        for item in items:
            self.assertEqual(item["kind"], EscalationKind.CODE_EVAL_FAILURE.value)


class MRItemSchemaKindTests(unittest.TestCase):
    """Verify both MR-item schemas accept the kind enum and reject bad values."""

    @staticmethod
    def _validator(schema_name: str) -> Draft202012Validator:
        path = SCHEMAS_DIR / schema_name
        return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))

    def _planner_payload_with_item(self, item_overrides: dict) -> dict:
        item = {
            "item_id": "I1",
            "title": "T",
            "question": "Q?",
            "options": [
                {"option_id": "ok", "label": "OK", "effect": "Continue."}
            ],
            "blocking_reason": "Needs input.",
        }
        item.update(item_overrides)
        return {
            "response_kind": "manual_block",
            "manual_resolution_items": [item],
            "module_plans": [],
            "spec_dependencies": [],
            "shared_contracts": [],
        }

    def _impl_payload_with_item(self, item_overrides: dict) -> dict:
        item = {
            "item_id": "I1",
            "title": "T",
            "question": "Q?",
            "options": [
                {"option_id": "ok", "label": "OK", "effect": "Continue."}
            ],
            "required": True,
            "blocking_reason": "Needs input.",
        }
        item.update(item_overrides)
        return {"manual_resolution_items": [item]}

    def test_planner_schema_accepts_optional_kind(self) -> None:
        v = self._validator("implement_unified_planner_output.schema.json")
        payload = self._planner_payload_with_item(
            {"kind": EscalationKind.AMBIGUITY.value}
        )
        self.assertEqual(list(v.iter_errors(payload)), [])

    def test_planner_schema_accepts_missing_kind(self) -> None:
        v = self._validator("implement_unified_planner_output.schema.json")
        payload = self._planner_payload_with_item({})
        self.assertEqual(list(v.iter_errors(payload)), [])

    def test_planner_schema_rejects_unknown_kind(self) -> None:
        v = self._validator("implement_unified_planner_output.schema.json")
        payload = self._planner_payload_with_item({"kind": "not_a_real_kind"})
        errors = list(v.iter_errors(payload))
        self.assertTrue(errors, "expected schema to reject unknown kind value")

    def test_implement_output_schema_accepts_optional_kind(self) -> None:
        v = self._validator("implement_output.schema.json")
        payload = self._impl_payload_with_item(
            {"kind": EscalationKind.AMENDMENT_UNSATISFIABLE.value}
        )
        self.assertEqual(list(v.iter_errors(payload)), [])

    def test_implement_output_schema_rejects_unknown_kind(self) -> None:
        v = self._validator("implement_output.schema.json")
        payload = self._impl_payload_with_item({"kind": "bogus"})
        errors = list(v.iter_errors(payload))
        self.assertTrue(errors, "expected schema to reject unknown kind value")

    def test_all_enum_values_accepted_by_both_schemas(self) -> None:
        planner_v = self._validator(
            "implement_unified_planner_output.schema.json"
        )
        impl_v = self._validator("implement_output.schema.json")
        for kind in EscalationKind:
            with self.subTest(kind=kind.value):
                self.assertEqual(
                    list(
                        planner_v.iter_errors(
                            self._planner_payload_with_item({"kind": kind.value})
                        )
                    ),
                    [],
                )
                self.assertEqual(
                    list(
                        impl_v.iter_errors(
                            self._impl_payload_with_item({"kind": kind.value})
                        )
                    ),
                    [],
                )


if __name__ == "__main__":
    unittest.main()
