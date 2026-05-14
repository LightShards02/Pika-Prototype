"""Workspace-scoped phase-run listing: GET /v1/workspaces/{id}/phase-runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _make_record(
    *,
    phase_run_id: str,
    workspace_id: str,
    phase: str = "format.normalize",
    status: str = "completed",
    started_at: str = "20260510-150000-0001",
    chain_id: str | None = None,
    ended_at: str | None = "20260510-150001-0001",
    blocked_at: str | None = None,
    inputs: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
    artifacts_index: dict[str, str] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "phase_run_id": phase_run_id,
        "phase": phase,
        "workspace_id": workspace_id,
        "chain_id": chain_id,
        "status": status,
        "started_at": started_at,
        "ended_at": ended_at,
        "blocked_at": blocked_at,
        "inputs": inputs or {},
        "artifacts_index": artifacts_index or {},
        "summary": summary or {},
        "error": error,
    }


def _register_ws(client, ws_dir: Path) -> str:
    resp = client.post("/v1/workspaces", json={"path": str(ws_dir)})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_empty_workspace_returns_empty_list(client, ws1_dir: Path) -> None:
    ws_id = _register_ws(client, ws1_dir)
    resp = client.get(f"/v1/workspaces/{ws_id}/phase-runs")
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


def test_lists_runs_sorted_by_started_at_descending(client, app, ws1_dir: Path) -> None:
    ws_id = _register_ws(client, ws1_dir)
    registry = app.state.phase_run_registry

    registry.put(_make_record(phase_run_id="r-old", workspace_id=ws_id, started_at="20260510-100000-0001"))
    registry.put(_make_record(phase_run_id="r-new", workspace_id=ws_id, started_at="20260510-200000-0001"))
    registry.put(_make_record(phase_run_id="r-mid", workspace_id=ws_id, started_at="20260510-150000-0001"))

    resp = client.get(f"/v1/workspaces/{ws_id}/phase-runs")
    assert resp.status_code == 200, resp.text
    ids = [row["phase_run_id"] for row in resp.json()]
    assert ids == ["r-new", "r-mid", "r-old"]


def test_sort_is_stable_for_ties(client, app, ws1_dir: Path) -> None:
    ws_id = _register_ws(client, ws1_dir)
    registry = app.state.phase_run_registry

    registry.put(_make_record(phase_run_id="r-a", workspace_id=ws_id, started_at="20260510-150000-0001"))
    registry.put(_make_record(phase_run_id="r-b", workspace_id=ws_id, started_at="20260510-150000-0001"))
    registry.put(_make_record(phase_run_id="r-c", workspace_id=ws_id, started_at="20260510-150000-0001"))

    resp = client.get(f"/v1/workspaces/{ws_id}/phase-runs")
    assert resp.status_code == 200, resp.text
    ids = [row["phase_run_id"] for row in resp.json()]
    assert ids == ["r-a", "r-b", "r-c"]


def test_filter_by_status(client, app, ws1_dir: Path) -> None:
    ws_id = _register_ws(client, ws1_dir)
    registry = app.state.phase_run_registry

    registry.put(_make_record(phase_run_id="r-run", workspace_id=ws_id, status="running"))
    registry.put(_make_record(phase_run_id="r-done", workspace_id=ws_id, status="completed"))
    registry.put(_make_record(phase_run_id="r-blocked-1", workspace_id=ws_id, status="blocked"))
    registry.put(_make_record(phase_run_id="r-blocked-2", workspace_id=ws_id, status="blocked"))

    blocked = client.get(f"/v1/workspaces/{ws_id}/phase-runs?status=blocked").json()
    assert {row["phase_run_id"] for row in blocked} == {"r-blocked-1", "r-blocked-2"}

    running = client.get(f"/v1/workspaces/{ws_id}/phase-runs?status=running").json()
    assert [row["phase_run_id"] for row in running] == ["r-run"]

    completed = client.get(f"/v1/workspaces/{ws_id}/phase-runs?status=completed").json()
    assert [row["phase_run_id"] for row in completed] == ["r-done"]


def test_filter_by_phase(client, app, ws1_dir: Path) -> None:
    ws_id = _register_ws(client, ws1_dir)
    registry = app.state.phase_run_registry

    registry.put(_make_record(phase_run_id="r-fmt-1", workspace_id=ws_id, phase="format.normalize"))
    registry.put(_make_record(phase_run_id="r-fmt-2", workspace_id=ws_id, phase="format.normalize"))
    registry.put(_make_record(phase_run_id="r-refine", workspace_id=ws_id, phase="refine.quality-audit"))

    fmt = client.get(f"/v1/workspaces/{ws_id}/phase-runs?phase=format.normalize").json()
    assert {row["phase_run_id"] for row in fmt} == {"r-fmt-1", "r-fmt-2"}
    assert all(row["phase"] == "format.normalize" for row in fmt)


def test_filter_by_chain_id(client, app, ws1_dir: Path) -> None:
    ws_id = _register_ws(client, ws1_dir)
    registry = app.state.phase_run_registry

    registry.put(_make_record(phase_run_id="r-c1-a", workspace_id=ws_id, chain_id="c-X"))
    registry.put(_make_record(phase_run_id="r-c1-b", workspace_id=ws_id, chain_id="c-X"))
    registry.put(_make_record(phase_run_id="r-c2", workspace_id=ws_id, chain_id="c-Y"))
    registry.put(_make_record(phase_run_id="r-nochain", workspace_id=ws_id, chain_id=None))

    out = client.get(f"/v1/workspaces/{ws_id}/phase-runs?chain_id=c-X").json()
    assert {row["phase_run_id"] for row in out} == {"r-c1-a", "r-c1-b"}


def test_filters_combine_via_and(client, app, ws1_dir: Path) -> None:
    ws_id = _register_ws(client, ws1_dir)
    registry = app.state.phase_run_registry

    registry.put(_make_record(
        phase_run_id="r-target",
        workspace_id=ws_id,
        phase="format.normalize",
        status="completed",
    ))
    registry.put(_make_record(
        phase_run_id="r-wrong-phase",
        workspace_id=ws_id,
        phase="refine.quality-audit",
        status="completed",
    ))
    registry.put(_make_record(
        phase_run_id="r-wrong-status",
        workspace_id=ws_id,
        phase="format.normalize",
        status="blocked",
    ))

    out = client.get(
        f"/v1/workspaces/{ws_id}/phase-runs?status=completed&phase=format.normalize"
    ).json()
    assert [row["phase_run_id"] for row in out] == ["r-target"]


def test_unknown_filter_values_return_empty_list(client, app, ws1_dir: Path) -> None:
    ws_id = _register_ws(client, ws1_dir)
    registry = app.state.phase_run_registry
    registry.put(_make_record(phase_run_id="r-1", workspace_id=ws_id))

    resp_status = client.get(f"/v1/workspaces/{ws_id}/phase-runs?status=cancelled")
    assert resp_status.status_code == 200, resp_status.text
    assert resp_status.json() == []

    resp_phase = client.get(f"/v1/workspaces/{ws_id}/phase-runs?phase=does.not.exist")
    assert resp_phase.status_code == 200, resp_phase.text
    assert resp_phase.json() == []


def test_limit_caps_response(client, app, ws1_dir: Path) -> None:
    ws_id = _register_ws(client, ws1_dir)
    registry = app.state.phase_run_registry

    for i in range(150):
        registry.put(_make_record(
            phase_run_id=f"r-{i:04d}",
            workspace_id=ws_id,
            started_at=f"20260510-{i:06d}-0001",
        ))

    default = client.get(f"/v1/workspaces/{ws_id}/phase-runs").json()
    assert len(default) == 100

    capped = client.get(f"/v1/workspaces/{ws_id}/phase-runs?limit=10").json()
    assert len(capped) == 10
    # Descending sort: should be the 10 most recent (highest started_at suffix).
    assert capped[0]["phase_run_id"] == "r-0149"
    assert capped[-1]["phase_run_id"] == "r-0140"


def test_limit_invalid_returns_400(client, ws1_dir: Path) -> None:
    ws_id = _register_ws(client, ws1_dir)

    for bad in (0, 501, -1, 10_000):
        resp = client.get(f"/v1/workspaces/{ws_id}/phase-runs?limit={bad}")
        assert resp.status_code == 400, (bad, resp.text)
        assert resp.json()["detail"]["code"] == "invalid_limit"


def test_unknown_workspace_returns_404(client) -> None:
    resp = client.get("/v1/workspaces/aaaaaaaaaaaa/phase-runs")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "workspace_not_found"


def test_only_returns_runs_for_requested_workspace(client, app, ws1_dir: Path, tmp_path: Path) -> None:
    ws_a = _register_ws(client, ws1_dir)

    other = tmp_path / "ws_other"
    other.mkdir()
    ws_b = _register_ws(client, other)
    assert ws_a != ws_b

    registry = app.state.phase_run_registry
    registry.put(_make_record(phase_run_id="r-a1", workspace_id=ws_a))
    registry.put(_make_record(phase_run_id="r-a2", workspace_id=ws_a))
    registry.put(_make_record(phase_run_id="r-b1", workspace_id=ws_b))

    a_rows = client.get(f"/v1/workspaces/{ws_a}/phase-runs").json()
    assert {row["phase_run_id"] for row in a_rows} == {"r-a1", "r-a2"}

    b_rows = client.get(f"/v1/workspaces/{ws_b}/phase-runs").json()
    assert {row["phase_run_id"] for row in b_rows} == {"r-b1"}


def test_response_entry_shape_matches_phase_run_endpoint(client, app, ws1_dir: Path) -> None:
    ws_id = _register_ws(client, ws1_dir)
    registry = app.state.phase_run_registry

    registry.put(_make_record(
        phase_run_id="r-shape",
        workspace_id=ws_id,
        phase="format.normalize",
        status="completed",
        chain_id="c-Z",
        inputs={"design_spec_path": "specs/raw.csv"},
        artifacts_index={"normalized": "normalized.csv"},
        summary={"row_count": 7},
    ))

    listed = client.get(f"/v1/workspaces/{ws_id}/phase-runs").json()
    assert len(listed) == 1
    entry = listed[0]

    direct = client.get("/v1/phase-runs/r-shape").json()

    # Same set of fields, same values.
    assert set(entry.keys()) == set(direct.keys())
    for key in entry:
        assert entry[key] == direct[key], key


def test_malformed_started_at_sorts_last(client, app, ws1_dir: Path) -> None:
    """Records with malformed started_at must sort after valid timestamps,
    regardless of the lexicographic value of the malformed string. 'zzz' would
    have sorted FIRST under naive sorted(..., reverse=True) because it
    lexicographically exceeds any valid timestamp."""
    ws_id = _register_ws(client, ws1_dir)
    registry = app.state.phase_run_registry

    registry.put(_make_record(
        phase_run_id="r-newest",
        workspace_id=ws_id,
        started_at="20260514-120000-0001",
    ))
    registry.put(_make_record(
        phase_run_id="r-older",
        workspace_id=ws_id,
        started_at="20260513-090000-0001",
    ))
    registry.put(_make_record(
        phase_run_id="r-malformed-zzz",
        workspace_id=ws_id,
        started_at="zzz",
    ))

    out = client.get(f"/v1/workspaces/{ws_id}/phase-runs").json()
    ids = [row["phase_run_id"] for row in out]
    assert ids == ["r-newest", "r-older", "r-malformed-zzz"]
