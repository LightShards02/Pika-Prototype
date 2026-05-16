"""Per-workspace lock serializes concurrent async phase runs."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from tests.api._refine_helpers import enable_refine, wait_for_status, write_refine_spec


def test_two_runs_on_same_workspace_serialize(client, ws1_dir: Path, monkeypatch) -> None:
    enable_refine(ws1_dir)
    refine_input = write_refine_spec(ws1_dir)

    timestamps: list[tuple[str, float]] = []
    timestamps_lock = threading.Lock()

    def slow_decomp(rows, *, similarity_threshold, variance_threshold):
        with timestamps_lock:
            timestamps.append(("start", time.monotonic()))
        time.sleep(0.5)
        with timestamps_lock:
            timestamps.append(("end", time.monotonic()))
        return {"split_candidates": [], "merge_candidates": [], "skipped": False}

    from handlers.refine.phases import decomposition_check as phase_mod
    monkeypatch.setattr(phase_mod, "run_decomposition_check", slow_decomp)

    ws = client.post("/v1/workspaces", json={"path": ws1_dir.name}).json()
    rid1 = client.post(
        "/v1/phases/refine.decomposition-check/runs",
        json={"workspace_id": ws["id"], "inputs": {"design_spec_path": refine_input}},
    ).json()["phase_run_id"]
    rid2 = client.post(
        "/v1/phases/refine.decomposition-check/runs",
        json={"workspace_id": ws["id"], "inputs": {"design_spec_path": refine_input}},
    ).json()["phase_run_id"]

    wait_for_status(client, rid1, "completed", timeout=15)
    wait_for_status(client, rid2, "completed", timeout=15)

    starts = [t for kind, t in timestamps if kind == "start"]
    ends = [t for kind, t in timestamps if kind == "end"]
    assert len(starts) == 2 and len(ends) == 2
    starts.sort()
    ends.sort()
    assert starts[1] >= ends[0] - 0.05, (
        f"second run started before first ended: starts={starts} ends={ends}"
    )
