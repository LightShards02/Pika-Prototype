"""Tests for core.format_sads."""

from __future__ import annotations

import unittest
from pathlib import Path

from core.format_sads import (
    build_agent_view_csv_content,
    get_design_spec_add_if_missing,
    truncate_cell,
    write_agent_view_csv,
    _normalize_sensitive_keywords,
    _unicode_to_latex,
    append_missing_columns,
    apply_keyword_replacement,
    assign_deterministic_ids,
    assign_sads_deterministic_ids,
    collapse_empty_columns_before_new,
    derive_contract_columns,
    flatten_sads_rows,
    load_sads_csv_or_xlsx,
    normalize_newlines_in_cells,
    normalize_raw_sads,
    rows_to_csv,
    write_id_mapping,
)


class WriteAgentViewCsvTests(unittest.TestCase):
    """Tests for write_agent_view_csv."""

    def test_writes_slim_csv_with_agent_columns_only(self) -> None:
        """Agent-view CSV contains only agent-relevant columns, no SRS/SADS lineage."""
        root = Path(__file__).parent / "test_data_format" / "agent_view"
        root.mkdir(parents=True, exist_ok=True)
        design_csv = root / "design.csv"
        design_csv.write_text(
            "KEY,SRS ID,SRS,SADS ID,UNIT,SADS,title,requirement,spec_id,subunit,map_status\n"
            "1,R001,foo,D001.01,SRV,bar,T1,R1,A1,S1,unmapped\n",
            encoding="utf-8",
        )
        out_csv = root / "agent_view.csv"
        try:
            content = write_agent_view_csv(design_csv, out_csv, dry_run=False)
            self.assertTrue(out_csv.exists())
            self.assertIn("spec_id", content)
            self.assertIn("title", content)
            self.assertIn("requirement", content)
            self.assertNotIn("SRS ID", content)
            self.assertNotIn("SADS ID", content)
            self.assertNotIn("KEY", content)
        finally:
            for f in (design_csv, out_csv):
                f.unlink(missing_ok=True)
            if root.exists():
                root.rmdir()

    def test_dry_run_does_not_write(self) -> None:
        """Dry-run returns content but does not write file."""
        root = Path(__file__).parent / "test_data_format" / "agent_view_dry"
        root.mkdir(parents=True, exist_ok=True)
        design_csv = root / "design.csv"
        design_csv.write_text("spec_id,title\nA1,Foo\n", encoding="utf-8")
        out_csv = root / "agent_view.csv"
        try:
            content = write_agent_view_csv(design_csv, out_csv, dry_run=True)
            self.assertIn("spec_id", content)
            self.assertFalse(out_csv.exists())
        finally:
            design_csv.unlink(missing_ok=True)
            if root.exists():
                root.rmdir()


class TruncateCellTests(unittest.TestCase):
    """Tests for truncate_cell."""

    def test_no_truncation_when_under_limit(self) -> None:
        """Returns original when value is shorter than max_chars."""
        self.assertEqual(truncate_cell("short", 100), "short")

    def test_truncation_appends_marker(self) -> None:
        """Truncated value ends with [truncated]."""
        result = truncate_cell("a" * 100, 20)
        self.assertTrue(result.endswith("[truncated]"))
        self.assertEqual(len(result), 20)

    def test_zero_max_chars_returns_original(self) -> None:
        """max_chars=0 means no limit."""
        long_val = "x" * 500
        self.assertEqual(truncate_cell(long_val, 0), long_val)


class BuildAgentViewCsvContentTests(unittest.TestCase):
    """Tests for build_agent_view_csv_content."""

    def test_truncates_acceptance_criteria_when_configured(self) -> None:
        """acceptance_criteria is truncated when max_acceptance_chars > 0."""
        headers = ["spec_id", "subunit", "title", "requirement", "acceptance_criteria"]
        rows = [
            {
                "spec_id": "A1",
                "subunit": "S1",
                "title": "Foo",
                "requirement": "Do X",
                "acceptance_criteria": "a" * 100,
            },
        ]
        content = build_agent_view_csv_content(
            headers, rows, max_acceptance_chars=20
        )
        self.assertIn("[truncated]", content)
        self.assertNotIn("a" * 100, content)


