"""Tests for core.time_utils."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from core.time_utils import generate_run_id


class GenerateRunIdTests(unittest.TestCase):
    """Tests for generate_run_id."""

    def test_returns_filename_safe_string(self) -> None:
        """Run ID contains no invalid filename characters (: / \\ * ? " < > |)."""
        run_id = generate_run_id()
        invalid = set(':/\\*?"<>|')
        for c in run_id:
            self.assertNotIn(c, invalid, msg=f"run_id contains invalid char: {c!r}")

    def test_format_matches_expected_pattern(self) -> None:
        """Run ID matches YYYYMMDD_HHMMSS_tz pattern."""
        run_id = generate_run_id()
        self.assertRegex(run_id, r"^\d{8}_\d{6}_[pm]\d{4}$")

    def test_with_explicit_datetime_includes_date_and_time(self) -> None:
        """Explicit datetime produces run_id containing its date and time."""
        tz = timezone(timedelta(hours=8))
        dt = datetime(2026, 3, 1, 17, 41, 24, tzinfo=tz)
        run_id = generate_run_id(dt)
        # Output is in local timezone; at least date and time components appear
        self.assertIn("20260301", run_id)
        self.assertRegex(run_id, r"_\d{6}_")

    def test_timezone_suffix_uses_p_or_m(self) -> None:
        """Timezone suffix uses p (plus) or m (minus), never raw + or -."""
        run_id = generate_run_id()
        self.assertNotIn("+", run_id)
        self.assertNotIn("-", run_id)
        self.assertRegex(run_id, r"_[pm]\d{4}$")
