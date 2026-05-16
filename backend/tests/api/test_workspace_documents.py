"""REST endpoints for workspace documents (id-addressed, manifest-backed)."""

from __future__ import annotations

import io
import json
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


_UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def _register(client, ws1_dir: Path) -> str:
    resp = client.post("/v1/workspaces", json={"path": ws1_dir.name})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _upload(
    client,
    wid: str,
    category: str,
    *,
    filename: str = "notes.md",
    content: bytes | str = b"# hi\n",
    display_name: str | None = None,
    content_type: str = "text/markdown",
):
    if isinstance(content, str):
        content = content.encode("utf-8")
    data = {}
    if display_name is not None:
        data["display_name"] = display_name
    return client.post(
        f"/v1/workspaces/{wid}/documents/{category}",
        files={"file": (filename, io.BytesIO(content), content_type)},
        data=data,
    )


# ---------- POST (upload) ----------


def test_post_creates_document_and_returns_entry(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    resp = _upload(client, wid, "my", filename="notes.md", content="# hello\n")
    assert resp.status_code == 201, resp.text
    entry = resp.json()
    assert _UUID4_RE.match(entry["file_id"])
    assert entry["display_name"] == "notes.md"
    assert entry["extension"] == ".md"
    assert entry["size"] == len(b"# hello\n")
    assert entry["content_type"] == "text/markdown; charset=utf-8"
    assert entry["sha256"]
    assert entry["created_at"] == entry["updated_at"]
    # On-disk layout: blob filename = <file_id><extension>
    fid = entry["file_id"]
    assert (
        ws1_dir / "documents" / "my" / "blobs" / f"{fid}.md"
    ).read_bytes() == b"# hello\n"
    manifest = json.loads(
        (ws1_dir / "documents" / "my" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["version"] == 1
    assert fid in manifest["documents"]
    assert manifest["documents"][fid]["display_name"] == "notes.md"


def test_post_uses_explicit_display_name_over_filename(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    resp = _upload(
        client,
        wid,
        "my",
        filename="upload.tmp.md",
        display_name="design-spec.md",
        content="x",
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["display_name"] == "design-spec.md"


def test_post_rejects_disallowed_extension(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    resp = _upload(client, wid, "my", filename="evil.exe", content="x")
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "document_invalid_display_name"


def test_post_rejects_oversized_body(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    resp = _upload(
        client, wid, "my", filename="big.txt", content=b"a" * (1024 * 1024 + 1)
    )
    assert resp.status_code == 413, resp.text
    assert resp.json()["detail"]["code"] == "document_too_large"


def test_post_rejects_non_utf8(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    resp = _upload(
        client, wid, "my", filename="b.txt", content=b"\xff\xfebad"
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "document_body_not_utf8"


def test_post_creates_parent_directory_lazily(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    assert not (ws1_dir / "documents").exists()
    resp = _upload(client, wid, "my", filename="x.md", content="x")
    assert resp.status_code == 201
    assert (ws1_dir / "documents" / "my" / "manifest.json").is_file()
    assert (ws1_dir / "documents" / "my" / "blobs").is_dir()


# ---------- GET list / content / meta ----------


def test_list_empty_when_dir_missing(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    resp = client.get(f"/v1/workspaces/{wid}/documents/my")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_returns_sorted_entries(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    _upload(client, wid, "my", filename="b.md", content="b")
    _upload(client, wid, "my", filename="a.md", content="aa")
    _upload(client, wid, "my", filename="c.md", content="ccc")
    body = client.get(f"/v1/workspaces/{wid}/documents/my").json()
    assert [e["display_name"] for e in body] == ["a.md", "b.md", "c.md"]
    for e in body:
        assert _UUID4_RE.match(e["file_id"])


def test_list_supports_duplicate_display_names(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    r1 = _upload(client, wid, "my", filename="notes.md", content="one")
    r2 = _upload(client, wid, "my", filename="notes.md", content="two")
    ids = {r1.json()["file_id"], r2.json()["file_id"]}
    assert len(ids) == 2
    body = client.get(f"/v1/workspaces/{wid}/documents/my").json()
    assert [e["display_name"] for e in body] == ["notes.md", "notes.md"]
    assert {e["file_id"] for e in body} == ids


def test_get_content_returns_bytes_and_correct_content_type(
    client, ws1_dir: Path
) -> None:
    wid = _register(client, ws1_dir)
    fid = _upload(client, wid, "my", filename="data.json", content='{"k":1}').json()[
        "file_id"
    ]
    resp = client.get(f"/v1/workspaces/{wid}/documents/my/{fid}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.headers["x-document-id"] == fid
    assert resp.headers["x-document-display-name"] == "data.json"
    assert resp.json() == {"k": 1}


def test_get_meta_returns_entry_only(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    fid = _upload(client, wid, "my", filename="notes.md", content="x").json()[
        "file_id"
    ]
    resp = client.get(f"/v1/workspaces/{wid}/documents/my/{fid}/meta")
    assert resp.status_code == 200
    assert resp.json()["file_id"] == fid


def test_get_content_missing_returns_404(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    bogus = str(uuid.uuid4())
    resp = client.get(f"/v1/workspaces/{wid}/documents/my/{bogus}")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "document_not_found"


def test_get_meta_missing_returns_404(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    bogus = str(uuid.uuid4())
    resp = client.get(f"/v1/workspaces/{wid}/documents/my/{bogus}/meta")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "document_not_found"


def test_get_content_invalid_file_id_400(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    resp = client.get(f"/v1/workspaces/{wid}/documents/my/not-a-uuid")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "document_invalid_file_id"


# ---------- PUT (replace content) ----------


def test_put_replaces_content(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    fid = _upload(client, wid, "my", filename="notes.md", content="v1").json()[
        "file_id"
    ]
    resp = client.put(
        f"/v1/workspaces/{wid}/documents/my/{fid}",
        files={"file": ("notes.md", io.BytesIO(b"v2-longer"), "text/markdown")},
    )
    assert resp.status_code == 200, resp.text
    entry = resp.json()
    assert entry["size"] == len(b"v2-longer")
    assert entry["display_name"] == "notes.md"
    assert entry["updated_at"] >= entry["created_at"]
    body = client.get(f"/v1/workspaces/{wid}/documents/my/{fid}").content
    assert body == b"v2-longer"


def test_put_can_rename_during_replace(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    fid = _upload(client, wid, "my", filename="old.md", content="x").json()[
        "file_id"
    ]
    resp = client.put(
        f"/v1/workspaces/{wid}/documents/my/{fid}",
        files={"file": ("ignored.md", io.BytesIO(b"new"), "text/markdown")},
        data={"display_name": "new.md"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["display_name"] == "new.md"


def test_put_rejects_extension_change(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    fid = _upload(client, wid, "my", filename="notes.md", content="x").json()[
        "file_id"
    ]
    resp = client.put(
        f"/v1/workspaces/{wid}/documents/my/{fid}",
        files={"file": ("notes.md", io.BytesIO(b"y"), "text/plain")},
        data={"display_name": "notes.txt"},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "document_invalid_input"


def test_put_missing_document_404(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    fid = str(uuid.uuid4())
    resp = client.put(
        f"/v1/workspaces/{wid}/documents/my/{fid}",
        files={"file": ("notes.md", io.BytesIO(b"x"), "text/markdown")},
    )
    assert resp.status_code == 404


# ---------- PATCH (rename) ----------


def test_patch_renames_document(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    fid = _upload(client, wid, "my", filename="old.md", content="x").json()[
        "file_id"
    ]
    resp = client.patch(
        f"/v1/workspaces/{wid}/documents/my/{fid}",
        json={"display_name": "renamed.md"},
    )
    assert resp.status_code == 200, resp.text
    entry = resp.json()
    assert entry["display_name"] == "renamed.md"
    # Content unchanged.
    assert client.get(f"/v1/workspaces/{wid}/documents/my/{fid}").content == b"x"


def test_patch_rejects_extension_change(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    fid = _upload(client, wid, "my", filename="old.md", content="x").json()[
        "file_id"
    ]
    resp = client.patch(
        f"/v1/workspaces/{wid}/documents/my/{fid}",
        json={"display_name": "old.txt"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "document_invalid_input"


def test_patch_missing_document_404(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    fid = str(uuid.uuid4())
    resp = client.patch(
        f"/v1/workspaces/{wid}/documents/my/{fid}",
        json={"display_name": "x.md"},
    )
    assert resp.status_code == 404


# ---------- DELETE ----------


def test_delete_removes_document_and_blob(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    fid = _upload(client, wid, "my", filename="notes.md", content="x").json()[
        "file_id"
    ]
    blob = ws1_dir / "documents" / "my" / "blobs" / f"{fid}.md"
    assert blob.is_file()

    resp = client.delete(f"/v1/workspaces/{wid}/documents/my/{fid}")
    assert resp.status_code == 204
    assert not blob.exists()
    assert client.get(f"/v1/workspaces/{wid}/documents/my/{fid}").status_code == 404


def test_delete_missing_document_404(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    resp = client.delete(
        f"/v1/workspaces/{wid}/documents/my/{uuid.uuid4()}"
    )
    assert resp.status_code == 404


# ---------- category validation ----------


def test_invalid_category_400(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    resp = client.get(f"/v1/workspaces/{wid}/documents/bad.cat")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "document_invalid_category"


def test_unknown_workspace_404_on_all_routes(client) -> None:
    wid = "aaaaaaaaaaaa"
    fid = str(uuid.uuid4())
    assert client.get(f"/v1/workspaces/{wid}/documents/my").status_code == 404
    assert client.get(f"/v1/workspaces/{wid}/documents/my/{fid}").status_code == 404
    assert (
        client.get(f"/v1/workspaces/{wid}/documents/my/{fid}/meta").status_code == 404
    )
    assert (
        client.post(
            f"/v1/workspaces/{wid}/documents/my",
            files={"file": ("x.md", io.BytesIO(b"x"), "text/markdown")},
        ).status_code
        == 404
    )
    assert client.delete(f"/v1/workspaces/{wid}/documents/my/{fid}").status_code == 404


# ---------- symlink escape (platform-aware) ----------


def _can_symlink_dir(tmp: Path) -> bool:
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
    if not _can_symlink_dir(tmp_path):
        pytest.skip("directory symlinks not permitted in this environment")
    wid = _register(client, ws1_dir)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("not yours", encoding="utf-8")
    docs_root = ws1_dir / "documents"
    docs_root.mkdir(parents=True, exist_ok=True)
    os.symlink(outside, docs_root / "escape", target_is_directory=True)
    resp = client.get(f"/v1/workspaces/{wid}/documents/escape")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "document_path_outside_workspace"


# ---------- concurrency ----------


def test_concurrent_uploads_each_get_unique_file_id(
    client, ws1_dir: Path
) -> None:
    wid = _register(client, ws1_dir)
    names = [f"d{i}.md" for i in range(8)]

    def upload(name: str) -> str:
        r = _upload(client, wid, "my", filename=name, content=name)
        assert r.status_code == 201, r.text
        return r.json()["file_id"]

    with ThreadPoolExecutor(max_workers=8) as ex:
        ids = list(ex.map(upload, names))
    assert len(set(ids)) == 8

    listed = client.get(f"/v1/workspaces/{wid}/documents/my").json()
    assert {e["file_id"] for e in listed} == set(ids)
    # No stray .tmp files leaked into the blobs dir or the manifest dir.
    blobs = list((ws1_dir / "documents" / "my" / "blobs").iterdir())
    assert all(not p.name.endswith(".tmp") for p in blobs)
    manifest_dir = ws1_dir / "documents" / "my"
    assert not any(
        p.name.endswith(".tmp") and p.is_file() for p in manifest_dir.iterdir()
    )