class GetDesignSpecAddIfMissingTests(unittest.TestCase):
    """Tests for get_design_spec_add_if_missing. Reads from pika.yaml."""

    def test_returns_list_from_pika_config(self) -> None:
        """Returns add_if_missing from pika.yaml csv_contracts."""
        result = get_design_spec_add_if_missing()
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)
        self.assertIn("spec_id", result)
        self.assertIn("map_status", result)


class LoadSadsTests(unittest.TestCase):
    """Tests for load_sads_csv_or_xlsx."""

    def test_load_csv_basic(self) -> None:
        """Load CSV with headers and rows."""
        path = Path(__file__).parent / "test_data_format" / "basic.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("title,requirement\nR1,Do X\nR2,Do Y\n", encoding="utf-8")
        try:
            headers, rows = load_sads_csv_or_xlsx(path)
            self.assertEqual(headers, ["title", "requirement"])
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0], {"title": "R1", "requirement": "Do X"})
            self.assertEqual(rows[1], {"title": "R2", "requirement": "Do Y"})
        finally:
            if path.exists():
                path.unlink()
            if path.parent.exists() and not any(path.parent.iterdir()):
                path.parent.rmdir()

    def test_load_csv_empty(self) -> None:
        """Load empty CSV returns empty rows."""
        path = Path(__file__).parent / "test_data_format" / "empty.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("title,requirement\n", encoding="utf-8")
        try:
            headers, rows = load_sads_csv_or_xlsx(path)
            self.assertEqual(headers, ["title", "requirement"])
            self.assertEqual(rows, [])
        finally:
            if path.exists():
                path.unlink()

    def test_load_unsupported_extension_raises(self) -> None:
        """Unsupported extension raises ValueError."""
        path = Path(__file__).parent / "test_data_format" / "unsupported.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
        try:
            with self.assertRaises(ValueError) as ctx:
                load_sads_csv_or_xlsx(path)
            self.assertIn("Unsupported", str(ctx.exception))
        finally:
            if path.exists():
                path.unlink()

    def test_load_csv_converts_unicode_to_latex(self) -> None:
        """Unicode math symbols in CSV are converted to LaTeX escapes on load."""
        path = Path(__file__).parent / "test_data_format" / "unicode_math.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "title,requirement\n"
            "Sum spec,Compute ∑ of values\n"
            "Micro,Length 3μm",
            encoding="utf-8",
        )
        try:
            headers, rows = load_sads_csv_or_xlsx(path)
            self.assertEqual(headers, ["title", "requirement"])
            self.assertEqual(len(rows), 2)
            # ∑ -> \sum, μ -> \ensuremath{\mu} (pylatexenc output)
            self.assertIn("\\sum", rows[0]["requirement"])
            self.assertIn("\\ensuremath{\\mu}", rows[1]["requirement"])
        finally:
            if path.exists():
                path.unlink()

    def test_load_csv_fallback_cp1252_on_utf8_decode_error(self) -> None:
        """CP1252-encoded file (e.g. Excel export) is read via fallback and converted to LaTeX."""
        path = Path(__file__).parent / "test_data_format" / "cp1252_micro.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        # 0xb5 is µ (micro) in cp1252; invalid UTF-8
        path.write_bytes(
            b"title,requirement\n"
            b"Micro,Length 3\xb5m\n"
        )
        try:
            headers, rows = load_sads_csv_or_xlsx(path)
            self.assertEqual(headers, ["title", "requirement"])
            self.assertEqual(len(rows), 1)
            # pylatexenc may output \ensuremath{\mu} or \textmu for µ
            self.assertTrue(
                "\\mu" in rows[0]["requirement"] or "\\textmu" in rows[0]["requirement"],
                f"Expected LaTeX mu in {rows[0]['requirement']!r}",
            )
        finally:
            if path.exists():
                path.unlink()


