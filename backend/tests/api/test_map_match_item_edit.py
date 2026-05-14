"""POST /resolutions/items/{i}/edit on a blocked map.match run."""

from __future__ import annotations

from pathlib import Path

from tests.api._map_helpers import (
    blocking_mapper_output,
    clean_mapper_output_for_subunit,
    enable_map,
    write_map_inputs,
)
from tests.api._refine_helpers import wait_for_status


def _start_blocked_map_run(client, ws1_dir: Path, monkeypatch) -> tuple[str, list[dict]]:
    enable_map(ws1_dir)
    design_rel, codebase_rel = write_map_inputs(ws1_dir)

    from handlers.map_phases import match as phase_mod

    def fake_invoke(**kwargs):
        tv = kwargs.get("template_vars") or {}
        csv = tv.get("design_spec_rows_csv", "")
        if "A1" in csv:
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
    wait_for_status(client, phase_run_id, "blocked")
    items = client.get(f"/v1/phase-runs/{phase_run_id}/resolutions").json()["items"]
    return phase_run_id, items


def test_edit_invokes_spec_editor_on_blocked_map_item(client, ws1_dir: Path, monkeypatch) -> None:
    fake_output = {
        "edit_type": "field",
        "field": "requirement",
        "new_text": "rewritten requirement text",
    }
    import handlers.resolve as resolve_mod
    monkeypatch.setattr(resolve_mod, "invoke_spec_editor", lambda *_a, **_kw: fake_output)
    monkeypatch.setattr(resolve_mod, "_invoke_spec_editor", lambda *_a, **_kw: fake_output)

    phase_run_id, items = _start_blocked_map_run(client, ws1_dir, monkeypatch)
    assert len(items) >= 1

    resp = client.post(
        f"/v1/phase-runs/{phase_run_id}/resolutions/items/0/edit",
        json={"user_guide": "tighten the wording"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["editor_output"] == fake_output
    assert body["item_index"] == 0
    assert body["phase_run_id"] == phase_run_id


def test_edit_returns_404_for_out_of_range_index_on_map(client, ws1_dir: Path, monkeypatch) -> None:
    phase_run_id, _items = _start_blocked_map_run(client, ws1_dir, monkeypatch)

    resp = client.post(
        f"/v1/phase-runs/{phase_run_id}/resolutions/items/999/edit",
        json={"user_guide": "out of range"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "item_index_out_of_range"
