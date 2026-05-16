"""Error paths for POST /v1/phases/format.normalize/runs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _register_ws(client, ws1_dir: Path) -> str:
    return client.post("/v1/workspaces", json={"path": ws1_dir.name}).json()["id"]


def test_missing_required_input_returns_422(client, ws1_dir: Path) -> None:
    ws = _register_ws(client, ws1_dir)
    resp = client.post(
        "/v1/phases/format.normalize/runs",
        json={"workspace_id": ws, "inputs": {}},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "inputs_invalid"


def test_unknown_workspace_returns_404(client) -> None:
    resp = client.post(
        "/v1/phases/format.normalize/runs",
        json={"workspace_id": "ffffffffffff", "inputs": {"design_spec_path": "x.csv"}},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "workspace_not_found"


def test_unknown_phase_returns_404(client, ws1_dir: Path) -> None:
    ws = _register_ws(client, ws1_dir)
    resp = client.post(
        "/v1/phases/nope.unknown/runs",
        json={"workspace_id": ws, "inputs": {}},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "phase_not_found"


def test_path_traversal_returns_400(client, ws1_dir: Path) -> None:
    ws = _register_ws(client, ws1_dir)
    resp = client.post(
        "/v1/phases/format.normalize/runs",
        json={
            "workspace_id": ws,
            "inputs": {"design_spec_path": "../../../etc/passwd"},
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "input_outside_workspace"


def test_artifact_missing_returns_500_and_records_failed_meta(
    client, ws1_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import api.phases.format_normalize as fmt_mod

    monkeypatch.setattr(fmt_mod, "resolve_format_output_path", lambda _c, _p: None)

    ws = _register_ws(client, ws1_dir)
    resp = client.post(
        "/v1/phases/format.normalize/runs",
        json={
            "workspace_id": ws,
            "inputs": {"design_spec_path": "specs/raw_sads.csv"},
        },
    )
    assert resp.status_code == 500, resp.text
    body = resp.json()
    assert body["detail"]["code"] == "artifact_missing"
    phase_run_id = body["detail"]["details"]["phase_run_id"]

    meta_path = (
        ws1_dir / "out" / "agent_runs" / "format.normalize" / phase_run_id / "run_meta.json"
    )
    assert meta_path.is_file()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["status"] == "failed"
    assert meta["error"]["code"] == "artifact_missing"
    assert "summary" in meta
    assert meta["summary"] == {}
    assert "artifacts_index" in meta


def test_failed_run_lookup_returns_full_phase_run_response_shape(
    client, ws1_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import api.phases.format_normalize as fmt_mod

    monkeypatch.setattr(fmt_mod, "resolve_format_output_path", lambda _c, _p: None)

    ws = _register_ws(client, ws1_dir)
    failed = client.post(
        "/v1/phases/format.normalize/runs",
        json={
            "workspace_id": ws,
            "inputs": {"design_spec_path": "specs/raw_sads.csv"},
        },
    )
    phase_run_id = failed.json()["detail"]["details"]["phase_run_id"]

    lookup = client.get(f"/v1/phase-runs/{phase_run_id}")
    assert lookup.status_code == 200, lookup.text
    body = lookup.json()
    for field in (
        "phase_run_id",
        "phase",
        "workspace_id",
        "status",
        "started_at",
        "inputs",
        "artifacts_index",
        "summary",
        "error",
    ):
        assert field in body, f"missing required field {field!r}"
    assert body["status"] == "failed"
    assert body["error"]["code"] == "artifact_missing"
    assert body["summary"] == {}
    assert body["artifacts_index"] == {}
