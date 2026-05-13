"""End-to-end async run for implement.unified-planner: 202 + SSE + terminal completed."""

from __future__ import annotations

import json
from pathlib import Path

from tests.api._implement_helpers import (
    empty_planner_output,
    enable_implement,
    write_planner_inputs,
)
from tests.api._refine_helpers import wait_for_terminal


def test_async_run_completes_with_artifacts(client, ws1_dir: Path, monkeypatch) -> None:
    enable_implement(ws1_dir)
    design_rel, codebase_rel = write_planner_inputs(ws1_dir)

    from handlers.implement.phases import unified_planner as phase_mod
    monkeypatch.setattr(
        phase_mod,
        "invoke_with_semantic_retry",
        lambda **_kwargs: empty_planner_output(),
    )

    ws = client.post("/v1/workspaces", json={"path": str(ws1_dir)}).json()
    resp = client.post(
        "/v1/phases/implement.unified-planner/runs",
        json={
            "workspace_id": ws["id"],
            "inputs": {"design_spec_path": design_rel, "codebase_dir": codebase_rel},
        },
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "running"
    assert body["events_url"] == f"/v1/phase-runs/{body['phase_run_id']}/events"

    terminal = wait_for_terminal(client, body["phase_run_id"])
    assert terminal["status"] == "completed", terminal.get("error")
    assert "unified_plan" in terminal["artifacts_index"]
    assert "spec_issues" in terminal["artifacts_index"]

    phase_run_dir = (
        ws1_dir / "out" / "agent_runs" / "implement.unified-planner" / body["phase_run_id"]
    )
    assert (phase_run_dir / "unified_plan.json").exists()
    assert (phase_run_dir / "spec_issues.json").exists()


def test_cache_replay_via_prior_planner_run_id(client, ws1_dir: Path, monkeypatch) -> None:
    enable_implement(ws1_dir)
    design_rel, codebase_rel = write_planner_inputs(ws1_dir)

    from handlers.implement.phases import unified_planner as phase_mod
    call_count = {"n": 0}

    def fake_invoke(**_kwargs):
        call_count["n"] += 1
        return empty_planner_output()

    monkeypatch.setattr(phase_mod, "invoke_with_semantic_retry", fake_invoke)

    ws = client.post("/v1/workspaces", json={"path": str(ws1_dir)}).json()
    first = client.post(
        "/v1/phases/implement.unified-planner/runs",
        json={
            "workspace_id": ws["id"],
            "inputs": {"design_spec_path": design_rel, "codebase_dir": codebase_rel},
        },
    ).json()
    wait_for_terminal(client, first["phase_run_id"])
    assert call_count["n"] == 1

    second = client.post(
        "/v1/phases/implement.unified-planner/runs",
        json={
            "workspace_id": ws["id"],
            "inputs": {
                "design_spec_path": design_rel,
                "codebase_dir": codebase_rel,
                "prior_planner_run_id": first["phase_run_id"],
            },
        },
    )
    assert second.status_code == 202, second.text
    terminal = wait_for_terminal(client, second.json()["phase_run_id"])
    assert terminal["status"] == "completed"
    assert call_count["n"] == 1  # cache replay; no new agent call
    assert terminal["summary"].get("cache_replay") is True
    assert terminal["summary"].get("source_phase_run_id") == first["phase_run_id"]


def test_missing_prior_run_returns_failed(client, ws1_dir: Path, monkeypatch) -> None:
    enable_implement(ws1_dir)
    design_rel, codebase_rel = write_planner_inputs(ws1_dir)

    from handlers.implement.phases import unified_planner as phase_mod
    monkeypatch.setattr(
        phase_mod,
        "invoke_with_semantic_retry",
        lambda **_kwargs: empty_planner_output(),
    )

    ws = client.post("/v1/workspaces", json={"path": str(ws1_dir)}).json()
    resp = client.post(
        "/v1/phases/implement.unified-planner/runs",
        json={
            "workspace_id": ws["id"],
            "inputs": {
                "design_spec_path": design_rel,
                "codebase_dir": codebase_rel,
                "prior_planner_run_id": "does-not-exist",
            },
        },
    )
    assert resp.status_code == 202, resp.text
    terminal = wait_for_terminal(client, resp.json()["phase_run_id"])
    assert terminal["status"] == "failed"
    assert terminal["error"]["code"] == "prior_phase_artifact_missing"
