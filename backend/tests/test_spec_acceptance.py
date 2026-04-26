"""Tests for core.spec_acceptance."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.spec_acceptance import (
    filter_to_spec_ids,
    load_spec_acceptance_criteria,
)


class LoadSpecAcceptanceCriteriaTests(unittest.TestCase):
    """Tests for load_spec_acceptance_criteria."""

    def _write_csv(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")

    def test_returns_empty_for_missing_file(self) -> None:
        """Missing file yields empty mapping, no exception."""
        with TemporaryDirectory() as td:
            self.assertEqual(
                load_spec_acceptance_criteria(Path(td) / "nope.csv"), {}
            )

    def test_loads_ac_and_evidence_type(self) -> None:
        """Happy path: spec_id -> {acceptance_criteria, evidence_type}."""
        with TemporaryDirectory() as td:
            csv_path = Path(td) / "design.csv"
            self._write_csv(
                csv_path,
                "spec_id,title,acceptance_criteria,evidence_type\n"
                "S1,T1,AC one,test_execution_record\n"
                "S2,T2,AC two,audit_trail\n",
            )
            result = load_spec_acceptance_criteria(csv_path)
            self.assertEqual(
                result,
                {
                    "S1": {
                        "acceptance_criteria": "AC one",
                        "evidence_type": "test_execution_record",
                    },
                    "S2": {
                        "acceptance_criteria": "AC two",
                        "evidence_type": "audit_trail",
                    },
                },
            )

    def test_skips_rows_with_empty_spec_id(self) -> None:
        """Rows missing a spec_id are silently dropped."""
        with TemporaryDirectory() as td:
            csv_path = Path(td) / "design.csv"
            self._write_csv(
                csv_path,
                "spec_id,acceptance_criteria,evidence_type\n"
                ",AC orphan,system_log\n"
                "S1,AC kept,NA\n",
            )
            result = load_spec_acceptance_criteria(csv_path)
            self.assertEqual(set(result.keys()), {"S1"})

    def test_skips_rows_with_empty_acceptance_criteria(self) -> None:
        """Rows missing acceptance_criteria are silently dropped."""
        with TemporaryDirectory() as td:
            csv_path = Path(td) / "design.csv"
            self._write_csv(
                csv_path,
                "spec_id,acceptance_criteria,evidence_type\n"
                "S1,,test_execution_record\n"
                "S2,AC two,audit_trail\n",
            )
            result = load_spec_acceptance_criteria(csv_path)
            self.assertEqual(set(result.keys()), {"S2"})

    def test_evidence_type_defaults_to_empty_when_column_missing(self) -> None:
        """Older CSVs without evidence_type still load with evidence_type=''."""
        with TemporaryDirectory() as td:
            csv_path = Path(td) / "design.csv"
            self._write_csv(
                csv_path,
                "spec_id,acceptance_criteria\n"
                "S1,AC one\n",
            )
            result = load_spec_acceptance_criteria(csv_path)
            self.assertEqual(
                result["S1"],
                {"acceptance_criteria": "AC one", "evidence_type": ""},
            )

    def test_returns_empty_when_required_columns_missing(self) -> None:
        """Missing spec_id or acceptance_criteria column -> empty dict."""
        with TemporaryDirectory() as td:
            csv_path = Path(td) / "design.csv"
            self._write_csv(
                csv_path,
                "title,description\nT1,D1\n",
            )
            self.assertEqual(load_spec_acceptance_criteria(csv_path), {})

    def test_evidence_type_empty_cell_yields_empty_string(self) -> None:
        """Cell-level empty evidence_type is preserved as empty string."""
        with TemporaryDirectory() as td:
            csv_path = Path(td) / "design.csv"
            self._write_csv(
                csv_path,
                "spec_id,acceptance_criteria,evidence_type\n"
                "S1,AC one,\n",
            )
            result = load_spec_acceptance_criteria(csv_path)
            self.assertEqual(result["S1"]["evidence_type"], "")


class FilterToSpecIdsTests(unittest.TestCase):
    """Tests for filter_to_spec_ids."""

    def test_filters_to_subset(self) -> None:
        ac_map = {
            "S1": {"acceptance_criteria": "a", "evidence_type": "x"},
            "S2": {"acceptance_criteria": "b", "evidence_type": "y"},
            "S3": {"acceptance_criteria": "c", "evidence_type": "z"},
        }
        self.assertEqual(
            set(filter_to_spec_ids(ac_map, {"S1", "S3"}).keys()),
            {"S1", "S3"},
        )

    def test_empty_subset_yields_empty(self) -> None:
        ac_map = {"S1": {"acceptance_criteria": "a", "evidence_type": "x"}}
        self.assertEqual(filter_to_spec_ids(ac_map, set()), {})

    def test_subset_with_unknown_ids_returns_only_known(self) -> None:
        ac_map = {"S1": {"acceptance_criteria": "a", "evidence_type": "x"}}
        self.assertEqual(
            filter_to_spec_ids(ac_map, {"S1", "S99"}),
            {"S1": {"acceptance_criteria": "a", "evidence_type": "x"}},
        )


if __name__ == "__main__":
    unittest.main()
