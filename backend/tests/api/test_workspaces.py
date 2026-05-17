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


# -- M6.7: opt-in workspace creation / config seeding ---------------------


def test_create_false_default_preserves_existing_behavior(
    client, workspace_base: Path
) -> None:
    """Omitting ``create`` (default false) leaves missing subdirs an error."""
    resp = client.post("/v1/workspaces", json={"path": "does_not_exist_default"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "workspace_invalid"
    # The subdir must NOT have been created.
    assert not (workspace_base / "does_not_exist_default").exists()


def test_create_true_creates_subdir_and_seeds_config(
    client, workspace_base: Path
) -> None:
    """``create=true`` mkdirs the workspace and seeds a default config."""
    resp = client.post(
        "/v1/workspaces", json={"path": "newws", "create": True}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    new_root = workspace_base / "newws"
    assert new_root.is_dir()
    config_path = new_root / "config" / "config.yaml"
    assert config_path.is_file()
    text = config_path.read_text(encoding="utf-8")
    assert "{{ name }}" not in text
    assert 'name: "newws"' in text
    # The seeded config makes config_resolved true.
    assert body["config_resolved"] is True
    assert body["exists"] is True
    assert Path(body["path"]) == new_root.resolve()


def test_create_true_is_idempotent(client, workspace_base: Path) -> None:
    """Re-POSTing with create=true does not rewrite an already-seeded config."""
    first = client.post(
        "/v1/workspaces", json={"path": "ws_idem", "create": True}
    )
    assert first.status_code == 200, first.text
    config_path = workspace_base / "ws_idem" / "config" / "config.yaml"
    assert config_path.is_file()
    original_bytes = config_path.read_bytes()
    original_mtime_ns = config_path.stat().st_mtime_ns

    second = client.post(
        "/v1/workspaces", json={"path": "ws_idem", "create": True}
    )
    assert second.status_code == 200, second.text

    # Same workspace id and config-file bytes; mtime must not have changed.
    assert second.json()["id"] == first.json()["id"]
    assert config_path.read_bytes() == original_bytes
    assert config_path.stat().st_mtime_ns == original_mtime_ns


def test_create_true_does_not_overwrite_existing_config(
    client, workspace_base: Path
) -> None:
    """When config.yaml already exists, create=true must not touch it."""
    target = workspace_base / "preexisting"
    (target / "config").mkdir(parents=True)
    config_path = target / "config" / "config.yaml"
    # An arbitrary placeholder body; we only care that bytes are preserved.
    original = b"# do not touch\nversion: 1\n"
    config_path.write_bytes(original)
    original_mtime_ns = config_path.stat().st_mtime_ns

    resp = client.post(
        "/v1/workspaces", json={"path": "preexisting", "create": True}
    )
    assert resp.status_code == 200, resp.text

    assert config_path.read_bytes() == original
    assert config_path.stat().st_mtime_ns == original_mtime_ns


def test_create_true_absolute_path_still_400(
    client, tmp_path: Path, workspace_base: Path
) -> None:
    """Absolute paths still fail with the canonical error when create=true."""
    resp = client.post(
        "/v1/workspaces",
        json={"path": str(tmp_path), "create": True},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "workspace_path_must_be_relative"
    # No seeding should have occurred anywhere under the base dir.
    assert list(workspace_base.iterdir()) == []


def test_create_true_traversal_still_400(
    client, workspace_base: Path
) -> None:
    """Traversal paths still fail with the canonical error when create=true."""
    resp = client.post(
        "/v1/workspaces", json={"path": "../escape", "create": True}
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "workspace_path_escapes_base"
    # Nothing was created under (or beside) the base dir.
    assert not (workspace_base.parent / "escape").exists()
    assert list(workspace_base.iterdir()) == []


def test_create_true_existing_dir_without_config_seeds_config(
    client, workspace_base: Path
) -> None:
    """An existing empty workspace dir without config gets one seeded."""
    target = workspace_base / "empty_ws"
    target.mkdir()

    resp = client.post(
        "/v1/workspaces", json={"path": "empty_ws", "create": True}
    )
    assert resp.status_code == 200, resp.text
    config_path = target / "config" / "config.yaml"
    assert config_path.is_file()
    text = config_path.read_text(encoding="utf-8")
    assert 'name: "empty_ws"' in text
    assert resp.json()["config_resolved"] is True


def test_create_false_with_existing_dir_works_as_before(
    client, ws1_dir: Path
) -> None:
    """create=false against a pre-existing workspace is unchanged."""
    resp = client.post(
        "/v1/workspaces", json={"path": ws1_dir.name, "create": False}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["exists"] is True
    assert body["config_resolved"] is True


def test_seeded_config_validates_against_schema(
    client, workspace_base: Path
) -> None:
    """The seeded config.yaml is a valid PIKA workspace config."""
    from core.config_loader import load_and_validate_config
    from core.pika_paths import get_config_schema_path

    resp = client.post(
        "/v1/workspaces", json={"path": "schema_ws", "create": True}
    )
    assert resp.status_code == 200, resp.text
    config_path = workspace_base / "schema_ws" / "config" / "config.yaml"
    loaded = load_and_validate_config(config_path, get_config_schema_path())
    # name substitution makes its way into the parsed config.
    assert loaded["project"]["name"] == "schema_ws"


def test_seeded_workspace_appears_in_list_endpoint(
    client, workspace_base: Path
) -> None:
    """A create=true scaffolded workspace shows up in GET /v1/workspaces."""
    created = client.post(
        "/v1/workspaces", json={"path": "listed_ws", "create": True}
    )
    assert created.status_code == 200, created.text
    created_body = created.json()

    listing = client.get("/v1/workspaces")
    assert listing.status_code == 200
    entries = listing.json()
    matched = [e for e in entries if e["id"] == created_body["id"]]
    assert len(matched) == 1
    assert matched[0] == created_body
    assert matched[0]["config_resolved"] is True


def test_seeded_config_yaml_safe_basename_yields_string_name(
    client, workspace_base: Path
) -> None:
    """A YAML-coercion-prone basename (e.g. ``123``) stays a string after seeding.

    Guards against the template losing the quotes around ``{{ name }}``: bare
    numeric or boolean-shaped basenames would otherwise parse as non-string
    scalars and fail schema validation.
    """
    from core.config_loader import load_and_validate_config
    from core.pika_paths import get_config_schema_path

    resp = client.post("/v1/workspaces", json={"path": "123", "create": True})
    assert resp.status_code == 200, resp.text

    config_path = workspace_base / "123" / "config" / "config.yaml"
    loaded = load_and_validate_config(config_path, get_config_schema_path())
    assert loaded["project"]["name"] == "123"
    assert isinstance(loaded["project"]["name"], str)
