"""REST endpoints for workspace memory: per-file GET/PUT + bundle GET + bootstrap idempotency."""

from __future__ import annotations

from pathlib import Path


def _register(client, ws1_dir: Path) -> str:
    resp = client.post("/v1/workspaces", json={"path": str(ws1_dir)})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_register_workspace_bootstraps_memory_files(client, ws1_dir: Path) -> None:
    _register(client, ws1_dir)
    mdir = ws1_dir / "out" / "state" / "memory"
    assert mdir.is_dir()
    for name in ("memory", "lessons", "tasks", "gaps"):
        path = mdir / f"{name}.md"
        assert path.is_file()
        assert path.read_text(encoding="utf-8").startswith("# ")


def test_bundle_returns_all_four_keys_after_bootstrap(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    resp = client.get(f"/v1/workspaces/{wid}/memory")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"memory", "lessons", "tasks", "gaps"}
    for v in body.values():
        assert v.startswith("# ")


def test_get_memory_file_returns_text_plain(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    resp = client.get(f"/v1/workspaces/{wid}/memory/lessons")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert resp.text.startswith("# Lessons")


def test_put_memory_file_replaces_and_persists(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    new_text = "# Lessons\n\n- always validate inputs\n"
    resp = client.put(
        f"/v1/workspaces/{wid}/memory/lessons",
        content=new_text,
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    assert resp.status_code == 200
    assert resp.text == new_text
    bundle = client.get(f"/v1/workspaces/{wid}/memory").json()
    assert bundle["lessons"] == new_text


def test_get_memory_file_unknown_name_returns_404(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    resp = client.get(f"/v1/workspaces/{wid}/memory/bogus")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "unknown_memory_file"


def test_put_memory_file_unknown_name_returns_404(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    resp = client.put(
        f"/v1/workspaces/{wid}/memory/bogus",
        content="x",
        headers={"Content-Type": "text/plain"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "unknown_memory_file"


def test_memory_endpoints_404_for_unknown_workspace(client) -> None:
    resp = client.get("/v1/workspaces/aaaaaaaaaaaa/memory")
    assert resp.status_code == 404
    resp2 = client.get("/v1/workspaces/aaaaaaaaaaaa/memory/lessons")
    assert resp2.status_code == 404


def test_bootstrap_idempotent_preserves_user_writes(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    payload = "# Lessons\n\n- preserved across re-register\n"
    put_resp = client.put(
        f"/v1/workspaces/{wid}/memory/lessons",
        content=payload,
        headers={"Content-Type": "text/plain"},
    )
    assert put_resp.status_code == 200
    # Re-register the same workspace.
    again = client.post("/v1/workspaces", json={"path": str(ws1_dir)})
    assert again.status_code == 200
    bundle = client.get(f"/v1/workspaces/{wid}/memory").json()
    assert bundle["lessons"] == payload


def test_put_memory_rejects_non_utf8_body(client, ws1_dir: Path) -> None:
    """PUT /memory/{file} with invalid UTF-8 bytes returns 400 memory_body_not_utf8."""
    wid = _register(client, ws1_dir)
    invalid = b"\xff\xfe\xfd not utf-8"
    resp = client.put(
        f"/v1/workspaces/{wid}/memory/lessons",
        content=invalid,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "memory_body_not_utf8"


def test_bundle_returns_empty_strings_for_missing_files(client, ws1_dir: Path) -> None:
    """If a memory file is deleted post-bootstrap, the bundle still returns all four
    keys with empty string for the missing one."""
    wid = _register(client, ws1_dir)
    # Delete one of the bootstrapped files directly on disk.
    (ws1_dir / "out" / "state" / "memory" / "tasks.md").unlink()
    bundle = client.get(f"/v1/workspaces/{wid}/memory").json()
    assert set(bundle.keys()) == {"memory", "lessons", "tasks", "gaps"}
    assert bundle["tasks"] == ""
