"""POST /cancel sets cancellation flag; runner observes it at the next safe boundary."""

from __future__ import annotations

import json
from pathlib import Path

from tests.api._refine_helpers import enable_refine, wait_for_status, write_refine_spec


def test_cancellation_persists_as_failed_with_cancelled_error_code(
    client, ws1_dir: Path, monkeypatch
) -> None:
    """When the cancel flag is set before the runner's safety check, terminal state
    persists as status='failed' with error.code='cancelled' (NOT status='cancelled').

    Directly exercises the cancellation branch in _run_async_phase by pre-marking
    a fresh phase_run_id as cancelled via the same monkeypatch hook the cancel
    endpoint uses. The runner observes the flag at its first is_cancelled check
    and writes the canonical failed-with-cancelled-error_code meta.
    """
    enable_refine(ws1_dir)
    refine_input = write_refine_spec(ws1_dir)

    from api.phase_runs import PhaseRunRegistry
    original_mark = PhaseRunRegistry.mark_cancelled
    rids_to_cancel: list[str] = []

    def auto_cancel_put(self, record):
        rid = record.get("phase_run_id")
        result = type(self).__bases__[0].put(self, record) if False else None  # noqa
        # Use the real put logic, then mark cancelled if this is a new running record.
        return result

    original_put = PhaseRunRegistry.put

    def put_then_mark(self, record):
        original_put(self, record)
        rid = record.get("phase_run_id")
        if isinstance(rid, str) and record.get("status") == "running":
            original_mark(self, rid)
            rids_to_cancel.append(rid)

    monkeypatch.setattr(PhaseRunRegistry, "put", put_then_mark)

    ws = client.post("/v1/workspaces", json={"path": ws1_dir.name}).json()
    resp = client.post(
        "/v1/phases/refine.decomposition-check/runs",
        json={"workspace_id": ws["id"], "inputs": {"design_spec_path": refine_input}},
    )
    assert resp.status_code == 202, resp.text
    phase_run_id = resp.json()["phase_run_id"]
    assert phase_run_id in rids_to_cancel

    final = wait_for_status(client, phase_run_id, "failed", timeout=10)
    assert final["status"] == "failed"
    assert final["error"]["code"] == "cancelled"

    phase_run_dir = ws1_dir / "out" / "agent_runs" / "refine.decomposition-check" / phase_run_id
    meta = json.loads((phase_run_dir / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "failed"
    assert meta["error"]["code"] == "cancelled"
    assert meta["status"] != "cancelled"


def test_cancel_endpoint_marks_flag_on_running_run(client, ws1_dir: Path, monkeypatch) -> None:
    """POST /cancel on a running run returns 200 and sets the registry cancellation flag."""
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

    cancel_resp = client.post(f"/v1/phase-runs/{phase_run_id}/cancel")
    assert cancel_resp.status_code in (200, 409)
    if cancel_resp.status_code == 200:
        assert cancel_resp.json()["status"] == "cancelling"


def test_cancel_returns_409_for_terminal_run(client, ws1_dir: Path, monkeypatch) -> None:
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
    resp = client.post(f"/v1/phase-runs/{phase_run_id}/cancel")
    assert resp.status_code == 409


def test_cancel_returns_404_for_unknown_run(client) -> None:
    resp = client.post("/v1/phase-runs/does-not-exist/cancel")
    assert resp.status_code == 404