class UnicodeToLatexTests(unittest.TestCase):
    """Tests for _unicode_to_latex."""

    def test_ascii_unchanged(self) -> None:
        """ASCII strings including LaTeX are returned unchanged."""
        self.assertEqual(_unicode_to_latex(""), "")
        self.assertEqual(_unicode_to_latex("hello"), "hello")
        self.assertEqual(_unicode_to_latex(r"\sum"), r"\sum")

    def test_unicode_math_converted(self) -> None:
        """Unicode math symbols are converted to LaTeX."""
        result = _unicode_to_latex("∑")
        self.assertIn("sum", result)
        self.assertIn("\\", result)


class ApplyKeywordReplacementTests(unittest.TestCase):
    """Tests for apply_keyword_replacement."""

    def test_empty_mappings_returns_copy(self) -> None:
        """Empty mappings returns copied rows."""
        headers = ["title", "requirement"]
        rows = [{"title": "A", "requirement": "B"}]
        result = apply_keyword_replacement(headers, rows, [])
        self.assertEqual(result, rows)
        self.assertIsNot(result, rows)

    def test_whole_word_replacement(self) -> None:
        """Keywords replaced as whole words."""
        headers = ["title", "requirement"]
        rows = [
            {"title": "CONFIDENTIAL data", "requirement": "Keep CONFIDENTIAL safe"},
        ]
        mappings = [({"CONFIDENTIAL": "[REDACTED]"}, False)]
        result = apply_keyword_replacement(headers, rows, mappings)
        self.assertEqual(
            result[0]["title"], "[REDACTED] data"
        )
        self.assertEqual(
            result[0]["requirement"], "Keep [REDACTED] safe"
        )

    def test_case_insensitive_by_default(self) -> None:
        """When case_sensitive=False, replacement is case-insensitive."""
        headers = ["title"]
        rows = [
            {"title": "KGAS and kgas and KgAs"},
        ]
        mappings = [({"KGAS": "[SOFTWARE]"}, False)]
        result = apply_keyword_replacement(headers, rows, mappings)
        self.assertEqual(
            result[0]["title"], "[SOFTWARE] and [SOFTWARE] and [SOFTWARE]"
        )

    def test_case_sensitive_when_explicit(self) -> None:
        """When case_sensitive=True, only exact case matches."""
        headers = ["title"]
        rows = [
            {"title": "KGAS and kgas and KgAs"},
        ]
        mappings = [({"KGAS": "[SOFTWARE]"}, True)]
        result = apply_keyword_replacement(headers, rows, mappings)
        self.assertEqual(
            result[0]["title"], "[SOFTWARE] and kgas and KgAs"
        )

    def test_per_mapping_case_sensitivity(self) -> None:
        """Different mappings can have different case_sensitive settings."""
        headers = ["title"]
        rows = [
            {"title": "KGAS and QX MGR and qx mgr"},
        ]
        mappings = [
            ({"KGAS": "[SOFTWARE]"}, False),  # case-insensitive
            ({"QX MGR": "[PARTNER]"}, True),  # case-sensitive
        ]
        result = apply_keyword_replacement(headers, rows, mappings)
        # KGAS, kgas, KgAs all replaced; only QX MGR replaced, not qx mgr
        self.assertEqual(
            result[0]["title"], "[SOFTWARE] and [PARTNER] and qx mgr"
        )


