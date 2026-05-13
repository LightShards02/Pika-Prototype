"""Catalog lists implement.unified-planner phase after app startup."""

from __future__ import annotations


def test_phase_catalog_lists_implement_unified_planner(client) -> None:
    resp = client.get("/v1/phases")
    assert resp.status_code == 200
    names = {item["name"] for item in resp.json()}
    assert "implement.unified-planner" in names


def test_implement_unified_planner_contract_is_async(client) -> None:
    resp = client.get("/v1/phases/implement.unified-planner")
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
        "prior_planner_run_id",
    ]
    by_name = {i["name"]: i for i in body["inputs"]}
    assert by_name["prior_planner_run_id"]["kind"] == "phase_run_ref"
    assert by_name["prior_planner_run_id"]["ref_phase"] == "implement.unified-planner"
    output_names = {o["name"] for o in body["outputs"]}
    assert {"unified_plan", "spec_issues"} <= output_names
    assert body["recommended_prerequisites"] == ["refine.quality-audit"]
