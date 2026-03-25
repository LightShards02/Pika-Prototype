"""Pytest configuration for backend tests."""

from __future__ import annotations

from typing import Any


def pytest_configure(config: Any) -> None:
    """Suppress DeprecationWarning from deprecated Codex CLI helpers (tests-only)."""
    config.addinivalue_line(
        "filterwarnings",
        "ignore:.*Codex CLI subprocess API is deprecated.*:DeprecationWarning",
    )
