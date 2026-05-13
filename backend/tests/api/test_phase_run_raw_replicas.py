"""GET /raw-replicas surfaces auditor_output_*.json files for refine.quality-audit runs."""

from __future__ import annotations

import json
from pathlib import Path


def _make_quality_run_record(ws1_dir: Path, phase_run_id: str) -> Path:
    phase_run_dir = ws1_dir / "out" / "agent_runs" / "refine.quality-audit" / phase_run_id
    phase_run_dir.mkdir(parents=True, exist_ok=True)
    (phase_run_dir / "auditor_output_0.json").write_text(json.dumps({"replica": 0, "items": []}), encoding="utf-8")
    (phase_run_dir / "auditor_output_1.json").write_text(json.dumps({"replica": 1, "items": []}), encoding="utf-8")
    meta = {
        "phase": "refine.quality-audit",
        "phase_run_id": phase_run_id,
        "workspace_id": "unused",
        "chain_id": None,
        "status": "completed",
        "started_at": "2026-01-01T00:00 UTC-7",
        "ended_at": "2026-01-01T00:01 UTC-7",
        "blocked_at": None,
        "inputs": {},
        "artifacts_index": {},
        "summary": {},
        "error": None,
    }
    (phase_run_dir / "run_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return phase_run_dir


def test_raw_replicas_returns_files(client, ws1_dir: Path) -> None:
    ws = client.post("/v1/workspaces", json={"path": str(ws1_dir)}).json()
    phase_run_id = "qa-test-1"
    _make_quality_run_record(ws1_dir, phase_run_id)
    from api.deps import get_phase_run_registry
    registry = client.app.state.phase_run_registry
    record = json.loads((ws1_dir / "out" / "agent_runs" / "refine.quality-audit" / phase_run_id / "run_meta.json").read_text(encoding="utf-8"))
    record["workspace_id"] = ws["id"]
    registry.put(record)

    resp = client.get(f"/v1/phase-runs/{phase_run_id}/raw-replicas")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 2
    assert {r["replica_index"] for r in body} == {0, 1}


def test_raw_replicas_returns_404_for_non_quality_audit(client, ws1_dir: Path) -> None:
    ws = client.post("/v1/workspaces", json={"path": str(ws1_dir)}).json()
    record = {
        "phase": "format.normalize",
        "phase_run_id": "fmt-1",
        "workspace_id": ws["id"],
        "chain_id": None,
        "status": "completed",
        "started_at": "2026-01-01T00:00 UTC-7",
        "ended_at": "2026-01-01T00:01 UTC-7",
        "blocked_at": None,
        "inputs": {},
        "artifacts_index": {},
        "summary": {},
        "error": None,
    }
    registry = client.app.state.phase_run_registry
    registry.put(record)

    resp = client.get("/v1/phase-runs/fmt-1/raw-replicas")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "raw_replicas_not_applicable"


def test_raw_replicas_returns_404_for_unknown_run(client) -> None:
    resp = client.get("/v1/phase-runs/does-not-exist/raw-replicas")
    assert resp.status_code == 404


def test_raw_replicas_empty_when_no_files_present(client, ws1_dir: Path) -> None:
    """Quality-audit run exists but no auditor_output_*.json files: 200 []."""
    ws = client.post("/v1/workspaces", json={"path": str(ws1_dir)}).json()
    phase_run_id = "qa-empty-1"
    phase_run_dir = ws1_dir / "out" / "agent_runs" / "refine.quality-audit" / phase_run_id
    phase_run_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "phase": "refine.quality-audit",
        "phase_run_id": phase_run_id,
        "workspace_id": ws["id"],
        "chain_id": None,
        "status": "completed",
        "started_at": "2026-01-01T00:00 UTC-7",
        "ended_at": "2026-01-01T00:01 UTC-7",
        "blocked_at": None,
        "inputs": {},
        "artifacts_index": {},
        "summary": {},
        "error": None,
    }
    (phase_run_dir / "run_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    registry = client.app.state.phase_run_registry
    registry.put(meta)

    resp = client.get(f"/v1/phase-runs/{phase_run_id}/raw-replicas")
    assert resp.status_code == 200, resp.text
    assert resp.json() == []
