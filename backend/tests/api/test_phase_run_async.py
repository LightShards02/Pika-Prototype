"""Async phase-run lifecycle: 202 + running run_meta + terminal SSE event."""

from __future__ import annotations

import json
import time
from pathlib import Path

import yaml


def _enable_refine(ws: Path) -> None:
    cfg_path = ws / "config" / "config.yaml"
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    data["commands"]["refine"]["enabled"] = True
    data["commands"]["refine"]["decomposition"]["enabled"] = True
    cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")


def _write_refine_spec(ws: Path) -> str:
    path = ws / "specs" / "refine_input.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "spec_id,module_tag,module_role,requirement\n"
        "S1,core,domain,The system shall validate user input.\n"
        "S2,core,domain,The system shall return results quickly.\n",
        encoding="utf-8",
    )
    return "specs/refine_input.csv"


def _wait_for_terminal(client, phase_run_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/v1/phase-runs/{phase_run_id}")
        body = resp.json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError(f"phase_run {phase_run_id} did not reach terminal state within {timeout}s")


def test_async_create_returns_202_with_events_url(client, ws1_dir: Path, monkeypatch) -> None:
    _enable_refine(ws1_dir)
    refine_input = _write_refine_spec(ws1_dir)

    from handlers.refine.phases import decomposition_check as phase_mod

    def fake_decomp(rows, *, similarity_threshold, variance_threshold):
        return {"split_candidates": [], "merge_candidates": [], "skipped": False}

    monkeypatch.setattr(phase_mod, "run_decomposition_check", fake_decomp)

    ws = client.post("/v1/workspaces", json={"path": str(ws1_dir)}).json()

    resp = client.post(
        "/v1/phases/refine.decomposition-check/runs",
        json={
            "workspace_id": ws["id"],
            "inputs": {"design_spec_path": refine_input},
        },
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "running"
    assert body["events_url"] == f"/v1/phase-runs/{body['phase_run_id']}/events"

    phase_run_dir = ws1_dir / "out" / "agent_runs" / "refine.decomposition-check" / body["phase_run_id"]
    meta = json.loads((phase_run_dir / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["status"] in ("running", "completed", "blocked", "failed")

    terminal = _wait_for_terminal(client, body["phase_run_id"])
    assert terminal["status"] == "completed", terminal.get("error")


def test_async_phase_persists_terminal_meta(client, ws1_dir: Path, monkeypatch) -> None:
    _enable_refine(ws1_dir)
    refine_input = _write_refine_spec(ws1_dir)

    from handlers.refine.phases import decomposition_check as phase_mod

    def fake_decomp(rows, *, similarity_threshold, variance_threshold):
        return {"split_candidates": [], "merge_candidates": [], "skipped": False}

    monkeypatch.setattr(phase_mod, "run_decomposition_check", fake_decomp)

    ws = client.post("/v1/workspaces", json={"path": str(ws1_dir)}).json()
    resp = client.post(
        "/v1/phases/refine.decomposition-check/runs",
        json={"workspace_id": ws["id"], "inputs": {"design_spec_path": refine_input}},
    )
    phase_run_id = resp.json()["phase_run_id"]
    terminal = _wait_for_terminal(client, phase_run_id)
    assert terminal["status"] == "completed", terminal.get("error")

    phase_run_dir = ws1_dir / "out" / "agent_runs" / "refine.decomposition-check" / phase_run_id
    meta = json.loads((phase_run_dir / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "completed"
    assert "completed_stages" not in meta
    assert "blocked_at_stage" not in meta
    assert "resolution_status" not in meta


def test_format_normalize_still_returns_200_sync(client, ws1_dir: Path) -> None:
    ws = client.post("/v1/workspaces", json={"path": str(ws1_dir)}).json()
    resp = client.post(
        "/v1/phases/format.normalize/runs",
        json={"workspace_id": ws["id"], "inputs": {"design_spec_path": "specs/raw_sads.csv"}},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
