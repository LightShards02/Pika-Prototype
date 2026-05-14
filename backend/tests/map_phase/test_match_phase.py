"""Unit tests for handlers.map_phases.match.run()."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests.map_phase.conftest import (
    blocking_subunit_output,
    clean_subunit_output,
    make_config,
    make_ctx,
)


def _import_phase():
    from handlers.map_phases.match import MAP_MATCH, run
    return MAP_MATCH, run


def _patch_mapper(side_effect: Any, counter: dict[str, int] | None = None):
    if counter is None:
        counter = {"calls": 0}

    if callable(side_effect):
        def wrapped(**kwargs: Any) -> dict[str, Any]:
            counter["calls"] = counter.get("calls", 0) + 1
            return side_effect(**kwargs)
        return patch(
            "handlers.map_phases.match.invoke_agent_with_schema_retry",
            side_effect=wrapped,
        ), counter

    def fake_invoke(**_kwargs: Any) -> dict[str, Any]:
        counter["calls"] = counter.get("calls", 0) + 1
        return side_effect
    return patch(
        "handlers.map_phases.match.invoke_agent_with_schema_retry",
        side_effect=fake_invoke,
    ), counter


def test_contract_shape() -> None:
    contract, _ = _import_phase()
    assert contract.name == "map.match"
    assert contract.command == "map"
    assert contract.async_execution is True
    assert contract.can_block is True
    assert contract.destructive is False
    input_names = [i.name for i in contract.inputs]
    assert input_names == [
        "design_spec_path",
        "codebase_dir",
        "project_context_path",
        "extra_prompt_path",
        "force_remap",
        "max_acceptance_chars",
        "prior_match_run_id",
    ]
    by_name = {i.name: i for i in contract.inputs}
    assert by_name["design_spec_path"].required is True
    assert by_name["codebase_dir"].required is True
    assert by_name["prior_match_run_id"].kind == "phase_run_ref"
    assert by_name["prior_match_run_id"].ref_phase == "map.match"
    output_names = {o.name for o in contract.outputs}
    assert {"map_output", "subunit_outputs"} <= output_names
    assert contract.recommended_prerequisites == ("refine.quality-audit",)


def _per_subunit_output(**kwargs: Any) -> dict[str, Any]:
    """Inspect template_vars to pick the right canned output per subunit."""
    tv = kwargs.get("template_vars") or {}
    csv = tv.get("design_spec_rows_csv", "")
    if "B1" in csv:
        return clean_subunit_output(["B1"])
    return clean_subunit_output(["A1", "A2"])


def test_phase_completes_when_no_blocking_items(
    workspace_root: Path, design_csv: Path, codebase_dir: Path,
) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseCompleted

    phase_run_dir = workspace_root / "out" / "agent_runs" / "map.match" / "m-1"
    config = make_config(workspace_root)
    ctx = make_ctx(workspace_root, run_id="m-1")

    patcher, counter = _patch_mapper(_per_subunit_output)
    with patcher:
        result = run(
            config, ctx, phase_run_dir,
            {"design_spec_path": design_csv, "codebase_dir": codebase_dir},
        )

    assert isinstance(result, PhaseCompleted), f"got {result!r}"
    assert (phase_run_dir / "map_output.json").exists()
    subunits_dir = phase_run_dir / "subunits"
    assert subunits_dir.exists()
    files = sorted(subunits_dir.glob("*.json"))
    assert len(files) == 2  # auth + profile
    assert result.artifacts_index["map_output"] == "map_output.json"
    assert result.artifacts_index["subunit_outputs"] == "subunits/*.json"
    assert result.summary["mappings"] == 3
    assert result.summary["subunits"] == 2
    assert counter["calls"] == 2


def test_phase_blocks_on_subunit_manual_items(
    workspace_root: Path, design_csv: Path, codebase_dir: Path,
) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseBlocked

    phase_run_dir = workspace_root / "out" / "agent_runs" / "map.match" / "m-2"
    config = make_config(workspace_root)
    ctx = make_ctx(workspace_root, run_id="m-2")

    def per_subunit(**kwargs: Any) -> dict[str, Any]:
        tv = kwargs.get("template_vars") or {}
        csv = tv.get("design_spec_rows_csv", "")
        if "B1" in csv:
            return clean_subunit_output(["B1"])
        return blocking_subunit_output("MR-1", "A1")

    patcher, _counter = _patch_mapper(per_subunit)
    with patcher:
        result = run(
            config, ctx, phase_run_dir,
            {"design_spec_path": design_csv, "codebase_dir": codebase_dir},
        )

    assert isinstance(result, PhaseBlocked), f"got {result!r}"
    assert result.item_count == 1
    manual_dir = phase_run_dir / "manual_resolution"
    assert (manual_dir / "map.json").exists()
    assert (manual_dir / "resolutions.yaml").exists()
    payload = json.loads((manual_dir / "map.json").read_text(encoding="utf-8"))
    assert payload["stage"] == "map"
    assert len(payload["items"]) == 1
    assert payload["items"][0]["item_id"] == "MR-1"


def test_phase_coalesces_multiple_blocking_subunits(
    workspace_root: Path, design_csv: Path, codebase_dir: Path,
) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseBlocked

    phase_run_dir = workspace_root / "out" / "agent_runs" / "map.match" / "m-2b"
    config = make_config(workspace_root)
    ctx = make_ctx(workspace_root, run_id="m-2b")

    def per_subunit(**kwargs: Any) -> dict[str, Any]:
        tv = kwargs.get("template_vars") or {}
        csv = tv.get("design_spec_rows_csv", "")
        if "B1" in csv:
            return blocking_subunit_output("MR-2", "B1")
        return blocking_subunit_output("MR-1", "A1")

    patcher, _ = _patch_mapper(per_subunit)
    with patcher:
        result = run(
            config, ctx, phase_run_dir,
            {"design_spec_path": design_csv, "codebase_dir": codebase_dir},
        )

    assert isinstance(result, PhaseBlocked)
    assert result.item_count == 2  # coalesced


def test_phase_resumes_when_resolutions_filled(
    workspace_root: Path, design_csv: Path, codebase_dir: Path,
) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseBlocked, PhaseCompleted

    phase_run_dir = workspace_root / "out" / "agent_runs" / "map.match" / "m-3"
    config = make_config(workspace_root)
    ctx = make_ctx(workspace_root, run_id="m-3")

    def block_then_clean(**kwargs: Any) -> dict[str, Any]:
        tv = kwargs.get("template_vars") or {}
        csv = tv.get("design_spec_rows_csv", "")
        if "B1" in csv:
            return clean_subunit_output(["B1"])
        return blocking_subunit_output("MR-1", "A1")

    patcher_block, _ = _patch_mapper(block_then_clean)
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

    captured: dict[str, Any] = {"calls": 0, "resolved_decisions": []}

    def fake_resume(**kwargs: Any) -> dict[str, Any]:
        captured["calls"] += 1
        tv = kwargs.get("template_vars") or {}
        captured["resolved_decisions"].append(tv.get("resolved_decisions", ""))
        csv = tv.get("design_spec_rows_csv", "")
        if "B1" in csv:
            return clean_subunit_output(["B1"])
        return clean_subunit_output(["A1", "A2"])

    with patch(
        "handlers.map_phases.match.invoke_agent_with_schema_retry",
        side_effect=fake_resume,
    ):
        result = run(
            config, ctx, phase_run_dir,
            {"design_spec_path": design_csv, "codebase_dir": codebase_dir},
        )

    assert isinstance(result, PhaseCompleted), f"got {result!r}"
    assert captured["calls"] == 2
    assert any(captured["resolved_decisions"]), "resolved_decisions must be threaded into template_vars on resume"


def test_phase_uses_prior_match_run_id(
    workspace_root: Path, design_csv: Path, codebase_dir: Path,
) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseCompleted

    prior_run_id = "prior-m"
    prior_dir = (
        workspace_root / "out" / "agent_runs" / "map.match" / prior_run_id
    )
    prior_dir.mkdir(parents=True, exist_ok=True)
    canned = {
        "manual_resolution_items": [],
        "run_summary": {},
        "created_at": "",
        "mappings": {"A1": {"status": "mapped", "code_refs": []}},
    }
    (prior_dir / "map_output.json").write_text(json.dumps(canned), encoding="utf-8")
    sub_dir = prior_dir / "subunits"
    sub_dir.mkdir(parents=True, exist_ok=True)
    (sub_dir / "auth.json").write_text(json.dumps(clean_subunit_output(["A1"])), encoding="utf-8")

    phase_run_dir = workspace_root / "out" / "agent_runs" / "map.match" / "m-4"
    config = make_config(workspace_root)
    ctx = make_ctx(workspace_root, run_id="m-4")

    counter = {"calls": 0}

    def fake_invoke(**_kwargs: Any) -> dict[str, Any]:
        counter["calls"] += 1
        return clean_subunit_output(["A1"])

    with patch(
        "handlers.map_phases.match.invoke_agent_with_schema_retry",
        side_effect=fake_invoke,
    ):
        result = run(
            config, ctx, phase_run_dir,
            {
                "design_spec_path": design_csv,
                "codebase_dir": codebase_dir,
                "prior_match_run_id": prior_run_id,
            },
        )

    assert isinstance(result, PhaseCompleted), f"got {result!r}"
    assert counter["calls"] == 0
    assert (phase_run_dir / "map_output.json").exists()
    assert (phase_run_dir / "subunits" / "auth.json").exists()
    assert result.summary.get("cache_replay") is True
    assert result.summary.get("source_phase_run_id") == prior_run_id


def test_phase_fails_when_prior_run_artifact_missing(
    workspace_root: Path, design_csv: Path, codebase_dir: Path,
) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseFailed

    phase_run_dir = workspace_root / "out" / "agent_runs" / "map.match" / "m-5"
    config = make_config(workspace_root)
    ctx = make_ctx(workspace_root, run_id="m-5")

    result = run(
        config, ctx, phase_run_dir,
        {
            "design_spec_path": design_csv,
            "codebase_dir": codebase_dir,
            "prior_match_run_id": "does-not-exist",
        },
    )

    assert isinstance(result, PhaseFailed)
    assert result.error_code == "prior_phase_artifact_missing"


def test_phase_rejects_path_traversal_prior_match_run_id(
    workspace_root: Path, design_csv: Path, codebase_dir: Path,
) -> None:
    """`prior_match_run_id` resolving outside the phase root must fail safe."""
    _, run = _import_phase()
    from core.phase_types import PhaseFailed

    phase_run_dir = workspace_root / "out" / "agent_runs" / "map.match" / "m-trav"
    config = make_config(workspace_root)
    ctx = make_ctx(workspace_root, run_id="m-trav")

    result = run(
        config, ctx, phase_run_dir,
        {
            "design_spec_path": design_csv,
            "codebase_dir": codebase_dir,
            "prior_match_run_id": "../../../etc",
        },
    )
    assert isinstance(result, PhaseFailed)
    assert result.error_code == "prior_phase_artifact_missing"


def test_phase_fails_on_agent_exception(
    workspace_root: Path, design_csv: Path, codebase_dir: Path,
) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseFailed

    phase_run_dir = workspace_root / "out" / "agent_runs" / "map.match" / "m-6"
    config = make_config(workspace_root)
    ctx = make_ctx(workspace_root, run_id="m-6")

    def boom(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("agent died")

    with patch(
        "handlers.map_phases.match.invoke_agent_with_schema_retry",
        side_effect=boom,
    ):
        result = run(
            config, ctx, phase_run_dir,
            {"design_spec_path": design_csv, "codebase_dir": codebase_dir},
        )

    assert isinstance(result, PhaseFailed)
    assert result.error_code == "map_agent_failed"
    assert "agent died" in result.message


def test_phase_returns_failed_when_code_ref_validation_raises(
    workspace_root: Path, design_csv: Path, codebase_dir: Path,
) -> None:
    """An invalid code-ref path from the mapper must produce PhaseFailed, not escape."""
    _, run = _import_phase()
    from core.phase_types import PhaseFailed

    phase_run_dir = workspace_root / "out" / "agent_runs" / "map.match" / "m-code-ref"
    config = make_config(workspace_root)
    ctx = make_ctx(workspace_root, run_id="m-code-ref")

    def boom(_merged, _codebase):
        raise ValueError("code_refs[0].path escapes codebase_dir")

    def per_subunit(**kwargs: Any) -> dict[str, Any]:
        tv = kwargs.get("template_vars") or {}
        csv = tv.get("design_spec_rows_csv", "")
        if "B1" in csv:
            return clean_subunit_output(["B1"])
        return clean_subunit_output(["A1", "A2"])

    with patch("handlers.map_phases.match.validate_code_ref_paths", side_effect=boom), \
         patch(
             "handlers.map_phases.match.invoke_agent_with_schema_retry",
             side_effect=per_subunit,
         ):
        result = run(
            config, ctx, phase_run_dir,
            {"design_spec_path": design_csv, "codebase_dir": codebase_dir},
        )

    assert isinstance(result, PhaseFailed)
    assert result.error_code == "map_code_ref_invalid"
    assert "escapes" in result.message


def test_phase_replays_from_subunits_only(
    workspace_root: Path, design_csv: Path, codebase_dir: Path,
) -> None:
    """Cache replay with only subunits/*.json (no map_output.json): loads subunits,
    runs the post-merge pipeline without agent calls, produces map_output.json."""
    _, run = _import_phase()
    from core.phase_types import PhaseCompleted

    prior_run_id = "prior-subunits-only"
    prior_run_dir = workspace_root / "out" / "agent_runs" / "map.match" / prior_run_id
    prior_subunits = prior_run_dir / "subunits"
    prior_subunits.mkdir(parents=True, exist_ok=True)
    (prior_subunits / "auth.json").write_text(json.dumps(clean_subunit_output(["A1", "A2"])), encoding="utf-8")
    (prior_subunits / "profile.json").write_text(json.dumps(clean_subunit_output(["B1"])), encoding="utf-8")

    phase_run_dir = workspace_root / "out" / "agent_runs" / "map.match" / "m-replay-subunits"
    config = make_config(workspace_root)
    ctx = make_ctx(workspace_root, run_id="m-replay-subunits")

    patcher, counter = _patch_mapper(_per_subunit_output)
    with patcher:
        result = run(
            config, ctx, phase_run_dir,
            {
                "design_spec_path": design_csv,
                "codebase_dir": codebase_dir,
                "prior_match_run_id": prior_run_id,
            },
        )

    assert isinstance(result, PhaseCompleted), f"got {result!r}"
    assert counter["calls"] == 0  # no agent calls during subunits-only replay
    assert (phase_run_dir / "map_output.json").exists()
    new_subunits = phase_run_dir / "subunits"
    assert (new_subunits / "auth.json").exists()
    assert (new_subunits / "profile.json").exists()
    assert result.summary["cache_replay"] is True
    assert result.summary["source_phase_run_id"] == prior_run_id


def test_memory_context_renders_into_template_vars(
    workspace_root: Path, design_csv: Path, codebase_dir: Path,
) -> None:
    _, run = _import_phase()
    from core.phase_types import PhaseCompleted

    phase_run_dir = workspace_root / "out" / "agent_runs" / "map.match" / "mp-mem"
    config = make_config(workspace_root)
    ctx = make_ctx(workspace_root, run_id="mp-mem")
    from dataclasses import replace as _dc_replace
    ctx = _dc_replace(ctx, memory_context={
        "memory": "", "lessons": "lesson-z", "tasks": "", "gaps": ""
    })

    captured: dict[str, Any] = {}

    def fake_invoke(**kwargs: Any) -> dict[str, Any]:
        tv = kwargs.get("template_vars") or {}
        captured.setdefault("template_vars", tv)
        csv = tv.get("design_spec_rows_csv", "")
        if "B1" in csv:
            return clean_subunit_output(["B1"])
        return clean_subunit_output(["A1", "A2"])

    with patch(
        "handlers.map_phases.match.invoke_agent_with_schema_retry",
        side_effect=fake_invoke,
    ):
        result = run(
            config, ctx, phase_run_dir,
            {"design_spec_path": design_csv, "codebase_dir": codebase_dir},
        )

    assert isinstance(result, PhaseCompleted)
    rendered = captured["template_vars"].get("memory", "")
    assert "## Lessons" in rendered
    assert "lesson-z" in rendered