class NormalizeSensitiveKeywordsTests(unittest.TestCase):
    """Tests for _normalize_sensitive_keywords (object format only)."""

    def test_object_format_required(self) -> None:
        """Each mapping must be {keywords: [...], case_sensitive?: bool}."""
        config = {
            "[REDACTED]": {"keywords": ["CONFIDENTIAL", "SECRET"]},
            "[INTERNAL]": {"keywords": ["internal"]},
        }
        result = _normalize_sensitive_keywords(config)
        self.assertEqual(len(result), 2)
        kd1, cs1 = result[0]
        self.assertEqual(kd1["CONFIDENTIAL"], "[REDACTED]")
        self.assertEqual(kd1["SECRET"], "[REDACTED]")
        self.assertFalse(cs1)
        kd2, cs2 = result[1]
        self.assertEqual(kd2["internal"], "[INTERNAL]")
        self.assertFalse(cs2)

    def test_skips_list_format(self) -> None:
        """List format (replacement -> [keywords]) is not supported; entry skipped."""
        config = {"[REDACTED]": ["CONFIDENTIAL", "SECRET"]}
        result = _normalize_sensitive_keywords(config)
        self.assertEqual(len(result), 0)

    def test_skips_legacy_string_format(self) -> None:
        """Legacy keyword -> replacement string is not supported; entry skipped."""
        config = {"CONFIDENTIAL": "[REDACTED]"}
        result = _normalize_sensitive_keywords(config)
        self.assertEqual(len(result), 0)

    def test_object_format_with_case_sensitive(self) -> None:
        """Object format {keywords: [...], case_sensitive: true} per mapping."""
        config = {
            "[SOFTWARE]": {"keywords": ["KGAS", "SAGK"], "case_sensitive": False},
            "[PARTNER]": {"keywords": ["QX MGR"], "case_sensitive": True},
        }
        result = _normalize_sensitive_keywords(config)
        self.assertEqual(len(result), 2)
        kd1, cs1 = result[0]
        self.assertEqual(kd1["KGAS"], "[SOFTWARE]")
        self.assertEqual(kd1["SAGK"], "[SOFTWARE]")
        self.assertFalse(cs1)
        kd2, cs2 = result[1]
        self.assertEqual(kd2["QX MGR"], "[PARTNER]")
        self.assertTrue(cs2)


class CollapseEmptyColumnsTests(unittest.TestCase):
    """Tests for collapse_empty_columns_before_new."""

    def test_no_empty_columns_unchanged(self) -> None:
        """Headers without empty columns are unchanged."""
        headers = ["SRS ID", "SRS", "SADS ID", "SADS"]
        result = collapse_empty_columns_before_new(headers)
        self.assertEqual(result, headers)

    def test_reduces_many_empty_to_two(self) -> None:
        """Many consecutive empty columns are reduced to 2."""
        headers = ["A", "B", "", "", "", "", "", "", "title", "requirement"]
        result = collapse_empty_columns_before_new(headers)
        self.assertEqual(result, ["A", "B", "", "", "title", "requirement"])

    def test_two_empty_unchanged(self) -> None:
        """Exactly 2 empty columns are kept."""
        headers = ["A", "B", "", "", "title"]
        result = collapse_empty_columns_before_new(headers)
        self.assertEqual(result, headers)

    def test_one_empty_unchanged(self) -> None:
        """Single empty column is kept."""
        headers = ["A", "B", "", "title"]
        result = collapse_empty_columns_before_new(headers)
        self.assertEqual(result, headers)

    def test_custom_max_empty(self) -> None:
        """Custom max_empty is respected."""
        headers = ["A", "", "", "", "", "B"]
        result = collapse_empty_columns_before_new(headers, max_empty=1)
        self.assertEqual(result, ["A", "", "B"])


