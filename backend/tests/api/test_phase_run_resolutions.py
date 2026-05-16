"""GET/PUT /resolutions endpoints."""

from __future__ import annotations

from pathlib import Path

import yaml

from tests.api._refine_helpers import enable_refine, wait_for_status, write_refine_spec


def _start_blocked_decomp(client, ws1_dir: Path, monkeypatch) -> dict:
    enable_refine(ws1_dir)
    refine_input = write_refine_spec(ws1_dir)

    from handlers.refine.phases import decomposition_check as phase_mod

    def fake_decomp(rows, *, similarity_threshold, variance_threshold):
        return {
            "split_candidates": [
                {"spec_id": "S1", "reason": "high variance", "variance": 0.25},
            ],
            "merge_candidates": [],
            "skipped": False,
        }

    monkeypatch.setattr(phase_mod, "run_decomposition_check", fake_decomp)

    ws = client.post("/v1/workspaces", json={"path": ws1_dir.name}).json()
    resp = client.post(
        "/v1/phases/refine.decomposition-check/runs",
        json={"workspace_id": ws["id"], "inputs": {"design_spec_path": refine_input}},
    )
    body = resp.json()
    return wait_for_status(client, body["phase_run_id"], "blocked")


def test_get_resolutions_returns_items(client, ws1_dir: Path, monkeypatch) -> None:
    terminal = _start_blocked_decomp(client, ws1_dir, monkeypatch)
    phase_run_id = terminal["phase_run_id"]

    resp = client.get(f"/v1/phase-runs/{phase_run_id}/resolutions")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["phase_run_id"] == phase_run_id
    assert body["stage"] == "decomposition"
    assert isinstance(body["items"], list) and len(body["items"]) >= 1


def test_get_resolutions_returns_409_when_not_blocked(client, ws1_dir: Path, monkeypatch) -> None:
    enable_refine(ws1_dir)
    refine_input = write_refine_spec(ws1_dir)
    from handlers.refine.phases import decomposition_check as phase_mod
    monkeypatch.setattr(
        phase_mod, "run_decomposition_check",
        lambda *_a, **_k: {"split_candidates": [], "merge_candidates": [], "skipped": False},
    )
    ws = client.post("/v1/workspaces", json={"path": ws1_dir.name}).json()
    resp = client.post(
        "/v1/phases/refine.decomposition-check/runs",
        json={"workspace_id": ws["id"], "inputs": {"design_spec_path": refine_input}},
    )
    phase_run_id = resp.json()["phase_run_id"]
    wait_for_status(client, phase_run_id, "completed")

    resp = client.get(f"/v1/phase-runs/{phase_run_id}/resolutions")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "run_not_blocked"


def test_get_resolutions_404_for_unknown_run(client) -> None:
    resp = client.get("/v1/phase-runs/does-not-exist/resolutions")
    assert resp.status_code == 404


