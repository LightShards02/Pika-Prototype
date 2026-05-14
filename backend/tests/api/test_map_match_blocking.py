"""End-to-end blocked → resolve → completed flow for map.match."""

from __future__ import annotations

from pathlib import Path

from tests.api._map_helpers import (
    blocking_mapper_output,
    clean_mapper_output_for_subunit,
    enable_map,
    write_map_inputs,
)
from tests.api._refine_helpers import wait_for_status


def test_blocked_then_resolve_advances_to_completed(client, ws1_dir: Path, monkeypatch) -> None:
    enable_map(ws1_dir)
    design_rel, codebase_rel = write_map_inputs(ws1_dir)

    from handlers.map_phases import match as phase_mod
    state = {"phase": "block"}

    def fake_invoke(**kwargs):
        tv = kwargs.get("template_vars") or {}
        csv = tv.get("design_spec_rows_csv", "")
        if state["phase"] == "block" and "A1" in csv:
            return blocking_mapper_output()
        return clean_mapper_output_for_subunit(tv)

    monkeypatch.setattr(phase_mod, "invoke_agent_with_schema_retry", fake_invoke)

    ws = client.post("/v1/workspaces", json={"path": str(ws1_dir)}).json()
    resp = client.post(
        "/v1/phases/map.match/runs",
        json={
            "workspace_id": ws["id"],
            "inputs": {"design_spec_path": design_rel, "codebase_dir": codebase_rel},
        },
    )
    phase_run_id = resp.json()["phase_run_id"]
    blocked = wait_for_status(client, phase_run_id, "blocked")
    assert blocked["status"] == "blocked"
    assert blocked["summary"]["item_count"] == 1

    items = client.get(f"/v1/phase-runs/{phase_run_id}/resolutions").json()["items"]
    assert len(items) == 1
    decisions = [{"item_id": it["item_id"], "decision": {"chosen_option_id": "A"}} for it in items]
    put_resp = client.put(f"/v1/phase-runs/{phase_run_id}/resolutions", json={"items": decisions})
    assert put_resp.json()["valid"] is True

    state["phase"] = "resolve"
    resolve_resp = client.post(f"/v1/phase-runs/{phase_run_id}/resolve")
    assert resolve_resp.status_code == 202, resolve_resp.text
    assert resolve_resp.json()["status"] == "running"

    final = wait_for_status(client, phase_run_id, "completed")
    assert final["status"] == "completed"
    phase_run_dir = (
        ws1_dir / "out" / "agent_runs" / "map.match" / phase_run_id
    )
    assert (phase_run_dir / "map_output.json").exists()
