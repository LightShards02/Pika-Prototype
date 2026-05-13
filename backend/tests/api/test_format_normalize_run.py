"""End-to-end happy path for format.normalize."""

from __future__ import annotations

import json
from pathlib import Path


def test_format_normalize_happy_path(client, ws1_dir: Path) -> None:
    ws = client.post("/v1/workspaces", json={"path": str(ws1_dir)}).json()

    resp = client.post(
        f"/v1/phases/format.normalize/runs",
        json={
            "workspace_id": ws["id"],
            "chain_id": "c-1",
            "inputs": {"design_spec_path": "specs/raw_sads.csv"},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert body["phase"] == "format.normalize"
    assert body["workspace_id"] == ws["id"]
    assert body["chain_id"] == "c-1"
    assert body["artifacts_index"]["normalized"] == "normalized.csv"
    assert "workspace_output_path" in body["summary"]

    phase_run_dir = (
        ws1_dir / "out" / "agent_runs" / "format.normalize" / body["phase_run_id"]
    )
    assert (phase_run_dir / "normalized.csv").is_file()
    meta = json.loads((phase_run_dir / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "completed"
    assert meta["phase_run_id"] == body["phase_run_id"]
    assert meta["chain_id"] == "c-1"

    workspace_output = ws1_dir / "out" / "state" / "DESIGN-SPEC.csv"
    assert workspace_output.is_file()
    text = workspace_output.read_text(encoding="utf-8")
    assert "spec_id" in text  # contract column added by normalize


def test_phase_run_lookup_after_completion(client, ws1_dir: Path) -> None:
    ws = client.post("/v1/workspaces", json={"path": str(ws1_dir)}).json()
    created = client.post(
        f"/v1/phases/format.normalize/runs",
        json={
            "workspace_id": ws["id"],
            "inputs": {"design_spec_path": "specs/raw_sads.csv"},
        },
    ).json()

    fetched = client.get(f"/v1/phase-runs/{created['phase_run_id']}")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["phase_run_id"] == created["phase_run_id"]
    assert body["status"] == "completed"


def test_phase_run_lookup_unknown_id_returns_404(client) -> None:
    fetched = client.get("/v1/phase-runs/does-not-exist")
    assert fetched.status_code == 404
    body = fetched.json()
    assert body["detail"]["code"] == "phase_run_not_found"
    assert "does-not-exist" in body["detail"]["message"]


def test_run_meta_persists_running_then_terminal(client, ws1_dir: Path, monkeypatch) -> None:
    from api.routers import phases as phases_router

    statuses: list[str] = []
    original = phases_router._write_run_meta

    def spy(meta_path, payload):
        statuses.append(payload["status"])
        original(meta_path, payload)

    monkeypatch.setattr(phases_router, "_write_run_meta", spy)

    ws = client.post("/v1/workspaces", json={"path": str(ws1_dir)}).json()
    resp = client.post(
        "/v1/phases/format.normalize/runs",
        json={
            "workspace_id": ws["id"],
            "inputs": {"design_spec_path": "specs/raw_sads.csv"},
        },
    )
    assert resp.status_code == 200, resp.text

    assert "running" in statuses, statuses
    assert "completed" in statuses, statuses
    assert statuses.index("running") < statuses.index("completed")