def test_put_resolutions_writes_decisions_and_validates(client, ws1_dir: Path, monkeypatch) -> None:
    terminal = _start_blocked_decomp(client, ws1_dir, monkeypatch)
    phase_run_id = terminal["phase_run_id"]
    items = client.get(f"/v1/phase-runs/{phase_run_id}/resolutions").json()["items"]
    item_id = items[0]["item_id"]

    resp = client.put(
        f"/v1/phase-runs/{phase_run_id}/resolutions",
        json={"items": [{"item_id": item_id, "decision": {"chosen_option_id": "skip"}}]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["valid"] is True
    assert body["resolved_count"] >= 1
    assert body["unresolved_count"] == 0


def test_put_resolutions_rejects_unknown_item_id(client, ws1_dir: Path, monkeypatch) -> None:
    terminal = _start_blocked_decomp(client, ws1_dir, monkeypatch)
    phase_run_id = terminal["phase_run_id"]
    resp = client.put(
        f"/v1/phase-runs/{phase_run_id}/resolutions",
        json={"items": [{"item_id": "no-such-item", "decision": {"chosen_option_id": "skip"}}]},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "items_invalid"


def test_put_resolutions_on_non_blocked_run_returns_409(client, ws1_dir: Path, monkeypatch) -> None:
    enable_refine(ws1_dir)
    refine_input = write_refine_spec(ws1_dir)
    from handlers.refine.phases import decomposition_check as phase_mod
    monkeypatch.setattr(
        phase_mod, "run_decomposition_check",
        lambda *_a, **_k: {"split_candidates": [], "merge_candidates": [], "skipped": False},
    )
    ws = client.post("/v1/workspaces", json={"path": ws1_dir.name}).json()
    resp = client.post(
        "/v1/phases/refine.decomposition-check/runs",
        json={"workspace_id": ws["id"], "inputs": {"design_spec_path": refine_input}},
    )
    phase_run_id = resp.json()["phase_run_id"]
    wait_for_status(client, phase_run_id, "completed")

    put_resp = client.put(
        f"/v1/phase-runs/{phase_run_id}/resolutions",
        json={"items": []},
    )
    assert put_resp.status_code == 409
    assert put_resp.json()["detail"]["code"] == "run_not_blocked"


def test_put_resolutions_on_unknown_run_returns_404(client) -> None:
    resp = client.put(
        "/v1/phase-runs/does-not-exist/resolutions",
        json={"items": []},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "phase_run_not_found"


def test_edit_invokes_spec_editor_on_blocked_item(client, ws1_dir: Path, monkeypatch) -> None:
    """Happy path: POST /resolutions/items/{i}/edit on a blocked run returns 200 + editor_output."""
    enable_refine(ws1_dir)
    refine_input = write_refine_spec(ws1_dir)
    from handlers.refine.phases import decomposition_check as phase_mod
    monkeypatch.setattr(
        phase_mod, "run_decomposition_check",
        lambda *_a, **_k: {
            "split_candidates": [{"spec_id": "S1", "reason": "x", "variance": 0.25}],
            "merge_candidates": [],
            "skipped": False,
        },
    )

    fake_output = {"edit_type": "structural", "edits": [{"action": "split", "spec_id": "S1"}]}
    import handlers.resolve as resolve_mod
    monkeypatch.setattr(resolve_mod, "invoke_spec_editor", lambda *_a, **_kw: fake_output)
    monkeypatch.setattr(resolve_mod, "_invoke_spec_editor", lambda *_a, **_kw: fake_output)

    ws = client.post("/v1/workspaces", json={"path": ws1_dir.name}).json()
    resp = client.post(
        "/v1/phases/refine.decomposition-check/runs",
        json={"workspace_id": ws["id"], "inputs": {"design_spec_path": refine_input}},
    )
    phase_run_id = resp.json()["phase_run_id"]
    wait_for_status(client, phase_run_id, "blocked")

    edit_resp = client.post(
        f"/v1/phase-runs/{phase_run_id}/resolutions/items/0/edit",
        json={"user_guide": "split into two specs"},
    )
    assert edit_resp.status_code == 200, edit_resp.text
    body = edit_resp.json()
    assert body["editor_output"] == fake_output
    assert body["item_index"] == 0
    assert body["phase_run_id"] == phase_run_id


def test_edit_returns_404_for_out_of_range_index(client, ws1_dir: Path, monkeypatch) -> None:
    enable_refine(ws1_dir)
    refine_input = write_refine_spec(ws1_dir)
    from handlers.refine.phases import decomposition_check as phase_mod
    monkeypatch.setattr(
        phase_mod, "run_decomposition_check",
        lambda *_a, **_k: {
            "split_candidates": [{"spec_id": "S1", "reason": "x", "variance": 0.25}],
            "merge_candidates": [],
            "skipped": False,
        },
    )
    ws = client.post("/v1/workspaces", json={"path": ws1_dir.name}).json()
    resp = client.post(
        "/v1/phases/refine.decomposition-check/runs",
        json={"workspace_id": ws["id"], "inputs": {"design_spec_path": refine_input}},
    )
    phase_run_id = resp.json()["phase_run_id"]
    wait_for_status(client, phase_run_id, "blocked")

    resp = client.post(
        f"/v1/phase-runs/{phase_run_id}/resolutions/items/999/edit",
        json={"user_guide": "test"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "item_index_out_of_range"
