"""Catalog lists map.match phase after app startup."""

from __future__ import annotations


def test_phase_catalog_lists_map_match(client) -> None:
    resp = client.get("/v1/phases")
    assert resp.status_code == 200
    names = {item["name"] for item in resp.json()}
    assert "map.match" in names


def test_map_match_contract_is_async(client) -> None:
    resp = client.get("/v1/phases/map.match")
    assert resp.status_code == 200
    body = resp.json()
    assert body["async_execution"] is True
    assert body["can_block"] is True
    assert body["destructive"] is False
    input_names = [i["name"] for i in body["inputs"]]
    assert input_names == [
        "design_spec_path",
        "codebase_dir",
        "project_context_path",
        "extra_prompt_path",
        "force_remap",
        "max_acceptance_chars",
        "prior_match_run_id",
    ]
    by_name = {i["name"]: i for i in body["inputs"]}
    assert by_name["design_spec_path"]["required"] is True
    assert by_name["codebase_dir"]["required"] is True
    assert by_name["prior_match_run_id"]["kind"] == "phase_run_ref"
    assert by_name["prior_match_run_id"]["ref_phase"] == "map.match"
    assert by_name["force_remap"]["kind"] == "bool"
    assert by_name["max_acceptance_chars"]["kind"] == "int"
    output_names = {o["name"] for o in body["outputs"]}
    assert {"map_output", "subunit_outputs"} <= output_names
    assert body["recommended_prerequisites"] == ["refine.quality-audit"]
