"""Phase 6 tests: schema deprecation markers, test_plan promotion, migration script."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "schemas" / "agent_outputs"
SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
BACKEND_ROOT = Path(__file__).resolve().parents[1]


class CodeEvalSchemaDeprecationTests(unittest.TestCase):
    def test_code_eval_output_schema_marked_deprecated(self) -> None:
        schema_path = SCHEMAS_DIR / "code_eval_output.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertTrue(
            schema.get("deprecated", False),
            "code_eval_output.schema.json must be marked deprecated in P6.",
        )
        self.assertIn(
            "DEPRECATED",
            schema.get("description", ""),
            "code_eval_output.schema.json description must mention deprecation.",
        )

    def test_evaluator_module_docstring_mentions_deprecation(self) -> None:
        evaluator_path = (
            BACKEND_ROOT / "handlers" / "implement" / "evaluator.py"
        )
        text = evaluator_path.read_text(encoding="utf-8")
        # Module docstring is the first triple-quoted block in the file.
        self.assertIn(
            "DEPRECATED (P6)",
            text.split('"""')[1] if '"""' in text else "",
            "evaluator.py module docstring must mention DEPRECATED (P6).",
        )


class EnricherTestPlanPromotionTests(unittest.TestCase):
    def test_enrichment_item_required_includes_test_plan(self) -> None:
        schema_path = SCHEMAS_DIR / "spec_testability_enricher_output.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        enrichment = schema["$defs"]["enrichment_item"]
        self.assertIn(
            "test_plan",
            enrichment["required"],
            "P6: test_plan must be in enrichment_item.required",
        )

    def test_planned_test_cases_allows_empty_array(self) -> None:
        # NA-evidence_type specs and non-testable specs should still validate
        # with empty planned_test_cases — schema must not impose minItems.
        schema_path = SCHEMAS_DIR / "spec_testability_enricher_output.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        test_plan = schema["$defs"]["test_plan"]
        planned_cases = test_plan["properties"]["planned_test_cases"]
        self.assertNotIn(
            "minItems",
            planned_cases,
            "test_plan.planned_test_cases must allow empty arrays for NA specs",
        )


class MigrationScriptTests(unittest.TestCase):
    """The migration script reports specs missing test_plan side-files."""

    def _run_script(self, project_root: Path, design_spec: Path | None = None) -> subprocess.CompletedProcess:
        cmd = [
            sys.executable,
            str(SCRIPTS_DIR / "migrate_test_plans.py"),
            "--project-root", str(project_root),
        ]
        if design_spec is not None:
            cmd.extend(["--design-spec", str(design_spec)])
        return subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=str(BACKEND_ROOT))

    def _write_csv(self, path: Path, rows: list[dict[str, str]]) -> None:
        if not rows:
            return
        headers = list(rows[0].keys())
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            f.write(",".join(headers) + "\n")
            for row in rows:
                f.write(",".join(row.get(h, "") for h in headers) + "\n")

    def test_exit_code_zero_when_all_have_test_plan(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            csv_path = root / "out" / "state" / "REFINED-SPEC.csv"
            self._write_csv(csv_path, [
                {"spec_id": "S1", "acceptance_criteria": "AC1 text", "evidence_type": "test_execution_record"},
            ])
            tp_dir = root / "out" / "state" / "test_plans"
            tp_dir.mkdir(parents=True)
            (tp_dir / "S1.json").write_text(
                json.dumps({"spec_id": "S1", "test_plan": {"planned_test_cases": []}}),
                encoding="utf-8",
            )
            result = self._run_script(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("OK", result.stdout)

    def test_exit_code_one_when_missing_test_plan(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            csv_path = root / "out" / "state" / "REFINED-SPEC.csv"
            self._write_csv(csv_path, [
                {"spec_id": "S1", "acceptance_criteria": "AC1 text", "evidence_type": "test_execution_record"},
                {"spec_id": "S2", "acceptance_criteria": "AC2 text", "evidence_type": "system_log"},
            ])
            tp_dir = root / "out" / "state" / "test_plans"
            tp_dir.mkdir(parents=True)
            (tp_dir / "S1.json").write_text(
                json.dumps({"spec_id": "S1", "test_plan": {"planned_test_cases": []}}),
                encoding="utf-8",
            )
            # S2 has no side-file
            result = self._run_script(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("S2", result.stdout)
            self.assertIn("FOUND", result.stdout)

    def test_exit_code_two_when_design_spec_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # No CSV
            result = self._run_script(root)
            self.assertEqual(result.returncode, 2)
            self.assertIn("design spec CSV not found", result.stderr)


if __name__ == "__main__":
    unittest.main()
