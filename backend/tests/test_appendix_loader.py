"""Tests for appendix CSV loading and normalization."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.appendix_loader import load_appendix_files


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


if __name__ == "__main__":
    unittest.main()
