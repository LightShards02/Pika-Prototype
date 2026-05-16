"""Workspace registration and listing endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_register_workspace_idempotent(client, ws1_dir: Path) -> None:
    first = client.post("/v1/workspaces", json={"path": ws1_dir.name})
    assert first.status_code == 200, first.text
    body = first.json()
    assert len(body["id"]) == 12
    assert body["exists"] is True
    assert body["config_resolved"] is True

    second = client.post("/v1/workspaces", json={"path": ws1_dir.name})
    assert second.status_code == 200
    assert second.json()["id"] == body["id"]


def test_get_workspace_returns_record(client, ws1_dir: Path) -> None:
    created = client.post("/v1/workspaces", json={"path": ws1_dir.name}).json()
    fetched = client.get(f"/v1/workspaces/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == created


def test_get_unknown_workspace_404(client) -> None:
    resp = client.get("/v1/workspaces/aaaaaaaaaaaa")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "workspace_not_found"


def test_register_missing_path_400(client, workspace_base: Path) -> None:
    # Relative target under base whose subdir does not exist on disk.
    resp = client.post("/v1/workspaces", json={"path": "does_not_exist"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "workspace_invalid"


def test_register_empty_path_400(client) -> None:
    resp = client.post("/v1/workspaces", json={"path": "   "})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "workspace_invalid"


def test_register_relative_resolves_under_base_dir(
    client, ws1_dir: Path, workspace_base: Path
) -> None:
    """Relative POST resolves under PIKA_WORKSPACE_BASE_DIR, not CWD."""
    resp = client.post("/v1/workspaces", json={"path": ws1_dir.name})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Path(body["path"]) == ws1_dir.resolve()
    assert Path(body["path"]).parent == workspace_base.resolve()
    assert body["exists"] is True


def test_register_idempotent_for_same_relative_path(client, ws1_dir: Path) -> None:
    """Two POSTs with the same relative path produce the same workspace id."""
    first = client.post("/v1/workspaces", json={"path": ws1_dir.name}).json()
    second = client.post("/v1/workspaces", json={"path": ws1_dir.name}).json()
    assert first["id"] == second["id"]
    assert first["path"] == second["path"]


def test_register_rejects_absolute_path(client, tmp_path: Path) -> None:
    resp = client.post("/v1/workspaces", json={"path": str(tmp_path)})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "workspace_path_must_be_relative"


def test_register_rejects_path_traversal(client) -> None:
    resp = client.post("/v1/workspaces", json={"path": "../somewhere"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "workspace_path_escapes_base"


def test_register_creates_base_dir_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Base dir is bootstrapped on demand; the workspace subdir must already exist."""
    import shutil
    from fastapi.testclient import TestClient

    from api.app import create_app
    from api.phase_registry import get_phase_registry

    state_dir = tmp_path / "api_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PIKA_API_STATE_DIR", str(state_dir))

    base = tmp_path / "missing_base"
    assert not base.exists()
    monkeypatch.setenv("PIKA_WORKSPACE_BASE_DIR", str(base))

    # Materialize a workspace subdir AFTER base does not yet exist on disk.
    # We pre-create only the workspace subdir so the base directory was missing
    # at app-construction time, then we materialize the subdir before posting.
    fixture_src = Path(__file__).resolve().parent / "fixtures" / "ws1"

    get_phase_registry().clear()
    app = create_app()
    # create_app() may have created the base via api_state plumbing? It should not have:
    # the base dir is only mkdir'd on register(). So at this point base still must exist
    # before we post -- but we want to demonstrate that register() creates it.
    # If create_app already created it (e.g. some unexpected side effect), remove it.
    if base.exists():
        shutil.rmtree(base)
    assert not base.exists()

    with TestClient(app) as client:
        # Without the subdir present, register() must fail with workspace_invalid
        # but the base directory must have been created in the process.
        resp = client.post("/v1/workspaces", json={"path": "myws"})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "workspace_invalid"
        assert base.exists() and base.is_dir()

        # Now materialize the workspace subdir and retry.
        dest = base / "myws"
        shutil.copytree(fixture_src, dest)
        resp = client.post("/v1/workspaces", json={"path": "myws"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert Path(body["path"]) == dest.resolve()


def test_workspace_base_dir_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PIKA_WORKSPACE_BASE_DIR is honored when constructing the app."""
    import shutil
    from fastapi.testclient import TestClient

    from api.app import create_app
    from api.phase_registry import get_phase_registry

    state_dir = tmp_path / "api_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PIKA_API_STATE_DIR", str(state_dir))

    override = tmp_path / "override_base"
    override.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PIKA_WORKSPACE_BASE_DIR", str(override))

    fixture_src = Path(__file__).resolve().parent / "fixtures" / "ws1"
    shutil.copytree(fixture_src, override / "ws1")

    get_phase_registry().clear()
    app = create_app()
    with TestClient(app) as client:
        resp = client.post("/v1/workspaces", json={"path": "ws1"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert Path(body["path"]) == (override / "ws1").resolve()


def test_workspace_base_dir_default_is_dataset_nutrition_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the env var, workspace_base_dir() points at <repo_root>/dataset/nutrition/backend."""
    from api.deps import repo_root, workspace_base_dir

    monkeypatch.delenv("PIKA_WORKSPACE_BASE_DIR", raising=False)
    expected = (repo_root() / "dataset" / "nutrition" / "backend").resolve()
    assert workspace_base_dir() == expected


def test_list_workspaces_empty_returns_empty_list(client) -> None:
    resp = client.get("/v1/workspaces")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_workspaces_returns_all_registered_sorted_by_path(
    client, workspace_base: Path
) -> None:
    """Register two workspaces and verify list response is path-ascending."""
    import shutil

    fixture_src = Path(__file__).resolve().parent / "fixtures" / "ws1"
    shutil.copytree(fixture_src, workspace_base / "alpha")
    shutil.copytree(fixture_src, workspace_base / "bravo")

    alpha = client.post("/v1/workspaces", json={"path": "alpha"}).json()
    bravo = client.post("/v1/workspaces", json={"path": "bravo"}).json()

    resp = client.get("/v1/workspaces")
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) == 2
    # Sorted by path ascending.
    assert entries[0]["path"] < entries[1]["path"]
    ids = [e["id"] for e in entries]
    assert set(ids) == {alpha["id"], bravo["id"]}


def test_list_workspace_entries_match_get_by_id(client, workspace_base: Path) -> None:
    """Each list entry equals GET /v1/workspaces/{id} for that id."""
    import shutil

    fixture_src = Path(__file__).resolve().parent / "fixtures" / "ws1"
    shutil.copytree(fixture_src, workspace_base / "alpha")
    shutil.copytree(fixture_src, workspace_base / "bravo")

    client.post("/v1/workspaces", json={"path": "alpha"})
    client.post("/v1/workspaces", json={"path": "bravo"})

    listing = client.get("/v1/workspaces").json()
    assert len(listing) == 2
    for entry in listing:
        single = client.get(f"/v1/workspaces/{entry['id']}").json()
        assert single == entry
