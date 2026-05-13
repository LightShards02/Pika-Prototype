"""Idempotency tests for register(registry) on refine phase modules."""

from __future__ import annotations

import pytest

from core.phase_registry import PhaseRegistry


@pytest.fixture()
def registry() -> PhaseRegistry:
    return PhaseRegistry()


def test_decomposition_check_register_is_idempotent(registry: PhaseRegistry) -> None:
    from handlers.refine.phases.decomposition_check import DECOMPOSITION_CHECK, register

    assert registry.contract(DECOMPOSITION_CHECK.name) is None

    register(registry)
    assert registry.contract(DECOMPOSITION_CHECK.name) is not None
    count_after_first = len(registry.all_contracts())

    register(registry)  # second call must be a no-op
    assert len(registry.all_contracts()) == count_after_first
    assert registry.contract(DECOMPOSITION_CHECK.name) is DECOMPOSITION_CHECK


def test_quality_audit_register_is_idempotent(registry: PhaseRegistry) -> None:
    from handlers.refine.phases.quality_audit import QUALITY_AUDIT, register

    assert registry.contract(QUALITY_AUDIT.name) is None

    register(registry)
    assert registry.contract(QUALITY_AUDIT.name) is not None
    count_after_first = len(registry.all_contracts())

    register(registry)
    assert len(registry.all_contracts()) == count_after_first
    assert registry.contract(QUALITY_AUDIT.name) is QUALITY_AUDIT
