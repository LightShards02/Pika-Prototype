"""Phase catalog: declarative contracts and runner registration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal


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


PhaseRunner = Callable[
    [dict[str, Any], "RuntimeContextLike", Path, dict[str, Any]],
    PhaseResult,
]


# Avoid importing core.context here to keep phase_registry typing-only.
class RuntimeContextLike:  # pragma: no cover - structural placeholder
    pass


class PhaseRegistry:
    """In-process singleton mapping phase name -> (contract, runner)."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[PhaseContract, PhaseRunner]] = {}

    def register(self, contract: PhaseContract, runner: PhaseRunner) -> None:
        if contract.name in self._entries:
            raise ValueError(f"Phase already registered: {contract.name}")
        self._entries[contract.name] = (contract, runner)

    def get(self, name: str) -> tuple[PhaseContract, PhaseRunner] | None:
        return self._entries.get(name)

    def contract(self, name: str) -> PhaseContract | None:
        entry = self._entries.get(name)
        return entry[0] if entry else None

    def names(self) -> list[str]:
        return sorted(self._entries.keys())

    def all_contracts(self) -> list[PhaseContract]:
        return [c for c, _ in self._entries.values()]

    def clear(self) -> None:
        self._entries.clear()


_registry = PhaseRegistry()


def get_phase_registry() -> PhaseRegistry:
    return _registry
