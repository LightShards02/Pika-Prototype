"""Phase catalog adapter: implement.unified-planner."""

from __future__ import annotations

from api.phase_registry import get_phase_registry
from handlers.implement.phases.unified_planner import register as _register


def register() -> None:
    _register(get_phase_registry())
