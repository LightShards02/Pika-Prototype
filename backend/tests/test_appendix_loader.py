"""Tests for appendix CSV loading and normalization."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.appendix_loader import AppendixEntry, format_appendix_for_agent, load_appendix_files


class AppendixLoaderCsvOverflowTests(unittest.TestCase):
    """Regression coverage for malformed appendix CSV rows with overflow cells."""

    def test_load_appendix_files_merges_overflow_cells_into_last_header(self) -> None:
        """Overflow cells should be appended to the final declared CSV column."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            appendix_path = root / "appendix_error_codes.csv"
            appendix_path.write_text(
                "\n".join(
                    [
                        "title,content,module_tag,error_code,http_status,applies_to_spec_ids,notes",
                        "ACC_STORAGE_WRITE_FAILED,"
                        "\"module_tag: DATA\\nerror_code: ACC_STORAGE_WRITE_FAILED\","
                        "DATA,ACC_STORAGE_WRITE_FAILED,503,A2011|A2014,"
                        "Returned when repository persistence fails for orders, manifest rows, work items.",
                    ]
                ),
                encoding="utf-8",
            )

            config = {
                "commands": {
                    "refine": {
                        "inputs": {
                            "appendices": [
                                {"path": appendix_path.name, "format": "csv"},
                            ]
                        }
                    }
                }
            }

            entries = load_appendix_files(config, root, command="refine")

            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].title, "ACC_STORAGE_WRITE_FAILED")
            self.assertEqual(
                entries[0].content,
                "module_tag: DATA\\nerror_code: ACC_STORAGE_WRITE_FAILED",
            )
            self.assertEqual(
                entries[0].module_tag,
                "DATA",
            )
            self.assertEqual(
                entries[0].source_path,
                str(appendix_path),
            )


class FormatAppendixForAgentTests(unittest.TestCase):
    """``format_appendix_for_agent`` sectioning and ordering."""

    def test_interleaved_same_source_preserves_global_entry_order(self) -> None:
        """Non-adjacent rows from the same file must not be merged ahead of others."""
        a = Path("/proj/appendix_a.csv")
        b = Path("/proj/appendix_b.csv")
        entries = [
            AppendixEntry(
                appendix_id="APX001",
                title="a1",
                content="CONTENT_A1",
                source_path=str(a),
            ),
            AppendixEntry(
                appendix_id="APX002",
                title="b1",
                content="CONTENT_B1",
                source_path=str(b),
            ),
            AppendixEntry(
                appendix_id="APX003",
                title="a2",
                content="CONTENT_A2",
                source_path=str(a),
            ),
        ]
        text = format_appendix_for_agent(entries)
        self.assertLess(text.index("CONTENT_A1"), text.index("CONTENT_B1"))
        self.assertLess(text.index("CONTENT_B1"), text.index("CONTENT_A2"))
        self.assertEqual(text.count("appendix_a.csv"), 2)

    def test_contiguous_same_source_single_section(self) -> None:
        p = Path("/proj/one.csv")
        entries = [
            AppendixEntry(
                appendix_id="APX001",
                title="r1",
                content="C1",
                source_path=str(p),
            ),
            AppendixEntry(
                appendix_id="APX002",
                title="r2",
                content="C2",
                source_path=str(p),
            ),
        ]
        text = format_appendix_for_agent(entries)
        self.assertEqual(text.count("one.csv"), 1)
        self.assertIn("(2 entries", text)


if __name__ == "__main__":
    unittest.main()
