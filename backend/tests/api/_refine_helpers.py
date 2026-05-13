"""Helpers shared by M2b refine-phase tests."""

from __future__ import annotations

import time
from pathlib import Path

import yaml


def enable_refine(ws: Path) -> None:
    cfg_path = ws / "config" / "config.yaml"
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    data["commands"]["refine"]["enabled"] = True
    data["commands"]["refine"]["decomposition"]["enabled"] = True
    data["commands"]["refine"]["decomposition"]["blocking"] = True
    cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")


def write_refine_spec(ws: Path) -> str:
    path = ws / "specs" / "refine_input.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "spec_id,module_tag,module_role,requirement\n"
        "S1,core,domain,The system shall validate user input.\n"
        "S2,core,domain,The system shall return results quickly.\n",
        encoding="utf-8",
    )
    return "specs/refine_input.csv"


def wait_for_terminal(client, phase_run_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/v1/phase-runs/{phase_run_id}")
        body = resp.json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError(f"phase_run {phase_run_id} did not reach terminal state within {timeout}s")


def wait_for_status(client, phase_run_id: str, target: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/v1/phase-runs/{phase_run_id}").json()
        if body["status"] == target:
            return body
        time.sleep(0.05)
    raise AssertionError(f"phase_run {phase_run_id} did not reach status {target!r} (last={body['status']})")
