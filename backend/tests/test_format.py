"""Tests for handlers.format — enrichment phase."""

from __future__ import annotations

import csv
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "backend"))


def _make_csv(rows: list[dict[str, str]], headers: list[str] | None = None) -> str:
    if not rows:
        return ""
    hs = headers or list(rows[0].keys())
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=hs, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


class EnrichmentEnabledTests(unittest.TestCase):
    """Tests for _enrichment_enabled helper."""

    def test_returns_false_when_no_format_key(self) -> None:
        from handlers.format import _enrichment_enabled
        self.assertFalse(_enrichment_enabled({}))

    def test_returns_false_when_enrichment_absent(self) -> None:
        from handlers.format import _enrichment_enabled
        config = {"commands": {"format": {"enabled": True}}}
        self.assertFalse(_enrichment_enabled(config))

    def test_returns_false_when_enabled_false(self) -> None:
        from handlers.format import _enrichment_enabled
        config = {"commands": {"format": {"enrichment": {"enabled": False}}}}
        self.assertFalse(_enrichment_enabled(config))

    def test_returns_true_when_enabled_true(self) -> None:
        from handlers.format import _enrichment_enabled
        config = {"commands": {"format": {"enrichment": {"enabled": True}}}}
        self.assertTrue(_enrichment_enabled(config))


class EnrichmentSkipFilledTests(unittest.TestCase):
    """Tests for _enrichment_skip_filled helper."""

    def test_defaults_to_true_when_absent(self) -> None:
        from handlers.format import _enrichment_skip_filled
        self.assertTrue(_enrichment_skip_filled({}))

    def test_respects_false(self) -> None:
        from handlers.format import _enrichment_skip_filled
        config = {"commands": {"format": {"enrichment": {"skip_filled": False}}}}
        self.assertFalse(_enrichment_skip_filled(config))


