"""Tests for core.contracts."""

from __future__ import annotations

import unittest

from core.contracts import get_design_spec_column_definitions


class GetDesignSpecColumnDefinitionsTests(unittest.TestCase):
    """Tests for get_design_spec_column_definitions."""

    def test_returns_non_empty_string(self) -> None:
        """Returns formatted column definitions from csv_contracts.md."""
        result = get_design_spec_column_definitions()
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_includes_spec_id_and_subunit(self) -> None:
        """Definitions include spec_id and subunit columns."""
        result = get_design_spec_column_definitions()
        self.assertIn("spec_id", result)
        self.assertIn("subunit", result)

    def test_format_has_column_name_and_meaning(self) -> None:
        """Each line has format: - column_name (required/optional): meaning."""
        result = get_design_spec_column_definitions()
        lines = [l.strip() for l in result.split("\n") if l.strip()]
        self.assertGreater(len(lines), 0)
        for line in lines[:3]:  # Check first few
            self.assertTrue(line.startswith("- "))
            self.assertIn(":", line)


if __name__ == "__main__":
    unittest.main()