class AppendMissingColumnsTests(unittest.TestCase):
    """Tests for append_missing_columns."""

    def test_appends_missing_columns(self) -> None:
        """Missing contract columns are appended."""
        headers = ["title", "requirement"]
        rows = [{"title": "R1", "requirement": "Do X"}]
        add_if_missing = ["spec_id", "map_status"]
        new_headers, new_rows = append_missing_columns(headers, rows, add_if_missing)
        self.assertEqual(
            new_headers,
            ["title", "requirement", "spec_id", "map_status"],
        )
        self.assertEqual(new_rows[0]["spec_id"], "")
        self.assertEqual(new_rows[0]["map_status"], "unmapped")

    def test_preserves_existing_columns(self) -> None:
        """Existing columns are not duplicated."""
        headers = ["title", "requirement", "spec_id"]
        rows = [{"title": "R1", "requirement": "Do X", "spec_id": "A1"}]
        add_if_missing = ["spec_id", "map_status"]
        new_headers, new_rows = append_missing_columns(headers, rows, add_if_missing)
        self.assertEqual(
            new_headers,
            ["title", "requirement", "spec_id", "map_status"],
        )
        self.assertEqual(new_rows[0]["spec_id"], "A1")


class AssignDeterministicIdsTests(unittest.TestCase):
    """Tests for assign_deterministic_ids."""

    def test_assigns_ids_to_rows_without_spec_id(self) -> None:
        """Rows without spec_id get deterministic IDs."""
        tmp = Path(__file__).parent / "test_data_format" / "ids_assign"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            registry_path = tmp / "id_registry.json"
            headers = ["title", "requirement", "spec_id"]
            rows = [
                {"title": "R1", "requirement": "Do X", "spec_id": ""},
                {"title": "R2", "requirement": "Do Y", "spec_id": ""},
            ]
            result, registry = assign_deterministic_ids(
                headers, rows, registry_path, tmp
            )
            self.assertEqual(result[0]["spec_id"], "A1")
            self.assertEqual(result[1]["spec_id"], "A2")
            self.assertIn("spec_fingerprints", registry)
        finally:
            for f in tmp.glob("*"):
                f.unlink()
            tmp.rmdir()

    def test_preserves_valid_existing_ids(self) -> None:
        """Rows with valid spec_id keep them."""
        tmp = Path(__file__).parent / "test_data_format" / "ids_preserve"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            registry_path = tmp / "id_registry.json"
            headers = ["title", "requirement", "spec_id"]
            rows = [
                {"title": "R1", "requirement": "Do X", "spec_id": "A99"},
            ]
            result, _ = assign_deterministic_ids(
                headers, rows, registry_path, tmp
            )
            self.assertEqual(result[0]["spec_id"], "A99")
        finally:
            for f in tmp.glob("*"):
                f.unlink()
            tmp.rmdir()


class NormalizeRawSadsTests(unittest.TestCase):
    """Tests for normalize_raw_sads."""

    def test_full_normalization_produces_csv(self) -> None:
        """Full normalization produces valid CSV with contract columns."""
        root = Path(__file__).parent / "test_data_format" / "normalize"
        root.mkdir(parents=True, exist_ok=True)
        csv_path = root / "raw.csv"
        csv_path.write_text(
            "title,requirement\n"
            "R1,Do something\n"
            "R2,Do something else\n",
            encoding="utf-8",
        )
        try:
            config = {
                "id_generation": {"registry_path": "out/state/id_registry.json"},
            }
            content, log = normalize_raw_sads(csv_path, config, root, dry_run=True)
            self.assertIn("spec_id", content)
            self.assertIn("map_status", content)
            self.assertEqual(log["input_rows"], 2)
            self.assertEqual(log["output_rows"], 2)
            self.assertIn("spec_id", log["output_columns"])
        finally:
            for f in root.glob("*"):
                f.unlink()
            root.rmdir()

    def test_keyword_replacement_applied(self) -> None:
        """Sensitive keywords are replaced when configured."""
        root = Path(__file__).parent / "test_data_format" / "keywords"
        root.mkdir(parents=True, exist_ok=True)
        csv_path = root / "raw.csv"
        csv_path.write_text(
            "title,requirement\n"
            "CONFIDENTIAL task,Handle CONFIDENTIAL data\n",
            encoding="utf-8",
        )
        try:
            config = {
                "commands": {
                    "format": {
                        "sensitive_keywords": {
                            "[REDACTED]": {"keywords": ["CONFIDENTIAL"]},
                        },
                    }
                },
                "id_generation": {"registry_path": "out/state/id_registry.json"},
            }
            content, log = normalize_raw_sads(csv_path, config, root, dry_run=True)
            self.assertIn("[REDACTED]", content)
            self.assertNotIn("CONFIDENTIAL", content)
            self.assertEqual(log["keyword_replacements"], 1)
        finally:
            for f in root.glob("*"):
                f.unlink()
            root.rmdir()

    def test_case_sensitive_from_config(self) -> None:
        """When case_sensitive: true per mapping, only exact case is replaced."""
        root = Path(__file__).parent / "test_data_format" / "keywords_case"
        root.mkdir(parents=True, exist_ok=True)
        csv_path = root / "raw.csv"
        csv_path.write_text(
            "title,requirement\n"
            "KGAS and kgas and KgAs,Use KGAS only\n",
            encoding="utf-8",
        )
        try:
            config = {
                "commands": {
                    "format": {
                        "sensitive_keywords": {
                            "[SOFTWARE]": {"keywords": ["KGAS"], "case_sensitive": True},
                        },
                    }
                },
                "id_generation": {"registry_path": "out/state/id_registry.json"},
            }
            content, log = normalize_raw_sads(csv_path, config, root, dry_run=True)
            self.assertIn("[SOFTWARE]", content)
            self.assertIn("kgas", content)
            self.assertIn("KgAs", content)
        finally:
            for f in root.glob("*"):
                f.unlink()
            root.rmdir()


