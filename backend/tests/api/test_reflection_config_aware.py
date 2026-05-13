"""Reflection resolves the agent-runs root via the lifecycle helper, not a hardcoded path.

Verifies that ``_agent_runs_roots_for_known_workspaces`` goes through
``resolve_agent_runs_root(config, ws)`` rather than directly probing
``<ws>/out/agent_runs``. This is the contract that lets workspace-level
config overrides (when permitted by the schema, e.g. for refine in M2+) be
honored on restart.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_reflection_uses_lifecycle_resolver_for_agent_runs_root(
    client, ws1_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = client.post("/v1/workspaces", json={"path": str(ws1_dir)}).json()

    custom_root = ws1_dir / "alternate_agent_runs"
    phase_run_id = "20260512-093000-aaaa"
    run_dir = custom_root / "format.normalize" / phase_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "phase": "format.normalize",
        "phase_run_id": phase_run_id,
        "workspace_id": ws["id"],
        "chain_id": None,
        "status": "completed",
        "started_at": "2026-05-12T09:30:00 UTC+0",
        "ended_at": "2026-05-12T09:30:05 UTC+0",
        "blocked_at": None,
        "inputs": {"design_spec_path": "specs/raw_sads.csv"},
        "artifacts_index": {"normalized": "normalized.csv"},
        "summary": {},
        "error": None,
    }
    (run_dir / "run_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    from api import app as app_module
    monkeypatch.setattr(
        app_module,
        "resolve_agent_runs_root",
        lambda _config, ws_path: (
            (ws_path / "alternate_agent_runs").resolve()
            if (ws_path / "alternate_agent_runs").is_dir()
            else (ws_path / "out" / "agent_runs").resolve()
        ),
    )

    from api.phase_registry import get_phase_registry
    from fastapi.testclient import TestClient

    get_phase_registry().clear()
    fresh_app = app_module.create_app()
    with TestClient(fresh_app) as fresh_client:
        lookup = fresh_client.get(f"/v1/phase-runs/{phase_run_id}")
        assert lookup.status_code == 200, lookup.text
        body = lookup.json()
        assert body["phase_run_id"] == phase_run_id
        assert body["status"] == "completed"


def test_reflection_falls_back_to_default_when_config_load_fails(
    client, ws1_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = client.post("/v1/workspaces", json={"path": str(ws1_dir)}).json()

    phase_run_id = "20260512-094500-bbbb"
    run_dir = ws1_dir / "out" / "agent_runs" / "format.normalize" / phase_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "phase": "format.normalize",
        "phase_run_id": phase_run_id,
        "workspace_id": ws["id"],
        "chain_id": None,
        "status": "completed",
        "started_at": "2026-05-12T09:45:00 UTC+0",
        "ended_at": "2026-05-12T09:45:05 UTC+0",
        "blocked_at": None,
        "inputs": {"design_spec_path": "specs/raw_sads.csv"},
        "artifacts_index": {"normalized": "normalized.csv"},
        "summary": {},
        "error": None,
    }
    (run_dir / "run_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    from api import app as app_module
    monkeypatch.setattr(
        app_module, "load_workspace_config",
        lambda _ws: (_ for _ in ()).throw(RuntimeError("simulated config load failure")),
    )

    from api.phase_registry import get_phase_registry
    from fastapi.testclient import TestClient

    get_phase_registry().clear()
    fresh_app = app_module.create_app()
    with TestClient(fresh_app) as fresh_client:
        lookup = fresh_client.get(f"/v1/phase-runs/{phase_run_id}")
        assert lookup.status_code == 200, lookup.text
        assert lookup.json()["status"] == "completed"
