"""Phase catalog endpoints."""

from __future__ import annotations


def test_list_phases_includes_format_normalize(client) -> None:
    resp = client.get("/v1/phases")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    names = [entry["name"] for entry in body]
    assert "format.normalize" in names


def test_get_format_normalize_contract_shape(client) -> None:
    resp = client.get("/v1/phases/format.normalize")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "format.normalize"
    assert body["command"] == "format"
    assert body["destructive"] is True
    assert body["can_block"] is False
    input_names = [i["name"] for i in body["inputs"]]
    assert "design_spec_path" in input_names
    output_names = [o["name"] for o in body["outputs"]]
    assert "normalized" in output_names


def test_get_unknown_phase_returns_404(client) -> None:
    resp = client.get("/v1/phases/nope.unknown")
    assert resp.status_code == 404
