"""REST endpoint: read files under <workspace>/out/state/, with traversal guard."""

from __future__ import annotations

import json
from pathlib import Path


def _register(client, ws1_dir: Path) -> str:
    resp = client.post("/v1/workspaces", json={"path": str(ws1_dir)})
    assert resp.status_code == 200
    return resp.json()["id"]


def test_state_read_happy_path(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    state_root = ws1_dir / "out" / "state" / "test_plans"
    state_root.mkdir(parents=True, exist_ok=True)
    fixture = state_root / "S-04.json"
    fixture.write_text(json.dumps({"spec_id": "S-04", "plan": []}), encoding="utf-8")

    resp = client.get(f"/v1/workspaces/{wid}/state/test_plans/S-04.json")
    assert resp.status_code == 200
    assert json.loads(resp.text)["spec_id"] == "S-04"


def test_state_read_404_for_missing_path(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    resp = client.get(f"/v1/workspaces/{wid}/state/nope/missing.json")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "state_path_not_found"


def test_state_read_blocks_path_traversal(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    # URL-encoded ".." segments so the client does not pre-normalize the path before
    # the request reaches the route handler.
    resp = client.get(f"/v1/workspaces/{wid}/state/%2E%2E/%2E%2E/etc/passwd")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "state_path_outside_workspace"


def test_state_read_unknown_workspace_404(client) -> None:
    resp = client.get("/v1/workspaces/aaaaaaaaaaaa/state/anything.json")
    assert resp.status_code == 404


def test_state_read_returns_json_content_type_for_json_files(client, ws1_dir: Path) -> None:
    """GET /state/{path} on a .json file returns application/json content-type."""
    wid = _register(client, ws1_dir)
    test_plans = ws1_dir / "out" / "state" / "test_plans"
    test_plans.mkdir(parents=True, exist_ok=True)
    (test_plans / "S-01.json").write_text('{"spec_id": "S-01", "criteria": []}', encoding="utf-8")
    resp = client.get(f"/v1/workspaces/{wid}/state/test_plans/S-01.json")
    assert resp.status_code == 200, resp.text
    ct = resp.headers.get("content-type", "")
    assert ct.startswith("application/json"), f"expected application/json, got {ct!r}"
    body = resp.json()
    assert body["spec_id"] == "S-01"


def test_state_read_rejects_directory_target(client, ws1_dir: Path) -> None:
    """GET /state/{path} on a directory returns 400 state_path_not_file."""
    wid = _register(client, ws1_dir)
    (ws1_dir / "out" / "state" / "subdir").mkdir(parents=True, exist_ok=True)
    resp = client.get(f"/v1/workspaces/{wid}/state/subdir")
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "state_path_not_file"
