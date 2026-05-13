"""Regression: api.phase_registry still re-exports all M1-era symbols after core relocation."""

from __future__ import annotations


def test_api_phase_registry_reexports_all_legacy_symbols() -> None:
    import api.phase_registry as ar
    from core.phase_registry import (
        PhaseRegistry as core_PhaseRegistry,
        PhaseRunner as core_PhaseRunner,
        RuntimeContextLike as core_RuntimeContextLike,
    )
    from core.phase_types import (
        PhaseBlocked as core_PhaseBlocked,
        PhaseCompleted as core_PhaseCompleted,
        PhaseContract as core_PhaseContract,
        PhaseFailed as core_PhaseFailed,
        PhaseInput as core_PhaseInput,
        PhaseOutput as core_PhaseOutput,
        PhaseResult as core_PhaseResult,
    )

    assert ar.PhaseInput is core_PhaseInput
    assert ar.PhaseOutput is core_PhaseOutput
    assert ar.PhaseContract is core_PhaseContract
    assert ar.PhaseCompleted is core_PhaseCompleted
    assert ar.PhaseBlocked is core_PhaseBlocked
    assert ar.PhaseFailed is core_PhaseFailed
    assert ar.PhaseResult is core_PhaseResult
    assert ar.PhaseRegistry is core_PhaseRegistry
    assert ar.PhaseRunner is core_PhaseRunner
    assert ar.RuntimeContextLike is core_RuntimeContextLike


def test_api_phase_registry_singleton_register_and_get() -> None:
    """Exercise the API singleton through its public interface to prove no M1 breakage."""
    from api.phase_registry import (
        PhaseContract,
        PhaseInput,
        PhaseOutput,
        PhaseCompleted,
        get_phase_registry,
    )

    registry = get_phase_registry()
    registry.clear()

    contract = PhaseContract(
        name="regression.test-only",
        command="regression",
        inputs=(PhaseInput(name="x", kind="string", required=True),),
        outputs=(PhaseOutput(name="y", path="y.json"),),
    )

    def runner(config, ctx, phase_run_dir, inputs):
        return PhaseCompleted(artifacts_index={"y": "y.json"})

    registry.register(contract, runner)

    fetched = registry.get(contract.name)
    assert fetched is not None
    assert fetched[0] is contract
    assert fetched[1] is runner

    assert registry.contract(contract.name) is contract
    assert contract.name in registry.names()
    assert contract in registry.all_contracts()

    registry.clear()
    assert registry.contract(contract.name) is None
