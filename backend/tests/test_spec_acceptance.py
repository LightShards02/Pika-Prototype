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

    def test_loads_ac(self) -> None:
        """Happy path: spec_id -> {acceptance_criteria}. evidence_type is no longer
        a SADS CSV column; per-criterion evidence_type lives in the per-spec
        test_plan side-files (loaded by load_spec_test_plans, not by this loader).
        """
        with TemporaryDirectory() as td:
            csv_path = Path(td) / "design.csv"
            self._write_csv(
                csv_path,
                "spec_id,title,acceptance_criteria\n"
                "S1,T1,AC one\n"
                "S2,T2,AC two\n",
            )
            result = load_spec_acceptance_criteria(csv_path)
            self.assertEqual(
                result,
                {
                    "S1": {"acceptance_criteria": "AC one"},
                    "S2": {"acceptance_criteria": "AC two"},
                },
            )

    def test_evidence_type_column_is_ignored_when_present(self) -> None:
        """A leftover evidence_type column in older SADS files is silently ignored."""
        with TemporaryDirectory() as td:
            csv_path = Path(td) / "design.csv"
            self._write_csv(
                csv_path,
                "spec_id,acceptance_criteria,evidence_type\n"
                "S1,AC one,legacy_value\n",
            )
            result = load_spec_acceptance_criteria(csv_path)
            self.assertEqual(result, {"S1": {"acceptance_criteria": "AC one"}})

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

    def test_returns_empty_when_required_columns_missing(self) -> None:
        """Missing spec_id or acceptance_criteria column -> empty dict."""
        with TemporaryDirectory() as td:
            csv_path = Path(td) / "design.csv"
            self._write_csv(
                csv_path,
                "title,description\nT1,D1\n",
            )
            self.assertEqual(load_spec_acceptance_criteria(csv_path), {})


class FilterToSpecIdsTests(unittest.TestCase):
    """Tests for filter_to_spec_ids."""

    def test_filters_to_subset(self) -> None:
        ac_map = {
            "S1": {"acceptance_criteria": "a"},
            "S2": {"acceptance_criteria": "b"},
            "S3": {"acceptance_criteria": "c"},
        }
        self.assertEqual(
            set(filter_to_spec_ids(ac_map, {"S1", "S3"}).keys()),
            {"S1", "S3"},
        )

    def test_empty_subset_yields_empty(self) -> None:
        ac_map = {"S1": {"acceptance_criteria": "a"}}
        self.assertEqual(filter_to_spec_ids(ac_map, set()), {})

    def test_subset_with_unknown_ids_returns_only_known(self) -> None:
        ac_map = {"S1": {"acceptance_criteria": "a"}}
        self.assertEqual(
            filter_to_spec_ids(ac_map, {"S1", "S99"}),
            {"S1": {"acceptance_criteria": "a"}},
        )


if __name__ == "__main__":
    unittest.main()
