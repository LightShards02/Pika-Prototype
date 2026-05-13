"""Workspace registration endpoints."""

from __future__ import annotations

from pathlib import Path


def test_register_workspace_idempotent(client, ws1_dir: Path) -> None:
    first = client.post("/v1/workspaces", json={"path": str(ws1_dir)})
    assert first.status_code == 200, first.text
    body = first.json()
    assert len(body["id"]) == 12
    assert body["exists"] is True
    assert body["config_resolved"] is True

    second = client.post("/v1/workspaces", json={"path": str(ws1_dir)})
    assert second.status_code == 200
    assert second.json()["id"] == body["id"]


def test_get_workspace_returns_record(client, ws1_dir: Path) -> None:
    created = client.post("/v1/workspaces", json={"path": str(ws1_dir)}).json()
    fetched = client.get(f"/v1/workspaces/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == created


def test_get_unknown_workspace_404(client) -> None:
    resp = client.get("/v1/workspaces/aaaaaaaaaaaa")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "workspace_not_found"


def test_register_missing_path_400(client, tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist"
    resp = client.post("/v1/workspaces", json={"path": str(missing)})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "workspace_invalid"


def test_register_relative_path_resolves_to_absolute(client, ws1_dir: Path, monkeypatch) -> None:
    monkeypatch.chdir(ws1_dir.parent)
    relative = ws1_dir.name
    resp = client.post("/v1/workspaces", json={"path": relative})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Path(body["path"]) == ws1_dir.resolve()
    assert body["exists"] is True


def test_register_idempotent_across_path_forms(client, ws1_dir: Path, monkeypatch) -> None:
    abs_resp = client.post("/v1/workspaces", json={"path": str(ws1_dir)}).json()

    monkeypatch.chdir(ws1_dir.parent)
    rel_resp = client.post("/v1/workspaces", json={"path": ws1_dir.name}).json()

    assert abs_resp["id"] == rel_resp["id"]
    assert abs_resp["path"] == rel_resp["path"]


def test_register_empty_path_400(client) -> None:
    resp = client.post("/v1/workspaces", json={"path": "   "})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "workspace_invalid"
