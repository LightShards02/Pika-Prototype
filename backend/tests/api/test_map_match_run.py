"""End-to-end async run for map.match: 202 + SSE + terminal completed + cache replay."""

from __future__ import annotations

from pathlib import Path

from tests.api._map_helpers import (
    clean_mapper_output_for_subunit,
    enable_map,
    write_map_inputs,
)
from tests.api._refine_helpers import wait_for_terminal


def test_async_run_completes_with_artifacts(client, ws1_dir: Path, monkeypatch) -> None:
    enable_map(ws1_dir)
    design_rel, codebase_rel = write_map_inputs(ws1_dir)

    from handlers.map_phases import match as phase_mod
    monkeypatch.setattr(
        phase_mod,
        "invoke_agent_with_schema_retry",
        lambda **kwargs: clean_mapper_output_for_subunit(kwargs.get("template_vars") or {}),
    )

    ws = client.post("/v1/workspaces", json={"path": str(ws1_dir)}).json()
    resp = client.post(
        "/v1/phases/map.match/runs",
        json={
            "workspace_id": ws["id"],
            "inputs": {"design_spec_path": design_rel, "codebase_dir": codebase_rel},
        },
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "running"
    assert body["events_url"] == f"/v1/phase-runs/{body['phase_run_id']}/events"

    terminal = wait_for_terminal(client, body["phase_run_id"])
    assert terminal["status"] == "completed", terminal.get("error")
    assert "map_output" in terminal["artifacts_index"]
    assert "subunit_outputs" in terminal["artifacts_index"]

    phase_run_dir = (
        ws1_dir / "out" / "agent_runs" / "map.match" / body["phase_run_id"]
    )
    assert (phase_run_dir / "map_output.json").exists()
    sub_files = list((phase_run_dir / "subunits").glob("*.json"))
    assert len(sub_files) == 2


def test_cache_replay_via_prior_match_run_id(client, ws1_dir: Path, monkeypatch) -> None:
    enable_map(ws1_dir)
    design_rel, codebase_rel = write_map_inputs(ws1_dir)

    from handlers.map_phases import match as phase_mod
    call_count = {"n": 0}

    def fake_invoke(**kwargs):
        call_count["n"] += 1
        return clean_mapper_output_for_subunit(kwargs.get("template_vars") or {})

    monkeypatch.setattr(phase_mod, "invoke_agent_with_schema_retry", fake_invoke)

    ws = client.post("/v1/workspaces", json={"path": str(ws1_dir)}).json()
    first = client.post(
        "/v1/phases/map.match/runs",
        json={
            "workspace_id": ws["id"],
            "inputs": {"design_spec_path": design_rel, "codebase_dir": codebase_rel},
        },
    ).json()
    wait_for_terminal(client, first["phase_run_id"])
    first_calls = call_count["n"]
    assert first_calls > 0

    second = client.post(
        "/v1/phases/map.match/runs",
        json={
            "workspace_id": ws["id"],
            "inputs": {
                "design_spec_path": design_rel,
                "codebase_dir": codebase_rel,
                "prior_match_run_id": first["phase_run_id"],
            },
        },
    )
    assert second.status_code == 202, second.text
    terminal = wait_for_terminal(client, second.json()["phase_run_id"])
    assert terminal["status"] == "completed"
    assert call_count["n"] == first_calls  # no new agent calls
    assert terminal["summary"].get("cache_replay") is True
    assert terminal["summary"].get("source_phase_run_id") == first["phase_run_id"]


def test_missing_prior_run_returns_failed(client, ws1_dir: Path, monkeypatch) -> None:
    enable_map(ws1_dir)
    design_rel, codebase_rel = write_map_inputs(ws1_dir)

    from handlers.map_phases import match as phase_mod
    monkeypatch.setattr(
        phase_mod,
        "invoke_agent_with_schema_retry",
        lambda **kwargs: clean_mapper_output_for_subunit(kwargs.get("template_vars") or {}),
    )

    ws = client.post("/v1/workspaces", json={"path": str(ws1_dir)}).json()
    resp = client.post(
        "/v1/phases/map.match/runs",
        json={
            "workspace_id": ws["id"],
            "inputs": {
                "design_spec_path": design_rel,
                "codebase_dir": codebase_rel,
                "prior_match_run_id": "does-not-exist",
            },
        },
    )
    assert resp.status_code == 202, resp.text
    terminal = wait_for_terminal(client, resp.json()["phase_run_id"])
    assert terminal["status"] == "failed"
    assert terminal["error"]["code"] == "prior_phase_artifact_missing"


def test_sse_progress_events_emitted_during_async_run(client, ws1_dir: Path, monkeypatch) -> None:
    """Subscribing to /events during a map.match run sees per-subunit progress events
    before the terminal completed event."""
    import json
    import sys
    import threading

    enable_map(ws1_dir)
    design_rel, codebase_rel = write_map_inputs(ws1_dir)

    from handlers.map_phases import match as phase_mod

    started = threading.Event()
    gate = threading.Event()
    call_count = {"n": 0}

    def gated_agent(**kwargs):
        # Emit a recognizable progress line and pause once so the test has time to
        # subscribe to /events before the run finishes.
        call_count["n"] += 1
        print(f"[PIKA] Map subunit: running — call {call_count['n']}", file=sys.stderr, flush=True)
        started.set()
        gate.wait(timeout=5)
        return clean_mapper_output_for_subunit(kwargs.get("template_vars") or {})

    monkeypatch.setattr(phase_mod, "invoke_agent_with_schema_retry", gated_agent)

    ws = client.post("/v1/workspaces", json={"path": str(ws1_dir)}).json()
    resp = client.post(
        "/v1/phases/map.match/runs",
        json={
            "workspace_id": ws["id"],
            "inputs": {"design_spec_path": design_rel, "codebase_dir": codebase_rel},
        },
    )
    assert resp.status_code == 202, resp.text
    phase_run_id = resp.json()["phase_run_id"]

    assert started.wait(timeout=5)

    events: list[dict] = []
    progress_seen = threading.Event()

    def consume():
        try:
            with client.stream(
                "GET", f"/v1/phase-runs/{phase_run_id}/events", timeout=10.0,
            ) as stream:
                current: dict[str, str] = {}
                for raw_line in stream.iter_lines():
                    line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else raw_line
                    if not line:
                        if current:
                            events.append(current)
                            if current.get("event") == "progress":
                                progress_seen.set()
                            if current.get("event") in ("completed", "blocked", "failed", "cancelled"):
                                return
                            current = {}
                        continue
                    if line.startswith("event:"):
                        current["event"] = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        current["data"] = line.split(":", 1)[1].strip()
        except Exception:
            return

    consumer = threading.Thread(target=consume, daemon=True)
    consumer.start()
    progress_seen.wait(timeout=5)
    gate.set()
    consumer.join(timeout=10)

    progress_events = [e for e in events if e.get("event") == "progress"]
    terminal_events = [e for e in events if e.get("event") in ("completed", "blocked", "failed", "cancelled")]
    assert progress_events, f"expected at least one progress event, got {events}"
    assert any("Map subunit" in (e.get("data") or "") for e in progress_events), \
        f"expected a Map subunit progress event, got {progress_events}"
    assert terminal_events and terminal_events[-1]["event"] == "completed", \
        f"expected terminal completed event, got {events}"
