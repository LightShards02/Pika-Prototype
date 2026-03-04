"""Timestamp utilities for PIKA. All timestamps use local timezone, seconds precision."""

from __future__ import annotations

import re
from datetime import datetime, timezone


def _format_offset_utc_style(dt: datetime) -> str:
    """Return UTC+X or UTC-X style offset from datetime's timezone.

    Examples: +0800 -> UTC+8, -0500 -> UTC-5, +0530 -> UTC+5:30
    """
    tz_str = dt.strftime("%z")
    if not tz_str or len(tz_str) < 5:
        return "UTC"
    sign = tz_str[0]
    hours = int(tz_str[1:3])
    minutes = int(tz_str[3:5])
    if sign == "-":
        hours = -hours
    if minutes == 0:
        return f"UTC{hours:+d}" if hours >= 0 else f"UTC{hours}"
    return f"UTC{hours:+d}:{minutes:02d}" if hours >= 0 else f"UTC{hours}:{minutes:02d}"


def format_timestamp_local_minutes(dt: datetime | None = None) -> str:
    """Return timestamp in local timezone, seconds precision, with UTC+X marker.

    Format: YYYY-MM-DDTHH:MM:SS UTC+8 (or UTC-5 etc.)

    Args:
        dt: Datetime to format. If None, uses now. If naive (no tzinfo), treats as UTC.

    Returns:
        Formatted string, e.g. 2026-02-26T07:05:41 UTC+8
    """
    if dt is None:
        dt = datetime.now().astimezone()
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc).astimezone()
    else:
        dt = dt.astimezone()
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + " " + _format_offset_utc_style(dt)


def normalize_timestamp_for_display(ts: str) -> str:
    """Parse an ISO timestamp string and return normalized display format.

    Handles agent-provided timestamps (e.g. 2026-02-26T07:05:41.8852169Z).
    Strips fractional seconds, converts to local timezone, formats as
    YYYY-MM-DDTHH:MM:SS UTC+X.

    Args:
        ts: ISO-8601 timestamp string (may include Z, fractional seconds).

    Returns:
        Formatted string, e.g. 2026-02-26T15:05:41 UTC+8 (UTC input converted to local).
    """
    if not ts or not isinstance(ts, str) or not ts.strip():
        return format_timestamp_local_minutes()
    s = ts.strip()
    # Strip fractional seconds (e.g. .8852169)
    s = re.sub(r"\.\d+", "", s)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return format_timestamp_local_minutes()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return format_timestamp_local_minutes(dt)


def generate_run_id(dt: datetime | None = None) -> str:
    """Generate a run_id from current timestamp; safe for filenames and directories.

    Uses the same local-timezone semantics as format_timestamp_local_minutes_filename,
    but with seconds for uniqueness. Invalid filename characters (e.g. : + - in
    some contexts) are removed or replaced so the result is safe on all platforms.

    Format: YYYYMMDD_HHMMSS_tz (e.g. 20260301_174124_p0800 for UTC+8,
    20260301_174124_m0500 for UTC-5).

    Args:
        dt: Datetime to format. If None, uses now. If naive, treats as UTC.

    Returns:
        Filename-safe run_id string.
    """
    if dt is None:
        dt = datetime.now().astimezone()
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc).astimezone()
    else:
        dt = dt.astimezone()
    base = dt.strftime("%Y%m%d_%H%M%S")
    tz_str = dt.strftime("%z")
    if not tz_str or len(tz_str) < 5:
        return base
    sign, hours, mins = tz_str[0], tz_str[1:3], tz_str[3:5]
    tz_safe = f"m{hours}{mins}" if sign == "-" else f"p{hours}{mins}"
    return f"{base}_{tz_safe}"


def format_timestamp_local_minutes_filename(dt: datetime | None = None) -> str:
    """Return compact timestamp for filenames: YYYYMMDD_HHMM with timezone suffix.

    Format: 20240115_1234+0800

    Args:
        dt: Datetime to format. If None, uses now. If naive, treats as UTC.

    Returns:
        Formatted string for use in backup filenames.
    """
    if dt is None:
        dt = datetime.now().astimezone()
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc).astimezone()
    else:
        dt = dt.astimezone()
    return dt.strftime("%Y%m%d_%H%M") + dt.strftime("%z")
