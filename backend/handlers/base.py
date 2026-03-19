"""Base utilities for command handlers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.context import RuntimeContext


def load_csv(path: Path) -> str:
    """Load CSV file content as text."""
    return path.read_text(encoding="utf-8")


def noop_translate(
    config: dict[str, Any],
    ctx: RuntimeContext,
    output: dict[str, Any],
    inputs: Any,
) -> None:
    """No-op translation (dry-run or stub)."""
    _ = config, ctx, output, inputs
