"""Phase catalog adapter: refine.quality-audit."""

from __future__ import annotations

from api.phase_registry import get_phase_registry
from handlers.refine.phases.quality_audit import register as _register


def register() -> None:
    _register(get_phase_registry())
