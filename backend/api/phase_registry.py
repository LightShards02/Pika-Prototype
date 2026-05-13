"""API-layer phase catalog accessor.

The contract dataclasses and registry class live in `core/` so handler phase
modules can import them without violating the `api/` -> `handlers/` dependency
direction. This module re-exports them for M1 API callers that already import
from here, plus the singleton accessor (`get_phase_registry`) which IS an
API-layer concern.
"""

from __future__ import annotations

from core.phase_registry import PhaseRegistry, PhaseRunner, RuntimeContextLike
from core.phase_types import (
    PhaseBlocked,
    PhaseCompleted,
    PhaseContract,
    PhaseFailed,
    PhaseInput,
    PhaseOutput,
    PhaseResult,
)


_registry = PhaseRegistry()


def get_phase_registry() -> PhaseRegistry:
    return _registry


__all__ = [
    "PhaseInput",
    "PhaseOutput",
    "PhaseContract",
    "PhaseRunner",
    "PhaseRegistry",
    "get_phase_registry",
    "PhaseCompleted",
    "PhaseBlocked",
    "PhaseFailed",
    "PhaseResult",
    "RuntimeContextLike",
]
