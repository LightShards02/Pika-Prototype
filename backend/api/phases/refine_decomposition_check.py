"""Phase catalog adapter: refine.decomposition-check."""

from __future__ import annotations

from api.phase_registry import get_phase_registry
from handlers.refine.phases.decomposition_check import register as _register


def register() -> None:
    _register(get_phase_registry())
