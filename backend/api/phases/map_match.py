"""Phase catalog adapter: map.match."""

from __future__ import annotations

from api.phase_registry import get_phase_registry
from handlers.map_phases.match import register as _register


def register() -> None:
    _register(get_phase_registry())