class FlattenSadsRowsTests(unittest.TestCase):
    """Tests for flatten_sads_rows."""

    def test_forward_fills_srs_id_and_filters_to_sads(self) -> None:
        """Forward-fills SRS ID/SRS and keeps only rows with SADS ID."""
        headers = ["SRS ID", "SRS", "SADS ID", "SADS"]
        rows = [
            {"SRS ID": "R627", "SRS": "High-level req", "SADS ID": "D627.01", "SADS": "Detail 1"},
            {"SRS ID": "", "SRS": "", "SADS ID": "D627.02", "SADS": "Detail 2"},
            {"SRS ID": "R609", "SRS": "Another req", "SADS ID": "D609.01", "SADS": "Detail A"},
        ]
        new_headers, new_rows = flatten_sads_rows(headers, rows)
        self.assertEqual(new_headers, headers)
        self.assertEqual(len(new_rows), 3)
        self.assertEqual(new_rows[0]["SRS ID"], "R627")
        self.assertEqual(new_rows[1]["SRS ID"], "R627")
        self.assertEqual(new_rows[1]["SRS"], "High-level req")
        self.assertEqual(new_rows[2]["SRS ID"], "R609")

    def test_skips_rows_without_sads_id(self) -> None:
        """Rows without valid SADS ID are filtered out."""
        headers = ["SRS ID", "SADS ID", "SADS"]
        rows = [
            {"SRS ID": "R1", "SADS ID": "D627.01", "SADS": "X"},
            {"SRS ID": "", "SADS ID": "", "SADS": "Y"},
            {"SRS ID": "", "SADS ID": "D627.02", "SADS": "Z"},
        ]
        _, new_rows = flatten_sads_rows(headers, rows)
        self.assertEqual(len(new_rows), 2)
        self.assertEqual(new_rows[0]["SADS ID"], "D627.01")
        self.assertEqual(new_rows[1]["SADS ID"], "D627.02")


class DeriveContractColumnsTests(unittest.TestCase):
    """Tests for derive_contract_columns."""

    def test_adds_title_and_requirement_from_sads(self) -> None:
        """When title/requirement missing, derives from SADS ID and SADS."""
        headers = ["SRS ID", "SADS ID", "SADS"]
        rows = [
            {"SRS ID": "R627", "SADS ID": "D627.01", "SADS": "Do SFTP transfer"},
        ]
        new_headers, new_rows = derive_contract_columns(headers, rows)
        self.assertIn("title", new_headers)
        self.assertIn("requirement", new_headers)
        self.assertEqual(new_rows[0]["title"], "D627.01")
        self.assertEqual(new_rows[0]["requirement"], "Do SFTP transfer")


