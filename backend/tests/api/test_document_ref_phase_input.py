"""Workflow integration: phase inputs that accept paths also accept document_ref objects."""

from __future__ import annotations

import io
import json
from pathlib import Path


def _register(client, ws1_dir: Path) -> str:
    return client.post("/v1/workspaces", json={"path": ws1_dir.name}).json()["id"]


def _upload_csv(client, wid: str, *, name: str, content: bytes) -> str:
    """Upload a CSV doc and return its file_id."""
    resp = client.post(
        f"/v1/workspaces/{wid}/documents/my",
        files={"file": (name, io.BytesIO(content), "text/csv")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["file_id"]


# Use a valid raw_sads-shaped CSV (format.normalize's input).
_RAW_SADS = (
    b"title,requirement\n"
    b"Login,Users can log in.\n"
    b"Logout,Users can log out.\n"
)


def test_format_normalize_accepts_document_ref(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    fid = _upload_csv(client, wid, name="raw.csv", content=_RAW_SADS)

    resp = client.post(
        "/v1/phases/format.normalize/runs",
        json={
            "workspace_id": wid,
            "inputs": {
                "design_spec_path": {
                    "document_ref": {"category": "my", "file_id": fid}
                }
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    # The resolved path is recorded in inputs (stored as a string).
    resolved = body["inputs"]["design_spec_path"]
    assert isinstance(resolved, str)
    expected = (ws1_dir / "documents" / "my" / "blobs" / f"{fid}.csv").resolve()
    assert Path(resolved).resolve() == expected

    # And the normalize output landed where the existing pipeline expects it.
    out = ws1_dir / "out" / "state" / "DESIGN-SPEC.csv"
    assert out.is_file()


def test_document_ref_unknown_file_id_rejected(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    bogus = "00000000-0000-4000-8000-000000000000"
    resp = client.post(
        "/v1/phases/format.normalize/runs",
        json={
            "workspace_id": wid,
            "inputs": {
                "design_spec_path": {
                    "document_ref": {"category": "my", "file_id": bogus}
                }
            },
        },
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "inputs_invalid"
    joined = " ".join(detail.get("details", {}).get("errors", []))
    assert "not found" in joined.lower()


def test_document_ref_invalid_uuid_rejected(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    resp = client.post(
        "/v1/phases/format.normalize/runs",
        json={
            "workspace_id": wid,
            "inputs": {
                "design_spec_path": {
                    "document_ref": {"category": "my", "file_id": "not-a-uuid"}
                }
            },
        },
    )
    assert resp.status_code == 422


def test_document_ref_invalid_category_rejected(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    fid = _upload_csv(client, wid, name="raw.csv", content=_RAW_SADS)
    resp = client.post(
        "/v1/phases/format.normalize/runs",
        json={
            "workspace_id": wid,
            "inputs": {
                "design_spec_path": {
                    "document_ref": {"category": "bad..cat", "file_id": fid}
                }
            },
        },
    )
    assert resp.status_code == 422


def test_string_path_input_still_works(client, ws1_dir: Path) -> None:
    """Backwards-compat: existing string-path inputs are unchanged."""
    wid = _register(client, ws1_dir)
    resp = client.post(
        "/v1/phases/format.normalize/runs",
        json={
            "workspace_id": wid,
            "inputs": {"design_spec_path": "specs/raw_sads.csv"},
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "completed"


def test_document_ref_object_missing_document_ref_key_rejected(
    client, ws1_dir: Path
) -> None:
    wid = _register(client, ws1_dir)
    resp = client.post(
        "/v1/phases/format.normalize/runs",
        json={
            "workspace_id": wid,
            "inputs": {"design_spec_path": {"category": "my", "file_id": "x"}},
        },
    )
    assert resp.status_code == 422


def test_document_ref_inner_extra_keys_rejected(client, ws1_dir: Path) -> None:
    """Inner document_ref must not accept extra keys beyond {category, file_id}."""
    wid = _register(client, ws1_dir)
    fid = _upload_csv(client, wid, name="raw.csv", content=_RAW_SADS)
    resp = client.post(
        "/v1/phases/format.normalize/runs",
        json={
            "workspace_id": wid,
            "inputs": {
                "design_spec_path": {
                    "document_ref": {
                        "category": "my",
                        "file_id": fid,
                        "version": 1,
                    }
                }
            },
        },
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "inputs_invalid"


def test_document_ref_blob_missing_on_disk(client, ws1_dir: Path) -> None:
    """Manifest entry exists but the blob has been deleted out-of-band -> 422."""
    wid = _register(client, ws1_dir)
    fid = _upload_csv(client, wid, name="raw.csv", content=_RAW_SADS)
    blob = ws1_dir / "documents" / "my" / "blobs" / f"{fid}.csv"
    assert blob.is_file()
    blob.unlink()

    resp = client.post(
        "/v1/phases/format.normalize/runs",
        json={
            "workspace_id": wid,
            "inputs": {
                "design_spec_path": {
                    "document_ref": {"category": "my", "file_id": fid}
                }
            },
        },
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "inputs_invalid"
    joined = " ".join(detail.get("details", {}).get("errors", []))
    assert "missing" in joined.lower()


def test_document_ref_with_extra_keys_rejected(client, ws1_dir: Path) -> None:
    wid = _register(client, ws1_dir)
    fid = _upload_csv(client, wid, name="raw.csv", content=_RAW_SADS)
    resp = client.post(
        "/v1/phases/format.normalize/runs",
        json={
            "workspace_id": wid,
            "inputs": {
                "design_spec_path": {
                    "document_ref": {"category": "my", "file_id": fid},
                    "extra": "nope",
                }
            },
        },
    )
    assert resp.status_code == 422
