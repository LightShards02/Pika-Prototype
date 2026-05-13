"""Tests for handlers.refine.phases.quality_audit.run()."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests.refine_phases.conftest import make_config, make_ctx


def _import_phase():
    from handlers.refine.phases.quality_audit import QUALITY_AUDIT, run
    return QUALITY_AUDIT, run


def _mock_auditor(full: dict[str, Any], triage: dict[str, Any] | None = None):
    if triage is None:
        triage = {"manual_resolution_items": list(full.get("manual_resolution_items", []))}

    def fake_invoke(prompt_name: str = "", template_vars: dict | None = None, **_kwargs: Any) -> dict:
        mode = (template_vars or {}).get("enrich_mode", "full")
        return full if mode == "full" else triage

    return patch(
        "handlers.refine.impl.invoke_agent_with_schema_retry",
        side_effect=fake_invoke,
    )


def _empty_full() -> dict[str, Any]:
    return {
        "manual_resolution_items": [],
        "enrichments": [],
        "appendix_recommendations": [],
    }


def _untestable_item(spec_id: str = "S1", item_id: str = "QA-1") -> dict[str, Any]:
    return {
        "item_id": item_id,
        "title": "Untestable",
        "spec_id": spec_id,
        "concern_kinds": ["untestable_outcome"],
        "concern_evidence": [
            {
                "kind": "untestable_outcome",
                "evidence": "no measurable threshold",
                "test_type_if_fixed": "integration",
            },
        ],
        "consequence_class": "functional_defect",
        "worst_case": "slow response goes undetected",
        "suggested_improvement": "Return within 200ms.",
    }


def test_contract_shape() -> None:
    contract, _ = _import_phase()
    assert contract.name == "refine.quality-audit"
    assert contract.command == "refine"
    assert contract.can_block is True
    assert contract.destructive is False
    input_names = [i.name for i in contract.inputs]
    assert input_names == ["design_spec_path", "decomposition_check_run_id"]
    for inp in contract.inputs:
        if inp.name == "decomposition_check_run_id":
            assert inp.kind == "phase_run_ref"
            assert inp.ref_phase == "refine.decomposition-check"
    output_names = {o.name for o in contract.outputs}
    assert {
        "auditor_output",
        "auditor_raw_replicas",
        "enrichments",
        "summary",
        "enriched_csv",
        "test_plans",
    } <= output_names
    assert contract.recommended_prerequisites == ("refine.decomposition-check",)


def test_phase_completes_when_no_concerns(workspace_root: Path, design_csv: Path) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseCompleted

    phase_run_dir = workspace_root / "out" / "agent_runs" / "refine.quality-audit" / "qa-1"
    config = make_config(workspace_root, str(design_csv))
    ctx = make_ctx(workspace_root, run_id="qa-1")

    with _mock_auditor(_empty_full()):
        result = run(config, ctx, phase_run_dir, {"design_spec_path": str(design_csv)})

    assert isinstance(result, PhaseCompleted), f"got {result!r}"
    assert (phase_run_dir / "auditor_output.json").exists()
    assert (phase_run_dir / "summary.json").exists()
    assert "auditor_output" in result.artifacts_index
    assert "summary" in result.artifacts_index
    assert "enriched_csv" in result.artifacts_index
    enriched_rel = result.artifacts_index["enriched_csv"]
    assert not Path(enriched_rel).is_absolute()
    assert (phase_run_dir / enriched_rel).is_file()
    workspace_out = result.summary.get("workspace_output_path")
    assert workspace_out is not None
    assert Path(workspace_out).exists()


def test_phase_blocks_on_concerns(workspace_root: Path, design_csv: Path) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseBlocked

    phase_run_dir = workspace_root / "out" / "agent_runs" / "refine.quality-audit" / "qa-2"
    config = make_config(workspace_root, str(design_csv))
    ctx = make_ctx(workspace_root, run_id="qa-2")

    item = _untestable_item("S1", "QA-1")
    full = {
        "manual_resolution_items": [item],
        "enrichments": [],
        "appendix_recommendations": [],
    }
    with _mock_auditor(full):
        result = run(config, ctx, phase_run_dir, {"design_spec_path": str(design_csv)})

    assert isinstance(result, PhaseBlocked), f"got {result!r}"
    assert result.item_count == 1
    manual_dir = phase_run_dir / "manual_resolution"
    assert (manual_dir / "agent_review.json").exists()
    assert (manual_dir / "resolutions.yaml").exists()
    assert "agent_review" in result.blocking_reason


def test_phase_uses_decomposition_check_run_id_when_provided(
    workspace_root: Path, design_csv: Path,
) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseCompleted

    prior_run_id = "prior-decomp-1"
    prior_dir = workspace_root / "out" / "agent_runs" / "refine.decomposition-check" / prior_run_id
    prior_dir.mkdir(parents=True, exist_ok=True)
    restructured = prior_dir / "restructured.csv"
    restructured.write_text(
        "spec_id,module_tag,module_role,requirement\n"
        "X1,m,domain,The system shall do thing one.\n"
        "X2,m,domain,The system shall do thing two.\n",
        encoding="utf-8",
    )

    phase_run_dir = workspace_root / "out" / "agent_runs" / "refine.quality-audit" / "qa-3"
    config = make_config(workspace_root, str(design_csv))
    ctx = make_ctx(workspace_root, run_id="qa-3")

    captured: dict[str, Any] = {}

    def fake_invoke(prompt_name: str = "", template_vars: dict | None = None, **_kwargs: Any) -> dict:
        mode = (template_vars or {}).get("enrich_mode", "full")
        captured["csv"] = (template_vars or {}).get("design_spec_csv", "")
        if mode == "full":
            return _empty_full()
        return {"manual_resolution_items": []}

    with patch(
        "handlers.refine.impl.invoke_agent_with_schema_retry",
        side_effect=fake_invoke,
    ):
        result = run(
            config, ctx, phase_run_dir,
            {"decomposition_check_run_id": prior_run_id},
        )

    assert isinstance(result, PhaseCompleted), f"got {result!r}"
    assert "X1" in captured.get("csv", "")
    assert "S1" not in captured.get("csv", "")


def test_phase_returns_failed_when_prior_phase_artifact_missing(workspace_root: Path) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseFailed

    phase_run_dir = workspace_root / "out" / "agent_runs" / "refine.quality-audit" / "qa-4"
    config = make_config(workspace_root, "")
    ctx = make_ctx(workspace_root, run_id="qa-4")

    result = run(
        config, ctx, phase_run_dir,
        {"decomposition_check_run_id": "does-not-exist"},
    )

    assert isinstance(result, PhaseFailed)
    assert result.error_code == "prior_phase_artifact_missing"

    # Phase functions are pure primitives: no run_meta.json written here.
    # The M2b REST router writes terminal state run_meta from the PhaseFailed.
    assert not (phase_run_dir / "run_meta.json").exists()


def test_phase_returns_failed_when_no_inputs(workspace_root: Path) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseFailed

    phase_run_dir = workspace_root / "out" / "agent_runs" / "refine.quality-audit" / "qa-5"
    config = make_config(workspace_root, "")
    ctx = make_ctx(workspace_root, run_id="qa-5")

    result = run(config, ctx, phase_run_dir, {})
    assert isinstance(result, PhaseFailed)
    assert result.error_code == "inputs_invalid"


def test_per_replica_progress_events_emitted(
    workspace_root: Path, design_csv: Path, capsys: Any,
) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseCompleted

    phase_run_dir = workspace_root / "out" / "agent_runs" / "refine.quality-audit" / "qa-6"
    config = make_config(workspace_root, str(design_csv))
    ctx = make_ctx(workspace_root, run_id="qa-6")

    with _mock_auditor(_empty_full()):
        result = run(config, ctx, phase_run_dir, {"design_spec_path": str(design_csv)})

    assert isinstance(result, PhaseCompleted)
    captured = capsys.readouterr()
    stderr = captured.err
    assert "Agents.replica.0" in stderr
    assert "mode=full" in stderr
