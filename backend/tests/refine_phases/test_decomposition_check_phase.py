"""Tests for handlers.refine.phases.decomposition_check.run()."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import yaml

from tests.refine_phases.conftest import make_config, make_ctx


def _import_phase():
    from handlers.refine.phases.decomposition_check import (
        DECOMPOSITION_CHECK,
        run,
    )
    return DECOMPOSITION_CHECK, run


def _patch_decomp(split=None, merge=None, skipped=False):
    return patch(
        "handlers.refine.phases.decomposition_check.run_decomposition_check",
        return_value={
            "split_candidates": split or [],
            "merge_candidates": merge or [],
            "skipped": skipped,
        },
    )


def test_contract_shape() -> None:
    contract, _ = _import_phase()
    assert contract.name == "refine.decomposition-check"
    assert contract.command == "refine"
    assert contract.can_block is True
    assert contract.destructive is False
    input_names = [i.name for i in contract.inputs]
    assert input_names == ["design_spec_path"]
    output_names = [o.name for o in contract.outputs]
    assert output_names == ["decomposition_flags", "restructured_csv"]


def test_phase_completes_when_no_issues_found(workspace_root: Path, design_csv: Path) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseCompleted

    phase_run_dir = workspace_root / "out" / "agent_runs" / "refine.decomposition-check" / "rid-1"
    config = make_config(workspace_root, str(design_csv), decomposition_enabled=True)
    ctx = make_ctx(workspace_root)

    with _patch_decomp(split=[], merge=[]):
        result = run(config, ctx, phase_run_dir, {"design_spec_path": str(design_csv)})

    assert isinstance(result, PhaseCompleted)
    assert (phase_run_dir / "decomposition_flags.json").exists()
    assert not (phase_run_dir / "manual_resolution").exists()
    assert result.artifacts_index == {"decomposition_flags": "decomposition_flags.json"}
    assert result.summary["split_candidates"] == 0
    assert result.summary["merge_candidates"] == 0


def test_phase_blocks_when_split_candidate_found(workspace_root: Path, design_csv: Path) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseBlocked

    phase_run_dir = workspace_root / "out" / "agent_runs" / "refine.decomposition-check" / "rid-2"
    config = make_config(
        workspace_root, str(design_csv),
        decomposition_enabled=True, decomposition_blocking=True,
    )
    ctx = make_ctx(workspace_root)

    split = [{"spec_id": "S1", "reason": "high variance", "variance": 0.25}]
    with _patch_decomp(split=split, merge=[]):
        result = run(config, ctx, phase_run_dir, {"design_spec_path": str(design_csv)})

    assert isinstance(result, PhaseBlocked)
    assert result.item_count == 1
    manual_dir = phase_run_dir / "manual_resolution"
    assert (manual_dir / "resolutions.yaml").exists()
    assert (manual_dir / "decomposition.json").exists()
    # Phase functions are pure primitives: they do not write run_meta.json
    # (that's the M2b REST router's responsibility).
    assert not (phase_run_dir / "run_meta.json").exists()


def test_phase_resumes_when_resolutions_filled(workspace_root: Path, design_csv: Path) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseBlocked, PhaseCompleted

    phase_run_dir = workspace_root / "out" / "agent_runs" / "refine.decomposition-check" / "rid-3"
    config = make_config(
        workspace_root, str(design_csv),
        decomposition_enabled=True, decomposition_blocking=True,
    )
    ctx = make_ctx(workspace_root)

    split = [{"spec_id": "S1", "reason": "high variance", "variance": 0.25}]
    with _patch_decomp(split=split, merge=[]):
        blocked = run(config, ctx, phase_run_dir, {"design_spec_path": str(design_csv)})
    assert isinstance(blocked, PhaseBlocked)

    resolutions_path = phase_run_dir / "manual_resolution" / "resolutions.yaml"
    data = yaml.safe_load(resolutions_path.read_text(encoding="utf-8"))
    for item in data.get("items") or []:
        item["chosen_option_id"] = "skip"
    resolutions_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    result = run(config, ctx, phase_run_dir, {"design_spec_path": str(design_csv)})
    assert isinstance(result, PhaseCompleted), f"got {result!r}"
    assert (phase_run_dir / "restructured.csv").exists()
    assert result.artifacts_index["restructured_csv"] == "restructured.csv"
    assert result.summary["resume"] is True
    assert result.summary["skipped"] >= 1


def test_phase_skips_when_decomposition_disabled_in_config(workspace_root: Path, design_csv: Path) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseCompleted

    phase_run_dir = workspace_root / "out" / "agent_runs" / "refine.decomposition-check" / "rid-4"
    # Opt out of decomposition explicitly (conftest default is enabled=True).
    config = make_config(workspace_root, str(design_csv), decomposition_enabled=False)
    ctx = make_ctx(workspace_root)

    result = run(config, ctx, phase_run_dir, {"design_spec_path": str(design_csv)})
    assert isinstance(result, PhaseCompleted)
    assert result.artifacts_index == {}
    assert result.summary == {"skipped": True, "reason": "decomposition_disabled"}
    # Fix 1: no decomposition_flags.json in the disabled-skip branch.
    assert not (phase_run_dir / "decomposition_flags.json").exists()
    assert not (phase_run_dir / "restructured.csv").exists()
    # Phase functions are pure primitives: no run_meta.json.
    assert not (phase_run_dir / "run_meta.json").exists()


def test_phase_failed_when_design_spec_missing(workspace_root: Path) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseFailed

    phase_run_dir = workspace_root / "out" / "agent_runs" / "refine.decomposition-check" / "rid-5"
    config = make_config(workspace_root, "")
    ctx = make_ctx(workspace_root)

    result = run(config, ctx, phase_run_dir, {"design_spec_path": str(workspace_root / "missing.csv")})
    assert isinstance(result, PhaseFailed)
    assert result.error_code == "input_missing"
