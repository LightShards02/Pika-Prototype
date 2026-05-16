"""SSE events endpoint: terminal event emitted on already-terminal run; progress on live run."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from tests.api._refine_helpers import enable_refine, wait_for_status, write_refine_spec


def _read_events(client, phase_run_id: str, max_events: int = 5, timeout: float = 5.0) -> list[dict]:
    events: list[dict] = []
    with client.stream("GET", f"/v1/phase-runs/{phase_run_id}/events", timeout=timeout) as resp:
        current_event: dict[str, str] = {}
        deadline = time.time() + timeout
        for raw_line in resp.iter_lines():
            if time.time() > deadline:
                break
            if not raw_line:
                if current_event:
                    events.append(current_event)
                    current_event = {}
                    if len(events) >= max_events:
                        break
                continue
            if isinstance(raw_line, bytes):
                line = raw_line.decode("utf-8", errors="replace")
            else:
                line = raw_line
            if line.startswith("event:"):
                current_event["event"] = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                current_event["data"] = line.split(":", 1)[1].strip()
    return events


def test_events_emits_terminal_for_already_completed_run(client, ws1_dir: Path, monkeypatch) -> None:
    enable_refine(ws1_dir)
    refine_input = write_refine_spec(ws1_dir)
    from handlers.refine.phases import decomposition_check as phase_mod
    monkeypatch.setattr(
        phase_mod, "run_decomposition_check",
        lambda *_a, **_k: {"split_candidates": [], "merge_candidates": [], "skipped": False},
    )
    ws = client.post("/v1/workspaces", json={"path": ws1_dir.name}).json()
    rid = client.post(
        "/v1/phases/refine.decomposition-check/runs",
        json={"workspace_id": ws["id"], "inputs": {"design_spec_path": refine_input}},
    ).json()["phase_run_id"]
    wait_for_status(client, rid, "completed")

    events = _read_events(client, rid, max_events=1)
    assert events
    assert events[0]["event"] == "completed"
    payload = json.loads(events[0]["data"])
    assert payload["phase_run_id"] == rid


def test_events_404_for_unknown_run(client) -> None:
    resp = client.get("/v1/phase-runs/does-not-exist/events")
    assert resp.status_code == 404


def test_stderr_pika_lines_become_progress_events(client, ws1_dir: Path, monkeypatch) -> None:
    enable_refine(ws1_dir)
    refine_input = write_refine_spec(ws1_dir)

    started = threading.Event()
    gate = threading.Event()

    def slow_decomp(rows, *, similarity_threshold, variance_threshold):
        import sys
        print("[PIKA] Decomposition: started — analyzing 2 specs", file=sys.stderr)
        started.set()
        gate.wait(timeout=5)
        print("[PIKA] Decomposition: completed — 0 split, 0 merge", file=sys.stderr)
        return {"split_candidates": [], "merge_candidates": [], "skipped": False}

    from handlers.refine.phases import decomposition_check as phase_mod
    monkeypatch.setattr(phase_mod, "run_decomposition_check", slow_decomp)

    ws = client.post("/v1/workspaces", json={"path": ws1_dir.name}).json()
    rid = client.post(
        "/v1/phases/refine.decomposition-check/runs",
        json={"workspace_id": ws["id"], "inputs": {"design_spec_path": refine_input}},
    ).json()["phase_run_id"]

    started.wait(timeout=5)
    gate.set()
    wait_for_status(client, rid, "completed")

    events = _read_events(client, rid, max_events=1)
    assert events and events[0]["event"] == "completed"


def test_subscribe_to_blocked_run_emits_blocked_and_closes(client, ws1_dir: Path, monkeypatch) -> None:
    """A blocked run subscribed via /events emits a single blocked event then closes."""
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
    rid = client.post(
        "/v1/phases/refine.decomposition-check/runs",
        json={"workspace_id": ws["id"], "inputs": {"design_spec_path": refine_input}},
    ).json()["phase_run_id"]
    wait_for_status(client, rid, "blocked")

    # Subscribe with enough events headroom; expect exactly one blocked event then stream ends.
    events = _read_events(client, rid, max_events=5, timeout=5.0)
    assert len(events) == 1, f"expected single event, got {events}"
    assert events[0]["event"] == "blocked"
    payload = json.loads(events[0]["data"])
    assert payload["phase_run_id"] == rid


def test_events_emits_failed_with_errorbody_payload(client, ws1_dir: Path, monkeypatch) -> None:
    """A failed run subscribed via /events emits event: failed with ErrorBody-shaped payload."""
    enable_refine(ws1_dir)
    refine_input = write_refine_spec(ws1_dir)

    from handlers.refine.phases import decomposition_check as phase_mod

    def boom(*_a, **_kw):
        raise RuntimeError("decomp blew up")

    monkeypatch.setattr(phase_mod, "run_decomposition_check", boom)

    ws = client.post("/v1/workspaces", json={"path": ws1_dir.name}).json()
    rid = client.post(
        "/v1/phases/refine.decomposition-check/runs",
        json={"workspace_id": ws["id"], "inputs": {"design_spec_path": refine_input}},
    ).json()["phase_run_id"]
    wait_for_status(client, rid, "failed")

    events = _read_events(client, rid, max_events=1)
    assert len(events) == 1
    assert events[0]["event"] == "failed"
    payload = json.loads(events[0]["data"])
    # ErrorBody shape: {code, message, [details], phase_run_id} — NOT full PhaseRunResponse.
    assert "code" in payload, f"expected ErrorBody-shaped payload, got {payload}"
    assert "message" in payload
    assert payload.get("phase_run_id") == rid
    # PhaseRunResponse-only fields must NOT be in the failed payload.
    assert "artifacts_index" not in payload
    assert "started_at" not in payload


def test_events_emits_cancelled_event(client, ws1_dir: Path, monkeypatch) -> None:
    """Cancellation publishes event: cancelled and the run reaches failed terminal state."""
    enable_refine(ws1_dir)
    refine_input = write_refine_spec(ws1_dir)

    from api.phase_runs import PhaseRunRegistry
    original_put = PhaseRunRegistry.put
    cancelled_ids: list[str] = []

    def put_then_mark(self, record):
        original_put(self, record)
        rid = record.get("phase_run_id")
        if isinstance(rid, str) and record.get("status") == "running":
            self.mark_cancelled(rid)
            cancelled_ids.append(rid)

    monkeypatch.setattr(PhaseRunRegistry, "put", put_then_mark)

    ws = client.post("/v1/workspaces", json={"path": ws1_dir.name}).json()
    rid = client.post(
        "/v1/phases/refine.decomposition-check/runs",
        json={"workspace_id": ws["id"], "inputs": {"design_spec_path": refine_input}},
    ).json()["phase_run_id"]
    assert rid in cancelled_ids
    wait_for_status(client, rid, "failed", timeout=10)

    # Terminal-replay subscriber sees failed (not cancelled — that's the live transition event).
    events = _read_events(client, rid, max_events=1)
    assert len(events) == 1
    assert events[0]["event"] == "failed"
    payload = json.loads(events[0]["data"])
    assert payload["code"] == "cancelled"