class FormatEnrichmentApplyTests(unittest.TestCase):
    """Integration-style tests for _run_format_enrichment (agent mocked)."""

    def _write_csv(self, path: Path, rows: list[dict[str, str]]) -> None:
        headers = list(rows[0].keys()) if rows else []
        path.write_text(_make_csv(rows, headers), encoding="utf-8")

    def _make_ctx(self, project_root: str) -> MagicMock:
        ctx = MagicMock()
        ctx.project_root = project_root
        ctx.run_id = "test-run-id-0000"
        ctx.command = "format"
        ctx.dry_run = False
        return ctx

    def _base_config(self) -> dict:
        return {
            "agent": {"provider": "stub"},
            "commands": {
                "format": {
                    "enrichment": {"enabled": True, "skip_filled": True},
                }
            },
        }

    def test_apply_enrichment_fills_module_role_evidence_type_and_criteria(self) -> None:
        """Agent output is applied: module_role + evidence_type + acceptance_criteria columns filled."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_file = tmp_path / "DESIGN-SPEC.csv"
            rows = [
                {
                    "spec_id": "A1",
                    "module_tag": "auth",
                    "requirement": "Users can log in",
                    "module_role": "",
                    "evidence_type": "",
                    "acceptance_criteria": "",
                },
                {
                    "spec_id": "A2",
                    "module_tag": "auth",
                    "requirement": "Session expires after 30 min",
                    "module_role": "",
                    "evidence_type": "",
                    "acceptance_criteria": "",
                },
            ]
            self._write_csv(out_file, rows)

            agent_output = {
                "modules": [{"module_tag": "auth", "module_role": "domain"}],
                "specs": [
                    {"spec_id": "A1", "evidence_type": "test_execution_record", "acceptance_criteria": "Given valid credentials, user is authenticated."},
                    {"spec_id": "A2", "evidence_type": "audit_trail", "acceptance_criteria": "Session token expires after 30 minutes of inactivity."},
                ],
            }

            config = self._base_config()
            ctx = self._make_ctx(tmp)

            with patch("handlers.format.invoke_agent_with_schema_retry", return_value=agent_output), \
                 patch("handlers.format.get_agent_provider", return_value="stub"), \
                 patch("handlers.format.get_prompt_name", return_value="design_doc_enricher"), \
                 patch("handlers.format.resolve_output_schema_path", return_value=None), \
                 patch("handlers.format.resolve_project_context_content", return_value=""), \
                 patch("handlers.format.resolve_project_state_path", return_value=None):
                from handlers.format import _run_format_enrichment
                _run_format_enrichment(config, ctx, out_file)

            result_text = out_file.read_text(encoding="utf-8")
            reader = csv.DictReader(result_text.splitlines())
            result_rows = list(reader)

            self.assertEqual(result_rows[0]["module_role"], "domain")
            self.assertEqual(result_rows[1]["module_role"], "domain")
            self.assertEqual(result_rows[0]["evidence_type"], "test_execution_record")
            self.assertEqual(result_rows[1]["evidence_type"], "audit_trail")
            self.assertIn("authenticated", result_rows[0]["acceptance_criteria"])
            self.assertIn("inactivity", result_rows[1]["acceptance_criteria"])

    def test_apply_enrichment_na_evidence_type_sets_na_criteria(self) -> None:
        """When evidence_type is NA, acceptance_criteria is also NA."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_file = tmp_path / "DESIGN-SPEC.csv"
            rows = [
                {
                    "spec_id": "A1",
                    "module_tag": "docs",
                    "requirement": "Provide user manual",
                    "module_role": "",
                    "evidence_type": "",
                    "acceptance_criteria": "",
                },
            ]
            self._write_csv(out_file, rows)

            agent_output = {
                "modules": [{"module_tag": "docs", "module_role": "shared"}],
                "specs": [
                    {"spec_id": "A1", "evidence_type": "NA", "acceptance_criteria": "NA"},
                ],
            }

            config = self._base_config()
            ctx = self._make_ctx(tmp)

            with patch("handlers.format.invoke_agent_with_schema_retry", return_value=agent_output), \
                 patch("handlers.format.get_agent_provider", return_value="stub"), \
                 patch("handlers.format.get_prompt_name", return_value="design_doc_enricher"), \
                 patch("handlers.format.resolve_output_schema_path", return_value=None), \
                 patch("handlers.format.resolve_project_context_content", return_value=""), \
                 patch("handlers.format.resolve_project_state_path", return_value=None):
                from handlers.format import _run_format_enrichment
                _run_format_enrichment(config, ctx, out_file)

            result_text = out_file.read_text(encoding="utf-8")
            reader = csv.DictReader(result_text.splitlines())
            result_rows = list(reader)

            self.assertEqual(result_rows[0]["evidence_type"], "NA")
            self.assertEqual(result_rows[0]["acceptance_criteria"], "NA")

    def test_skip_filled_rows_not_overwritten(self) -> None:
        """Rows with existing module_role + evidence_type + acceptance_criteria are not overwritten."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_file = tmp_path / "DESIGN-SPEC.csv"
            rows = [
                {
                    "spec_id": "A1",
                    "module_tag": "auth",
                    "requirement": "Login",
                    "module_role": "Existing role",
                    "evidence_type": "test_execution_record",
                    "acceptance_criteria": "Existing criteria",
                },
            ]
            self._write_csv(out_file, rows)

            agent_output = {
                "modules": [],
                "specs": [],
            }

            config = self._base_config()
            ctx = self._make_ctx(tmp)

            with patch("handlers.format.invoke_agent_with_schema_retry", return_value=agent_output) as mock_agent, \
                 patch("handlers.format.get_agent_provider", return_value="stub"), \
                 patch("handlers.format.get_prompt_name", return_value="design_doc_enricher"), \
                 patch("handlers.format.resolve_output_schema_path", return_value=None), \
                 patch("handlers.format.resolve_project_context_content", return_value=""), \
                 patch("handlers.format.resolve_project_state_path", return_value=None):
                from handlers.format import _run_format_enrichment
                _run_format_enrichment(config, ctx, out_file)

            # Agent should not have been called — all rows already filled
            mock_agent.assert_not_called()

            result_text = out_file.read_text(encoding="utf-8")
            reader = csv.DictReader(result_text.splitlines())
            result_rows = list(reader)
            self.assertEqual(result_rows[0]["module_role"], "Existing role")
            self.assertEqual(result_rows[0]["evidence_type"], "test_execution_record")
            self.assertEqual(result_rows[0]["acceptance_criteria"], "Existing criteria")

    def test_enrichment_disabled_skips_agent(self) -> None:
        """When enrichment.enabled=false, _run_format_enrichment is never called."""
        config = {
            "agent": {"provider": "stub"},
            "commands": {
                "format": {
                    "enrichment": {"enabled": False},
                }
            },
        }
        from handlers.format import _enrichment_enabled
        self.assertFalse(_enrichment_enabled(config))


class ValidateDesignEnrichModuleRolesTests(unittest.TestCase):
    """Tests for validate_design_enrich_module_roles gate."""

    def test_rejects_role_not_in_allowed_set(self) -> None:
        from handlers.format import validate_design_enrich_module_roles

        with self.assertRaises(ValueError) as ctx:
            validate_design_enrich_module_roles(
                {"modules": [{"module_tag": "x", "module_role": "banana"}]},
                {"api", "domain"},
            )
        self.assertIn("banana", str(ctx.exception))
        self.assertIn("allowed_module_roles", str(ctx.exception))

    def test_accepts_case_insensitive_match(self) -> None:
        from handlers.format import validate_design_enrich_module_roles

        validate_design_enrich_module_roles(
            {"modules": [{"module_tag": "x", "module_role": "API"}]},
            {"api"},
        )

    def test_rejects_empty_module_role(self) -> None:
        from handlers.format import validate_design_enrich_module_roles

        with self.assertRaises(ValueError) as ctx:
            validate_design_enrich_module_roles(
                {"modules": [{"module_tag": "x", "module_role": "  "}]},
                {"api"},
            )
        self.assertIn("empty module_role", str(ctx.exception))

    def test_rejects_empty_allowed_set(self) -> None:
        from handlers.format import validate_design_enrich_module_roles

        with self.assertRaises(ValueError) as ctx:
            validate_design_enrich_module_roles(
                {"modules": [{"module_tag": "x", "module_role": "api"}]},
                set(),
            )
        self.assertIn("empty", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
