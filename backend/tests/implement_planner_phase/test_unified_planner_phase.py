"""Unit tests for handlers.implement.phases.unified_planner.run()."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests.implement_planner_phase.conftest import (
    empty_plan,
    make_config,
    make_ctx,
    planner_mr_item,
    spec_issue,
)


def _import_phase():
    from handlers.implement.phases.unified_planner import UNIFIED_PLANNER, run
    return UNIFIED_PLANNER, run


def _patch_planner(output: dict[str, Any], counter: dict[str, int] | None = None):
    if counter is None:
        counter = {"calls": 0}

    def fake_invoke(**_kwargs: Any) -> dict[str, Any]:
        counter["calls"] = counter.get("calls", 0) + 1
        return output

    return patch(
        "handlers.implement.phases.unified_planner.invoke_with_semantic_retry",
        side_effect=fake_invoke,
    ), counter


def test_contract_shape() -> None:
    contract, _ = _import_phase()
    assert contract.name == "implement.unified-planner"
    assert contract.command == "implement"
    assert contract.async_execution is True
    assert contract.can_block is True
    assert contract.destructive is False
    input_names = [i.name for i in contract.inputs]
    assert input_names == [
        "design_spec_path",
        "codebase_dir",
        "project_context_path",
        "prior_planner_run_id",
    ]
    by_name = {i.name: i for i in contract.inputs}
    assert by_name["design_spec_path"].required is True
    assert by_name["codebase_dir"].required is True
    assert by_name["project_context_path"].required is False
    assert by_name["prior_planner_run_id"].required is False
    assert by_name["prior_planner_run_id"].kind == "phase_run_ref"
    assert by_name["prior_planner_run_id"].ref_phase == "implement.unified-planner"
    output_names = {o.name for o in contract.outputs}
    assert {"unified_plan", "spec_issues"} <= output_names
    assert contract.recommended_prerequisites == ("refine.quality-audit",)


def test_phase_completes_when_no_blocking_items(
    workspace_root: Path, design_csv: Path, codebase_dir: Path,
) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseCompleted

    phase_run_dir = workspace_root / "out" / "agent_runs" / "implement.unified-planner" / "pl-1"
    config = make_config(workspace_root)
    ctx = make_ctx(workspace_root, run_id="pl-1")

    patcher, _counter = _patch_planner(empty_plan())
    with patcher:
        result = run(
            config, ctx, phase_run_dir,
            {"design_spec_path": design_csv, "codebase_dir": codebase_dir},
        )

    assert isinstance(result, PhaseCompleted), f"got {result!r}"
    assert (phase_run_dir / "unified_plan.json").exists()
    assert (phase_run_dir / "spec_issues.json").exists()
    assert result.artifacts_index == {
        "unified_plan": "unified_plan.json",
        "spec_issues": "spec_issues.json",
    }
    assert result.summary["module_plans"] == 1
    assert result.summary["spec_issues"] == 0


def test_phase_blocks_on_planner_manual_items(
    workspace_root: Path, design_csv: Path, codebase_dir: Path,
) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseBlocked

    phase_run_dir = workspace_root / "out" / "agent_runs" / "implement.unified-planner" / "pl-2"
    config = make_config(workspace_root)
    ctx = make_ctx(workspace_root, run_id="pl-2")

    output = empty_plan()
    output["manual_resolution_items"] = [planner_mr_item("MR-1")]

    patcher, _counter = _patch_planner(output)
    with patcher:
        result = run(
            config, ctx, phase_run_dir,
            {"design_spec_path": design_csv, "codebase_dir": codebase_dir},
        )

    assert isinstance(result, PhaseBlocked), f"got {result!r}"
    assert result.item_count == 1
    manual_dir = phase_run_dir / "manual_resolution"
    assert (manual_dir / "unified_planner.json").exists()
    assert (manual_dir / "resolutions.yaml").exists()
    assert "planner=1" in result.blocking_reason
    assert "spec_issues=0" in result.blocking_reason


def test_phase_blocks_on_spec_issues_only(
    workspace_root: Path, design_csv: Path, codebase_dir: Path,
) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseBlocked

    phase_run_dir = workspace_root / "out" / "agent_runs" / "implement.unified-planner" / "pl-3"
    config = make_config(workspace_root)
    ctx = make_ctx(workspace_root, run_id="pl-3")

    output = empty_plan()
    output["spec_issues"] = [spec_issue("SI-1", "ambiguity", "S1")]

    patcher, _counter = _patch_planner(output)
    with patcher:
        result = run(
            config, ctx, phase_run_dir,
            {"design_spec_path": design_csv, "codebase_dir": codebase_dir},
        )

    assert isinstance(result, PhaseBlocked), f"got {result!r}"
    assert result.item_count == 1
    assert "planner=0" in result.blocking_reason
    assert "spec_issues=1" in result.blocking_reason
    issues_payload = json.loads((phase_run_dir / "spec_issues.json").read_text(encoding="utf-8"))
    assert len(issues_payload["spec_issues"]) == 1


def test_phase_blocks_coalesces_planner_and_spec_issues(
    workspace_root: Path, design_csv: Path, codebase_dir: Path,
) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseBlocked

    phase_run_dir = workspace_root / "out" / "agent_runs" / "implement.unified-planner" / "pl-4"
    config = make_config(workspace_root)
    ctx = make_ctx(workspace_root, run_id="pl-4")

    output = empty_plan()
    output["manual_resolution_items"] = [planner_mr_item("MR-1"), planner_mr_item("MR-2")]
    output["spec_issues"] = [
        spec_issue("SI-1", "ambiguity", "S1"),
        spec_issue("SI-2", "contradiction", "S2"),
    ]

    patcher, _counter = _patch_planner(output)
    with patcher:
        result = run(
            config, ctx, phase_run_dir,
            {"design_spec_path": design_csv, "codebase_dir": codebase_dir},
        )

    assert isinstance(result, PhaseBlocked)
    assert result.item_count == 4
    assert "planner=2" in result.blocking_reason
    assert "spec_issues=2" in result.blocking_reason
    manual_payload = json.loads(
        (phase_run_dir / "manual_resolution" / "unified_planner.json").read_text(encoding="utf-8")
    )
    item_ids = [item.get("item_id") for item in manual_payload["items"]]
    assert "MR-1" in item_ids and "MR-2" in item_ids
    assert "SI-1" in item_ids and "SI-2" in item_ids


def test_phase_resumes_when_resolutions_filled(
    workspace_root: Path, design_csv: Path, codebase_dir: Path,
) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseBlocked, PhaseCompleted

    phase_run_dir = workspace_root / "out" / "agent_runs" / "implement.unified-planner" / "pl-5"
    config = make_config(workspace_root)
    ctx = make_ctx(workspace_root, run_id="pl-5")

    blocked_output = empty_plan()
    blocked_output["manual_resolution_items"] = [planner_mr_item("MR-1")]
    patcher_block, counter = _patch_planner(blocked_output)
    with patcher_block:
        result_block = run(
            config, ctx, phase_run_dir,
            {"design_spec_path": design_csv, "codebase_dir": codebase_dir},
        )
    assert isinstance(result_block, PhaseBlocked)

    resolutions_path = phase_run_dir / "manual_resolution" / "resolutions.yaml"
    text = resolutions_path.read_text(encoding="utf-8")
    filled = text.replace("chosen_option_id: null", "chosen_option_id: A")
    resolutions_path.write_text(filled, encoding="utf-8")

    captured: dict[str, Any] = {}

    def fake_resume(**kwargs: Any) -> dict[str, Any]:
        captured["resolved_decisions"] = (kwargs.get("template_vars") or {}).get("resolved_decisions", "")
        captured["calls"] = captured.get("calls", 0) + 1
        return empty_plan()

    with patch(
        "handlers.implement.phases.unified_planner.invoke_with_semantic_retry",
        side_effect=fake_resume,
    ):
        result = run(
            config, ctx, phase_run_dir,
            {"design_spec_path": design_csv, "codebase_dir": codebase_dir},
        )

    assert isinstance(result, PhaseCompleted), f"got {result!r}"
    assert captured["calls"] == 1
    assert captured["resolved_decisions"], "resolved_decisions must be threaded into template_vars on resume"


def test_phase_uses_prior_planner_run_id(
    workspace_root: Path, design_csv: Path, codebase_dir: Path,
) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseCompleted

    prior_run_id = "prior-pl"
    prior_dir = (
        workspace_root / "out" / "agent_runs" / "implement.unified-planner" / prior_run_id
    )
    prior_dir.mkdir(parents=True, exist_ok=True)
    canned_plan = {"module_plans": [{"module_tag": "core", "planned_anchors": []}]}
    (prior_dir / "unified_plan.json").write_text(json.dumps(canned_plan), encoding="utf-8")
    (prior_dir / "spec_issues.json").write_text(json.dumps({"spec_issues": []}), encoding="utf-8")

    phase_run_dir = (
        workspace_root / "out" / "agent_runs" / "implement.unified-planner" / "pl-6"
    )
    config = make_config(workspace_root)
    ctx = make_ctx(workspace_root, run_id="pl-6")

    counter = {"calls": 0}

    def fake_invoke(**_kwargs: Any) -> dict[str, Any]:
        counter["calls"] += 1
        return empty_plan()

    with patch(
        "handlers.implement.phases.unified_planner.invoke_with_semantic_retry",
        side_effect=fake_invoke,
    ):
        result = run(
            config, ctx, phase_run_dir,
            {
                "design_spec_path": design_csv,
                "codebase_dir": codebase_dir,
                "prior_planner_run_id": prior_run_id,
            },
        )

    assert isinstance(result, PhaseCompleted), f"got {result!r}"
    assert counter["calls"] == 0
    assert (phase_run_dir / "unified_plan.json").exists()
    assert (phase_run_dir / "spec_issues.json").exists()
    assert result.summary.get("cache_replay") is True
    assert result.summary.get("source_phase_run_id") == prior_run_id


def test_phase_fails_when_prior_run_artifact_missing(
    workspace_root: Path, design_csv: Path, codebase_dir: Path,
) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseFailed

    phase_run_dir = (
        workspace_root / "out" / "agent_runs" / "implement.unified-planner" / "pl-7"
    )
    config = make_config(workspace_root)
    ctx = make_ctx(workspace_root, run_id="pl-7")

    result = run(
        config, ctx, phase_run_dir,
        {
            "design_spec_path": design_csv,
            "codebase_dir": codebase_dir,
            "prior_planner_run_id": "does-not-exist",
        },
    )

    assert isinstance(result, PhaseFailed)
    assert result.error_code == "prior_phase_artifact_missing"


def test_phase_fails_on_agent_exception(
    workspace_root: Path, design_csv: Path, codebase_dir: Path,
) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseFailed

    phase_run_dir = (
        workspace_root / "out" / "agent_runs" / "implement.unified-planner" / "pl-8"
    )
    config = make_config(workspace_root)
    ctx = make_ctx(workspace_root, run_id="pl-8")

    def boom(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("agent died")

    with patch(
        "handlers.implement.phases.unified_planner.invoke_with_semantic_retry",
        side_effect=boom,
    ):
        result = run(
            config, ctx, phase_run_dir,
            {"design_spec_path": design_csv, "codebase_dir": codebase_dir},
        )

    assert isinstance(result, PhaseFailed)
    assert result.error_code == "planner_failed"
    assert "agent died" in result.message


def test_memory_context_renders_into_template_vars(
    workspace_root: Path, design_csv: Path, codebase_dir: Path,
) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseCompleted

    phase_run_dir = (
        workspace_root / "out" / "agent_runs" / "implement.unified-planner" / "pl-mem"
    )
    config = make_config(workspace_root)
    ctx = make_ctx(workspace_root, run_id="pl-mem")
    from dataclasses import replace as _dc_replace
    ctx = _dc_replace(ctx, memory_context={
        "memory": "M", "lessons": "lesson-y", "tasks": "", "gaps": ""
    })

    captured: dict[str, Any] = {}

    def fake_invoke(**kwargs: Any) -> dict[str, Any]:
        captured["template_vars"] = kwargs.get("template_vars") or {}
        return empty_plan()

    with patch(
        "handlers.implement.phases.unified_planner.invoke_with_semantic_retry",
        side_effect=fake_invoke,
    ):
        result = run(
            config, ctx, phase_run_dir,
            {"design_spec_path": design_csv, "codebase_dir": codebase_dir},
        )

    assert isinstance(result, PhaseCompleted)
    rendered = captured["template_vars"].get("memory", "")
    assert "## Lessons" in rendered
    assert "lesson-y" in rendered
