"""POST /resolve advances a blocked phase-run to terminal completion."""

from __future__ import annotations

from pathlib import Path

from tests.api._refine_helpers import enable_refine, wait_for_status, write_refine_spec


def test_resolve_advances_blocked_run_to_completed(client, ws1_dir: Path, monkeypatch) -> None:
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
    phase_run_id = resp.json()["phase_run_id"]
    blocked = wait_for_status(client, phase_run_id, "blocked")
    assert blocked["status"] == "blocked"

    items = client.get(f"/v1/phase-runs/{phase_run_id}/resolutions").json()["items"]
    decisions = [{"item_id": it["item_id"], "decision": {"chosen_option_id": "skip"}} for it in items]
    put_resp = client.put(f"/v1/phase-runs/{phase_run_id}/resolutions", json={"items": decisions})
    assert put_resp.json()["valid"] is True

    resolve_resp = client.post(f"/v1/phase-runs/{phase_run_id}/resolve")
    assert resolve_resp.status_code == 202, resolve_resp.text
    assert resolve_resp.json()["status"] == "running"

    final = wait_for_status(client, phase_run_id, "completed")
    assert final["status"] == "completed"
    phase_run_dir = ws1_dir / "out" / "agent_runs" / "refine.decomposition-check" / phase_run_id
    assert (phase_run_dir / "restructured.csv").exists()


def test_resolve_with_unresolved_items_returns_422(client, ws1_dir: Path, monkeypatch) -> None:
    """Blocked run with unresolved items: /resolve returns 422 + unresolved_count > 0."""
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
    phase_run_id = resp.json()["phase_run_id"]
    wait_for_status(client, phase_run_id, "blocked")

    # Do not PUT any decisions; all items remain unresolved.
    resolve_resp = client.post(f"/v1/phase-runs/{phase_run_id}/resolve")
    assert resolve_resp.status_code == 422, resolve_resp.text
    body = resolve_resp.json()
    assert body["detail"]["code"] == "resolutions_invalid"
    assert body["detail"]["details"]["unresolved_count"] > 0


def test_resolve_resets_event_channel(client, ws1_dir: Path, monkeypatch) -> None:
    """POST /resolve must close+create the event channel so resume subscribers
    don't receive stale events from the prior blocked run."""
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

    bus = client.app.state.event_bus
    pre_resolve_channel = bus.subscribe(phase_run_id)

    items = client.get(f"/v1/phase-runs/{phase_run_id}/resolutions").json()["items"]
    decisions = [{"item_id": it["item_id"], "decision": {"chosen_option_id": "skip"}} for it in items]
    client.put(f"/v1/phase-runs/{phase_run_id}/resolutions", json={"items": decisions})

    client.post(f"/v1/phase-runs/{phase_run_id}/resolve")
    wait_for_status(client, phase_run_id, "completed")

    post_resolve_channel = bus.subscribe(phase_run_id)
    if pre_resolve_channel is not None and post_resolve_channel is not None:
        assert pre_resolve_channel is not post_resolve_channel


def test_resolve_returns_409_when_not_blocked(client, ws1_dir: Path, monkeypatch) -> None:
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

    resp = client.post(f"/v1/phase-runs/{phase_run_id}/resolve")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "run_not_blocked"