class AssignSadsDeterministicIdsTests(unittest.TestCase):
    """Tests for assign_sads_deterministic_ids."""

    def test_assigns_spec_ids_and_builds_mapping(self) -> None:
        """Assigns spec_ids and returns by_sads_id, by_srs_id mapping."""
        tmp = Path(__file__).parent / "test_data_format" / "sads_ids"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            headers = ["SRS ID", "SADS ID", "SADS", "spec_id"]
            rows = [
                {"SRS ID": "R627", "SADS ID": "D627.01", "SADS": "Req 1", "spec_id": ""},
                {"SRS ID": "R627", "SADS ID": "D627.02", "SADS": "Req 2", "spec_id": ""},
                {"SRS ID": "R609", "SADS ID": "D609.01", "SADS": "Req A", "spec_id": ""},
            ]
            result, registry, id_mapping = assign_sads_deterministic_ids(
                headers, rows, tmp / "id_registry.json", tmp
            )
            self.assertEqual(result[0]["spec_id"], "A1")
            self.assertEqual(result[1]["spec_id"], "A2")
            self.assertEqual(result[2]["spec_id"], "A3")
            self.assertEqual(id_mapping["by_sads_id"]["D627.01"], {"spec_id": "A1", "srs_id": "R627"})
            self.assertEqual(id_mapping["by_sads_id"]["D627.02"], {"spec_id": "A2", "srs_id": "R627"})
            self.assertEqual(id_mapping["by_srs_id"]["R627"], ["A1", "A2"])
            self.assertEqual(id_mapping["by_srs_id"]["R609"], ["A3"])
        finally:
            for f in tmp.glob("*"):
                f.unlink()
            tmp.rmdir()


class WriteIdMappingTests(unittest.TestCase):
    """Tests for write_id_mapping."""

    def test_writes_mapping_json(self) -> None:
        """Writes by_sads_id and by_srs_id to JSON file."""
        tmp = Path(__file__).parent / "test_data_format" / "mapping_out"
        tmp.mkdir(parents=True, exist_ok=True)
        mapping_path = tmp / "sads_id_mapping.json"
        try:
            id_mapping = {
                "by_sads_id": {"D627.01": {"spec_id": "A1", "srs_id": "R627"}},
                "by_srs_id": {"R627": ["A1"]},
            }
            write_id_mapping(id_mapping, mapping_path, tmp, dry_run=False)
            self.assertTrue(mapping_path.exists())
            import json
            loaded = json.loads(mapping_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["by_sads_id"]["D627.01"]["spec_id"], "A1")
        finally:
            if mapping_path.exists():
                mapping_path.unlink()
            tmp.rmdir()

    def test_dry_run_skips_write(self) -> None:
        """Dry run does not write file."""
        tmp = Path(__file__).parent / "test_data_format" / "mapping_dry"
        tmp.mkdir(parents=True, exist_ok=True)
        mapping_path = tmp / "sads_id_mapping.json"
        try:
            write_id_mapping({"by_sads_id": {}, "by_srs_id": {}}, mapping_path, tmp, dry_run=True)
            self.assertFalse(mapping_path.exists())
        finally:
            if mapping_path.exists():
                mapping_path.unlink()
            tmp.rmdir()


