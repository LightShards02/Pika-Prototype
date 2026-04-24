"""Tests for evidence_harnesses: deterministic harness gates."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from handlers.implement.evidence_harnesses import (
    ALL_HARNESS_IDS,
    collect_harness_results,
    run_anchor_preservation,
    run_diff_size_sanity,
    run_forbidden_path_violation,
    run_syntax_check,
)


def _spec_outputs(diffs_by_spec: dict[str, list[dict]]) -> dict[str, dict]:
    return {
        sid: {"diffs": diffs, "mapped_test_cases": [], "summary": "ok"}
        for sid, diffs in diffs_by_spec.items()
    }


class SyntaxCheckTests(unittest.TestCase):
    def test_passes_on_valid_python(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "pkg").mkdir()
            (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
            (root / "pkg" / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
            outputs = _spec_outputs({"S1": [{"diff_id": "d1", "touched_files": ["pkg/a.py"]}]})
            results = run_syntax_check(root, outputs)
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0]["passed"])

    def test_fails_on_broken_python(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "pkg").mkdir()
            (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
            (root / "pkg" / "a.py").write_text("def f(\n", encoding="utf-8")
            outputs = _spec_outputs({"S1": [{"diff_id": "d1", "touched_files": ["pkg/a.py"]}]})
            results = run_syntax_check(root, outputs)
            self.assertFalse(results[0]["passed"])
            self.assertIn("pkg/a.py", results[0]["details"])

    def test_skipped_when_no_python(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "notes.md").write_text("hi", encoding="utf-8")
            outputs = _spec_outputs({"S1": [{"diff_id": "d1", "touched_files": ["notes.md"]}]})
            results = run_syntax_check(root, outputs)
            self.assertTrue(results[0]["passed"])
            self.assertIn("skipped", results[0]["details"])


class ForbiddenPathViolationTests(unittest.TestCase):
    def test_flags_touch_under_forbidden_prefix(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            outputs = _spec_outputs({"S1": [{"diff_id": "d1", "touched_files": ["docs/guide.md"]}]})
            results = run_forbidden_path_violation(root, outputs, ["docs/"])
            self.assertFalse(results[0]["passed"])
            self.assertIn("docs/guide.md", results[0]["details"])

    def test_no_violation_when_prefix_doesnt_match(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            outputs = _spec_outputs({"S1": [{"diff_id": "d1", "touched_files": ["src/a.py"]}]})
            results = run_forbidden_path_violation(root, outputs, ["docs/"])
            self.assertTrue(results[0]["passed"])

    def test_empty_forbidden_list_passes(self) -> None:
        with TemporaryDirectory() as td:
            outputs = _spec_outputs({"S1": [{"diff_id": "d1", "touched_files": ["anywhere/x.py"]}]})
            results = run_forbidden_path_violation(Path(td), outputs, [])
            self.assertTrue(results[0]["passed"])


class AnchorPreservationTests(unittest.TestCase):
    def test_passes_when_planned_symbol_present(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "m").mkdir()
            (root / "m" / "a.py").write_text("def handler():\n    return 1\n", encoding="utf-8")
            outputs = _spec_outputs({"S1": [{"diff_id": "d1", "touched_files": ["m/a.py"]}]})
            anchor_plans = {
                "m": {
                    "module_tag": "m",
                    "planned_anchors": [
                        {
                            "planned_file_path": "m/a.py",
                            "planned_symbol": "handler",
                            "spec_ids": ["S1"],
                        }
                    ],
                }
            }
            results = run_anchor_preservation(root, outputs, anchor_plans, {"S1": "m"})
            self.assertTrue(results[0]["passed"])

    def test_fails_when_planned_symbol_missing(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "m").mkdir()
            (root / "m" / "a.py").write_text("def other():\n    return 1\n", encoding="utf-8")
            outputs = _spec_outputs({"S1": [{"diff_id": "d1", "touched_files": ["m/a.py"]}]})
            anchor_plans = {
                "m": {
                    "module_tag": "m",
                    "planned_anchors": [
                        {
                            "planned_file_path": "m/a.py",
                            "planned_symbol": "handler",
                            "spec_ids": ["S1"],
                        }
                    ],
                }
            }
            results = run_anchor_preservation(root, outputs, anchor_plans, {"S1": "m"})
            self.assertFalse(results[0]["passed"])
            self.assertIn("handler", results[0]["details"])


class DiffSizeSanityTests(unittest.TestCase):
    def test_flags_empty_diff(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "patch.diff").write_text("", encoding="utf-8")
            outputs = _spec_outputs(
                {"S1": [{"diff_id": "d1", "diff_path": "patch.diff", "touched_files": ["a.py"]}]}
            )
            results = run_diff_size_sanity(root, outputs, max_lines=2000)
            self.assertFalse(results[0]["passed"])
            self.assertIn("empty diff", results[0]["details"])

    def test_flags_runaway_diff(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "patch.diff").write_text("x\n" * 50, encoding="utf-8")
            outputs = _spec_outputs(
                {"S1": [{"diff_id": "d1", "diff_path": "patch.diff", "touched_files": ["a.py"]}]}
            )
            results = run_diff_size_sanity(root, outputs, max_lines=10)
            self.assertFalse(results[0]["passed"])

    def test_passes_within_bounds(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "patch.diff").write_text("x\n" * 50, encoding="utf-8")
            outputs = _spec_outputs(
                {"S1": [{"diff_id": "d1", "diff_path": "patch.diff", "touched_files": ["a.py"]}]}
            )
            results = run_diff_size_sanity(root, outputs, max_lines=2000)
            self.assertTrue(results[0]["passed"])


class CollectHarnessResultsTests(unittest.TestCase):
    def test_empty_enabled_list_returns_empty(self) -> None:
        with TemporaryDirectory() as td:
            results = collect_harness_results(
                enabled_harnesses=[],
                project_root=Path(td),
                spec_outputs={},
                forbidden_path_prefixes=[],
                anchor_plans_by_module={},
                spec_to_module_tag={},
            )
            self.assertEqual(results, [])

    def test_unknown_harness_is_ignored(self) -> None:
        with TemporaryDirectory() as td:
            results = collect_harness_results(
                enabled_harnesses=["does_not_exist", "forbidden_path_violation"],
                project_root=Path(td),
                spec_outputs={},
                forbidden_path_prefixes=[],
                anchor_plans_by_module={},
                spec_to_module_tag={},
            )
            harness_ids = {r["harness_id"] for r in results}
            self.assertEqual(harness_ids, {"forbidden_path_violation"})

    def test_all_known_harness_ids_supported(self) -> None:
        with TemporaryDirectory() as td:
            results = collect_harness_results(
                enabled_harnesses=list(ALL_HARNESS_IDS),
                project_root=Path(td),
                spec_outputs={},
                forbidden_path_prefixes=[],
                anchor_plans_by_module={},
                spec_to_module_tag={},
            )
            harness_ids = {r["harness_id"] for r in results}
            self.assertEqual(harness_ids, set(ALL_HARNESS_IDS))


if __name__ == "__main__":
    unittest.main()
