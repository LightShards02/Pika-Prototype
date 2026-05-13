"""Phase registry: in-process mapping of phase name to (contract, runner).

Lives in core/ so handler phase modules can declare their `register(registry)`
parameter type without importing from api/. The API layer's singleton accessor
(`get_phase_registry`) stays in `api/phase_registry.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from core.phase_types import PhaseContract, PhaseResult


PhaseRunner = Callable[
    [dict[str, Any], "RuntimeContextLike", Path, dict[str, Any]],
    PhaseResult,
]


class RuntimeContextLike:  # pragma: no cover - structural placeholder
    pass


class PhaseRegistry:
    """In-process mapping of phase name -> (contract, runner)."""

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


__all__ = ["PhaseRegistry", "PhaseRunner", "RuntimeContextLike"]