class NormalizeSadsFormatTests(unittest.TestCase):
    """Tests for normalize_raw_sads with SADS format (Sample-Spec structure)."""

    def test_sads_format_flattens_and_assigns_ids(self) -> None:
        """SADS format: flatten, derive, assign IDs, produce mapping."""
        root = Path(__file__).parent / "test_data_format" / "sads_normalize"
        root.mkdir(parents=True, exist_ok=True)
        csv_path = root / "sample_spec.csv"
        csv_path.write_text(
            "SRS ID,SRS,UNIT,SADS ID,SADS,NOTES\n"
            "R627,High-level req,SRV,D627.01,Detail 1,\n"
            ",,,D627.02,Detail 2,\n"
            "R609,Another req,FRT,D609.01,Detail A,\n",
            encoding="utf-8",
        )
        try:
            config = {
                "commands": {"format": {}},
                "id_generation": {"registry_path": str(root / "id_registry.json")},
            }
            content, log = normalize_raw_sads(csv_path, config, root, dry_run=False)
            self.assertTrue(log["sads_format"])
            self.assertEqual(log["output_rows"], 3)
            self.assertIn("spec_id", content)
            self.assertIn("D627.01", content)
            mapping_path = root / "out" / "state" / "sads_id_mapping.json"
            # Default path is out/state/sads_id_mapping.json relative to project_root
            default_mapping = root / "out" / "state" / "sads_id_mapping.json"
            # Config doesn't override, so we use DEFAULT_SADS_ID_MAPPING_PATH = out/state/...
            self.assertTrue(default_mapping.exists(), f"Expected {default_mapping}")
            import json
            mapping = json.loads(default_mapping.read_text(encoding="utf-8"))
            self.assertIn("D627.01", mapping["by_sads_id"])
            self.assertIn("R627", mapping["by_srs_id"])
        finally:
            for f in root.rglob("*"):
                if f.is_file():
                    f.unlink()
            for d in sorted(root.rglob("*"), key=lambda p: -len(p.parts)):
                if d.is_dir() and d != root:
                    try:
                        d.rmdir()
                    except OSError:
                        pass
            root.rmdir()


class RowsToCsvTests(unittest.TestCase):
    """Tests for rows_to_csv."""

    def test_normalizes_newlines_to_single_line_rows(self) -> None:
        """Newlines in cells are replaced with space; each row is one CSV line."""
        headers = ["title", "notes"]
        rows = [
            {"title": "A", "notes": "Line1\nLine2"},
            {"title": "B", "notes": "Single"},
        ]
        result = normalize_newlines_in_cells(headers, rows)
        self.assertEqual(result[0]["notes"], "Line1 Line2")
        self.assertEqual(result[1]["notes"], "Single")
        csv_out = rows_to_csv(headers, result)
        lines = csv_out.strip().split("\n")
        self.assertEqual(len(lines), 3)  # header + 2 rows

    def test_serializes_headers_and_rows(self) -> None:
        """Serializes to valid CSV string."""
        headers = ["a", "b"]
        rows = [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]
        out = rows_to_csv(headers, rows)
        self.assertIn("a,b", out)
        self.assertIn("1,2", out)
        self.assertIn("3,4", out)

    def test_uses_unix_line_endings_to_avoid_double_blank_on_windows(self) -> None:
        """Output uses \\n only so write_text() on Windows produces correct \\r\\n.

        The default csv lineterminator '\\r\\n' would be double-translated when
        written via write_text() on Windows, producing \\r\\r\\n and blank lines.
        """
        headers = ["x"]
        rows = [{"x": "1"}, {"x": "2"}]
        out = rows_to_csv(headers, rows)
        self.assertNotIn("\r\r\n", out, "Should not contain double CRLF (causes blank lines)")
        self.assertEqual(out, "x\n1\n2\n")

    def test_converts_unicode_to_latex_on_output(self) -> None:
        """Unicode in cell values is converted to LaTeX escapes in CSV output."""
        headers = ["title", "requirement"]
        rows = [
            {"title": "Sum", "requirement": "Compute ∑ of values"},
            {"title": "Micro", "requirement": "Length 3μm"},
        ]
        out = rows_to_csv(headers, rows)
        self.assertIn("\\sum", out)
        self.assertIn("\\ensuremath{\\mu}", out)
        self.assertNotIn("∑", out)
        self.assertNotIn("μ", out)


if __name__ == "__main__":
    unittest.main()
