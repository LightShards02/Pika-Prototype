"""REST endpoints for workspace documents: CRUD over <ws>/documents/<category>/<name>."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


def _register(client, ws1_dir: Path) -> str:
    resp = client.post("/v1/workspaces", json={"path": str(ws1_dir)})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _put(client, wid: str, category: str, name: str, body: str | bytes):
    return client.put(
        f"/v1/workspaces/{wid}/documents/{category}/{name}",
        content=body,
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )


# ---------- happy path / round-trip ----------


def test_put_then_get_round_trips(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    text = "# Notes\n\nhello world\n"
    resp = _put(client, wid, "my", "notes.md", text)
    assert resp.status_code == 200, resp.text
    assert resp.text == text
    assert resp.headers["content-type"].startswith("text/plain")

    got = client.get(f"/v1/workspaces/{wid}/documents/my/notes.md")
    assert got.status_code == 200
    assert got.text == text
    assert got.headers["content-type"].startswith("text/plain")
    assert (ws1_dir / "documents" / "my" / "notes.md").read_text(encoding="utf-8") == text


def test_put_json_returns_application_json_on_get(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    body = json.dumps({"k": 1})
    resp = _put(client, wid, "my", "data.json", body)
    assert resp.status_code == 200, resp.text

    got = client.get(f"/v1/workspaces/{wid}/documents/my/data.json")
    assert got.status_code == 200
    assert got.headers["content-type"].startswith("application/json")
    assert got.json() == {"k": 1}


def test_list_returns_empty_when_dir_missing(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    resp = client.get(f"/v1/workspaces/{wid}/documents/my")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_returns_entries_sorted_by_name(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    _put(client, wid, "my", "b.md", "b")
    _put(client, wid, "my", "a.md", "a")
    _put(client, wid, "my", "c.md", "ccc")

    resp = client.get(f"/v1/workspaces/{wid}/documents/my")
    assert resp.status_code == 200
    body = resp.json()
    assert [e["name"] for e in body] == ["a.md", "b.md", "c.md"]
    sizes = {e["name"]: e["size"] for e in body}
    assert sizes == {"a.md": 1, "b.md": 1, "c.md": 3}
    for e in body:
        assert isinstance(e["mtime"], (int, float))


def test_list_skips_disallowed_extensions(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    _put(client, wid, "my", "ok.md", "ok")
    # Drop a stray .exe by hand to simulate a user-touched directory.
    (ws1_dir / "documents" / "my" / "stray.exe").write_bytes(b"x")
    body = client.get(f"/v1/workspaces/{wid}/documents/my").json()
    assert [e["name"] for e in body] == ["ok.md"]


def test_delete_removes_document(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    _put(client, wid, "my", "notes.md", "hi")
    assert (ws1_dir / "documents" / "my" / "notes.md").is_file()

    resp = client.delete(f"/v1/workspaces/{wid}/documents/my/notes.md")
    assert resp.status_code == 204
    assert not (ws1_dir / "documents" / "my" / "notes.md").exists()

    got = client.get(f"/v1/workspaces/{wid}/documents/my/notes.md")
    assert got.status_code == 404
    assert got.json()["detail"]["code"] == "document_not_found"


def test_put_creates_parent_directory_lazily(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    assert not (ws1_dir / "documents").exists()
    resp = _put(client, wid, "my", "first.md", "x")
    assert resp.status_code == 200, resp.text
    assert (ws1_dir / "documents" / "my").is_dir()


def test_put_supports_alternate_category(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    resp = _put(client, wid, "shared", "ref.md", "ref")
    assert resp.status_code == 200, resp.text
    assert (ws1_dir / "documents" / "shared" / "ref.md").read_text() == "ref"
    body = client.get(f"/v1/workspaces/{wid}/documents/shared").json()
    assert [e["name"] for e in body] == ["ref.md"]
    # And listing under "my" remains empty (categories isolated).
    assert client.get(f"/v1/workspaces/{wid}/documents/my").json() == []


# ---------- validation ----------


def test_invalid_category_400(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    # A dot in the category segment fails the regex.
    resp = client.get(f"/v1/workspaces/{wid}/documents/bad.cat")
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "document_invalid_category"


def test_invalid_name_extension_400(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    resp = _put(client, wid, "my", "evil.exe", "x")
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "document_invalid_name"


def test_invalid_name_no_extension_400(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    resp = _put(client, wid, "my", "noext", "x")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "document_invalid_name"


def test_invalid_name_starts_with_dot_400(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    resp = _put(client, wid, "my", ".hidden.md", "x")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "document_invalid_name"


def test_put_blocks_path_traversal(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    # URL-encoded dot-dot segments. The route matcher / regex should reject
    # this before it ever touches the filesystem.
    resp = client.put(
        f"/v1/workspaces/{wid}/documents/%2E%2E/%2E%2E.md",
        content=b"pwned",
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    assert resp.status_code == 400, resp.text
    code = resp.json()["detail"]["code"]
    assert code in {
        "document_invalid_category",
        "document_invalid_name",
        "document_path_outside_workspace",
    }
    # And the file we'd target by traversal must not exist.
    assert not (ws1_dir.parent / "pwned.md").exists()


def test_get_blocks_path_traversal_in_name(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    # %2F decodes to "/" which Starlette uses as a path separator; the route
    # simply does not match and returns 404. Either a 404 (no route match) or
    # a 400 with a document_* code is acceptable evidence the traversal cannot
    # land. What we forbid is a 200 response or any file written outside the
    # workspace.
    resp = client.get(f"/v1/workspaces/{wid}/documents/my/%2E%2E%2Fescape.md")
    assert resp.status_code in {400, 404}
    if resp.status_code == 400:
        assert resp.json()["detail"]["code"] in {
            "document_invalid_name",
            "document_path_outside_workspace",
        }


def test_put_body_too_large_413(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    blob = b"a" * (1024 * 1024 + 1)
    resp = client.put(
        f"/v1/workspaces/{wid}/documents/my/big.txt",
        content=blob,
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    assert resp.status_code == 413, resp.text
    body = resp.json()["detail"]
    assert body["code"] == "document_too_large"
    assert body["details"]["limit_bytes"] == 1024 * 1024


def test_put_body_at_size_cap_succeeds(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    blob = b"a" * (1024 * 1024)
    resp = client.put(
        f"/v1/workspaces/{wid}/documents/my/edge.txt",
        content=blob,
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    assert resp.status_code == 200, resp.text


def test_put_body_not_utf8_400(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    resp = client.put(
        f"/v1/workspaces/{wid}/documents/my/binary.txt",
        content=b"\xff\xfe\x00bad",
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "document_body_not_utf8"


# ---------- existence / workspace ----------


def test_get_missing_document_404(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    resp = client.get(f"/v1/workspaces/{wid}/documents/my/none.md")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "document_not_found"


def test_delete_missing_document_404(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    resp = client.delete(f"/v1/workspaces/{wid}/documents/my/none.md")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "document_not_found"


def test_unknown_workspace_404_on_all_routes(client) -> None:
    bogus = "aaaaaaaaaaaa"
    assert client.get(f"/v1/workspaces/{bogus}/documents/my").status_code == 404
    assert client.get(f"/v1/workspaces/{bogus}/documents/my/x.md").status_code == 404
    assert (
        client.put(
            f"/v1/workspaces/{bogus}/documents/my/x.md",
            content=b"x",
            headers={"Content-Type": "text/plain; charset=utf-8"},
        ).status_code
        == 404
    )
    assert client.delete(f"/v1/workspaces/{bogus}/documents/my/x.md").status_code == 404


# ---------- directory target ----------


def _can_symlink_dir(tmp: Path) -> bool:
    """True if this process can create directory symlinks. False on Windows w/o privilege."""
    src = tmp / "_src"
    dst = tmp / "_dst"
    src.mkdir()
    try:
        os.symlink(src, dst, target_is_directory=True)
    except (OSError, NotImplementedError):
        return False
    finally:
        try:
            if dst.is_symlink() or dst.exists():
                dst.unlink()
        except OSError:
            pass
        try:
            src.rmdir()
        except OSError:
            pass
    return True


def test_list_blocks_symlinked_category_escape(
    client, ws1_dir: Path, tmp_path: Path
) -> None:
    """A category dir that symlinks outside the workspace must surface as 400."""
    if not _can_symlink_dir(tmp_path):
        pytest.skip("directory symlinks not permitted in this environment")
    wid = _register(client, ws1_dir)
    outside = tmp_path / "outside_target"
    outside.mkdir()
    (outside / "secret.md").write_text("not yours", encoding="utf-8")
    docs_root = ws1_dir / "documents"
    docs_root.mkdir(parents=True, exist_ok=True)
    link = docs_root / "escape"
    os.symlink(outside, link, target_is_directory=True)

    resp = client.get(f"/v1/workspaces/{wid}/documents/escape")
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "document_path_outside_workspace"


def test_get_on_directory_target_returns_400(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    # Land a directory at <ws>/documents/my/dir.md so the route + name regex
    # accept it but the filesystem entry is a directory.
    bad = ws1_dir / "documents" / "my" / "dir.md"
    bad.mkdir(parents=True)
    resp = client.get(f"/v1/workspaces/{wid}/documents/my/dir.md")
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "document_path_not_file"


# ---------- concurrency smoke ----------


def test_concurrent_puts_do_not_corrupt(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    payloads = [("a" * 500) + f"\n#{i}\n" for i in range(8)]

    def write(payload: str) -> int:
        r = client.put(
            f"/v1/workspaces/{wid}/documents/my/race.md",
            content=payload,
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )
        return r.status_code

    with ThreadPoolExecutor(max_workers=8) as ex:
        codes = list(ex.map(write, payloads))
    assert all(c == 200 for c in codes), codes

    final = (ws1_dir / "documents" / "my" / "race.md").read_text(encoding="utf-8")
    assert final in payloads


def test_concurrent_puts_to_different_names_same_extension(
    client, ws1_dir: Path
) -> None:
    """Cross-document writes in the same category must not collide on temp files."""
    wid = _register(client, ws1_dir)
    names = [f"doc{i}.md" for i in range(8)]
    payloads = {n: f"# {n}\n" + ("x" * 200) for n in names}

    def write(name: str) -> int:
        r = client.put(
            f"/v1/workspaces/{wid}/documents/my/{name}",
            content=payloads[name],
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )
        return r.status_code

    with ThreadPoolExecutor(max_workers=8) as ex:
        codes = list(ex.map(write, names))
    assert all(c == 200 for c in codes), codes

    for name in names:
        on_disk = (ws1_dir / "documents" / "my" / name).read_text(encoding="utf-8")
        assert on_disk == payloads[name], f"{name} got mangled"

    # And no stray temp files were left in the directory.
    leftover_tmp = [
        p.name for p in (ws1_dir / "documents" / "my").iterdir() if p.suffix == ".tmp"
    ]
    assert leftover_tmp == []
