"""Phase contract and result types shared by api/ and handlers/.

These dataclasses describe what a phase declares (`PhaseInput`, `PhaseOutput`,
`PhaseContract`) and what a phase runner produces (`PhaseCompleted`,
`PhaseBlocked`, `PhaseFailed`). They live in core/ so both `api/` (catalog,
serialization) and `handlers/` (phase implementations) can import them
without violating the locked dependency direction (`api/` → `handlers/`,
never reverse).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class PhaseInput:
    name: str
    kind: Literal["path", "workspace_relative_path", "phase_run_ref", "string", "bool", "int"]
    required: bool
    description: str = ""
    ref_phase: str | None = None


@dataclass(frozen=True)
class PhaseOutput:
    name: str
    path: str
    scope: Literal["phase_run", "workspace"] = "phase_run"
    schema_ref: str | None = None


@dataclass(frozen=True)
class PhaseContract:
    name: str
    command: str
    inputs: tuple[PhaseInput, ...]
    outputs: tuple[PhaseOutput, ...]
    recommended_prerequisites: tuple[str, ...] = ()
    can_block: bool = False
    destructive: bool = False
    description: str = ""
    async_execution: bool = False


@dataclass(frozen=True)
class PhaseCompleted:
    artifacts_index: dict[str, str]
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PhaseBlocked:
    manual_dir: Path
    item_count: int
    blocking_reason: str


@dataclass(frozen=True)
class PhaseFailed:
    error_code: str
    message: str
    recoverable_artifacts: dict[str, str] = field(default_factory=dict)


PhaseResult = PhaseCompleted | PhaseBlocked | PhaseFailed


__all__ = [
    "PhaseInput",
    "PhaseOutput",
    "PhaseContract",
    "PhaseCompleted",
    "PhaseBlocked",
    "PhaseFailed",
    "PhaseResult",
]
