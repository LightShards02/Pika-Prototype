"""Catalog lists refine phases after app startup; both have async_execution=True."""

from __future__ import annotations


def test_phase_catalog_lists_refine_phases(client) -> None:
    resp = client.get("/v1/phases")
    assert resp.status_code == 200
    names = {item["name"] for item in resp.json()}
    assert "format.normalize" in names
    assert "refine.decomposition-check" in names
    assert "refine.quality-audit" in names


def test_refine_contracts_are_async(client) -> None:
    resp = client.get("/v1/phases/refine.decomposition-check")
    assert resp.status_code == 200
    assert resp.json()["async_execution"] is True

    resp = client.get("/v1/phases/refine.quality-audit")
    assert resp.status_code == 200
    assert resp.json()["async_execution"] is True


def test_format_normalize_contract_is_sync(client) -> None:
    resp = client.get("/v1/phases/format.normalize")
    assert resp.status_code == 200
    assert resp.json()["async_execution"] is False
