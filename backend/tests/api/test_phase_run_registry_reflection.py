"""PhaseRunRegistry hydrates run_meta.json on startup."""

from __future__ import annotations

import json
from pathlib import Path


def test_registry_reflects_existing_run_meta(client, ws1_dir: Path) -> None:
    """Write a synthetic run_meta.json under the workspace and verify a fresh
    PhaseRunRegistry picks it up after registering the workspace + reloading."""
    ws = client.post("/v1/workspaces", json={"path": ws1_dir.name}).json()

    phase_run_id = "20260510-153000-abcd"
    run_dir = ws1_dir / "out" / "agent_runs" / "format.normalize" / phase_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "phase": "format.normalize",
        "phase_run_id": phase_run_id,
        "workspace_id": ws["id"],
        "chain_id": None,
        "status": "completed",
        "started_at": "2026-05-10T15:30:00 UTC+0",
        "ended_at": "2026-05-10T15:30:05 UTC+0",
        "blocked_at": None,
        "inputs": {"design_spec_path": "specs/raw_sads.csv"},
        "artifacts_index": {"normalized": "normalized.csv"},
        "error": None,
    }
    (run_dir / "run_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    # Rebuild app to trigger reflection over registered workspaces.
    from api.phase_registry import get_phase_registry
    from api.app import create_app
    from fastapi.testclient import TestClient

    get_phase_registry().clear()
    app = create_app()
    with TestClient(app) as fresh_client:
        # Workspace registry persists on disk, so the new app re-loads it and
        # reflection visits its out/agent_runs tree.
        resp = fresh_client.get(f"/v1/phase-runs/{phase_run_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["phase_run_id"] == phase_run_id
        assert body["status"] == "completed"
