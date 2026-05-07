"""Phase 5 tests: stagnation, partial-spec lock-in, planner cache invalidation,
amendment_id determinism across iterations, and amend-prompt registration.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from handlers.implement.config import _get_impl_cfg
from handlers.implement.impl import _invalidate_planner_cache_after_ac_resolve
from handlers.implement.reviewer import (
    amendment_id_for,
    amendment_ids_in_packet,
    is_stagnant,
    out_of_scope_diff_ids,
)


class StagnationTests(unittest.TestCase):
    def test_zero_progress_is_stagnant(self) -> None:
        prior = {amendment_id_for("S1", "AC1", "code")}
        current = {
            "amendments": [
                {"amendment_id": amendment_id_for("S1", "AC1", "code")},
                {"amendment_id": amendment_id_for("S1", "AC2", "code")},
            ]
        }
        self.assertTrue(is_stagnant(current, prior))

    def test_first_iteration_never_stagnant(self) -> None:
        current = {
            "amendments": [
                {"amendment_id": amendment_id_for("S1", "AC1", "code")},
            ]
        }
        self.assertFalse(is_stagnant(current, set()))
        self.assertFalse(is_stagnant(current, None))

    def test_progress_clears_stagnation(self) -> None:
        prior = {amendment_id_for("S1", "AC1", "code")}
        current = {
            "amendments": [
                # Different criterion; prior amendment cleared.
                {"amendment_id": amendment_id_for("S1", "AC2", "code")},
            ]
        }
        self.assertFalse(is_stagnant(current, prior))

    def test_amendment_ids_in_packet_returns_strings(self) -> None:
        packet = {
            "amendments": [
                {"amendment_id": "S1::AC1::code"},
                {"amendment_id": "S2::AC3::test_evidence"},
                {},  # missing id silently skipped
                {"amendment_id": ""},  # empty silently skipped
            ]
        }
        self.assertEqual(
            amendment_ids_in_packet(packet),
            {"S1::AC1::code", "S2::AC3::test_evidence"},
        )


class OutOfScopeDiffTests(unittest.TestCase):
    def _diff(self, diff_id: str, owner: str) -> dict:
        return {
            "diff_id": diff_id,
            "owner_spec_id": owner,
            "diff_path": f"patches/{diff_id}.diff",
            "touched_files": [f"{owner.lower()}/file.py"],
            "related_spec_ids": [owner],
            "file_path": f"{owner.lower()}/file.py",
            "op": "modify",
        }

    def test_in_scope_diff_passes(self) -> None:
        diffs = [self._diff("d1", "S1"), self._diff("d2", "S2")]
        offenders = out_of_scope_diff_ids(diffs, target_spec_ids={"S1", "S2"})
        self.assertEqual(offenders, [])

    def test_non_target_owner_fails(self) -> None:
        diffs = [self._diff("d1", "S1"), self._diff("d2", "S99")]
        offenders = out_of_scope_diff_ids(diffs, target_spec_ids={"S1"})
        self.assertEqual(len(offenders), 1)
        self.assertEqual(offenders[0]["diff_id"], "d2")
        self.assertEqual(offenders[0]["offending_owner_spec_id"], "S99")

    def test_prior_owner_allowed_through(self) -> None:
        # S99 was an owner in the prior iteration; the implementer is
        # modifying that shared diff and is allowed.
        diffs = [self._diff("d1", "S99")]
        prior = [self._diff("d_prior", "S99")]
        offenders = out_of_scope_diff_ids(
            diffs, target_spec_ids={"S1"}, prior_diff_plan=prior,
        )
        self.assertEqual(offenders, [])

    def test_empty_diffs_returns_empty(self) -> None:
        self.assertEqual(
            out_of_scope_diff_ids([], target_spec_ids={"S1"}),
            [],
        )


class PlannerCacheInvalidationTests(unittest.TestCase):
    def test_archives_existing_unified_plan(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "unified_plan.json").write_text(
                json.dumps({"response_kind": "plan"}), encoding="utf-8"
            )
            stages = {"load", "catalog", "unified_planner", "plan_validation"}
            _invalidate_planner_cache_after_ac_resolve(run_dir, stages)
            self.assertFalse((run_dir / "unified_plan.json").exists())
            self.assertTrue((run_dir / "unified_plan_pre_resolve.json").exists())
            self.assertNotIn("unified_planner", stages)
            self.assertNotIn("plan_validation", stages)
            self.assertIn("load", stages)  # unrelated stages preserved
            self.assertIn("catalog", stages)

    def test_no_cached_plan_still_drops_stages(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)  # no unified_plan.json
            stages = {"unified_planner", "load"}
            _invalidate_planner_cache_after_ac_resolve(run_dir, stages)
            self.assertNotIn("unified_planner", stages)
            self.assertIn("load", stages)

    def test_idempotent_when_called_twice(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "unified_plan.json").write_text(
                json.dumps({"response_kind": "plan"}), encoding="utf-8"
            )
            stages = {"unified_planner"}
            _invalidate_planner_cache_after_ac_resolve(run_dir, stages)
            stages.discard("unified_planner")  # already discarded
            _invalidate_planner_cache_after_ac_resolve(run_dir, stages)  # second call no-op
            self.assertFalse((run_dir / "unified_plan.json").exists())
            self.assertTrue((run_dir / "unified_plan_pre_resolve.json").exists())


class AmendPromptRegistrationTests(unittest.TestCase):
    """The amend prompt is resolved per provider; falls back to full prompt when missing."""

    def _cfg(self, agent_provider: str = "stub") -> dict:
        return {
            "agent": {"provider": agent_provider},
            "commands": {
                "implement": {
                    "design_spec_path": "out/state/REFINED-SPEC.csv",
                    "test_spec_path": "out/state/test_spec.csv",
                }
            },
        }

    def test_amend_prompt_name_resolved_for_default_provider(self) -> None:
        impl = _get_impl_cfg(self._cfg(agent_provider="stub"))
        self.assertEqual(impl["amend_prompt_name"], "implement_from_specs_amend")

    def test_amend_prompt_name_resolved_for_local_provider(self) -> None:
        impl = _get_impl_cfg(self._cfg(agent_provider="local"))
        self.assertEqual(impl["amend_prompt_name"], "implement_from_specs_local_amend")


if __name__ == "__main__":
    unittest.main()
