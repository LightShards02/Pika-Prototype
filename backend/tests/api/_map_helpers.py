"""Helpers shared by M4 map.match phase tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


_MAP_SADS_HEADERS = (
    "spec_id,title,requirement,acceptance_criteria,subunit,map_status\n"
)
_MAP_SADS_ROWS = (
    "A1,Validate,The system shall validate user input.,AC1,auth,\n"
    "A2,Latency,The system shall respond within 200ms.,AC2,auth,\n"
    "B1,Persist,The system shall persist users.,AC3,profile,\n"
)


def enable_map(ws: Path) -> None:
    cfg_path = ws / "config" / "config.yaml"
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    map_cfg = data["commands"].setdefault("map", {})
    map_cfg["enabled"] = True
    map_cfg.setdefault("skip_mapped", True)
    map_cfg.setdefault("max_acceptance_chars", 0)
    map_cfg.setdefault("min_remapping_confidence_threshold", 0.0)
    map_cfg.setdefault("max_problem_threshold", 1.0)
    inputs = map_cfg.setdefault("inputs", {})
    inputs.setdefault("project_context_filename", "PROJECT_CONTEXT.md")
    outputs = map_cfg.setdefault("outputs", {})
    outputs.setdefault("backups_dir", {"path": "out/backups", "no_overwrite": False})
    outputs.setdefault("agent_runs_dir", {"path": "out/agent_runs", "no_overwrite": False})
    cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    (ws / "PROJECT_CONTEXT.md").write_text("# test context\n", encoding="utf-8")
    codebase = ws / "codebase"
    codebase.mkdir(parents=True, exist_ok=True)
    (codebase / "auth.py").write_text("# stub\n", encoding="utf-8")


def write_map_inputs(ws: Path) -> tuple[str, str]:
    """Write a map-ready SADS + codebase. Returns (design_spec_rel, codebase_rel)."""
    sads = ws / "specs" / "map_input.csv"
    sads.parent.mkdir(parents=True, exist_ok=True)
    sads.write_text(_MAP_SADS_HEADERS + _MAP_SADS_ROWS, encoding="utf-8")
    return "specs/map_input.csv", "codebase"


def clean_mapper_output_for_subunit(template_vars: dict[str, Any]) -> dict[str, Any]:
    """Return a clean mapper output keyed off which subunit the prompt CSV came from."""
    csv = template_vars.get("design_spec_rows_csv", "")
    if "B1" in csv:
        return _clean_for(["B1"])
    return _clean_for(["A1", "A2"])


def _clean_for(spec_ids: list[str]) -> dict[str, Any]:
    return {
        "manual_resolution_items": [],
        "run_summary": {
            "command": "agent map",
            "status": "success",
            "summary": "",
            "blocking_items": 0,
            "storage_file": "",
        },
        "created_at": "2026-01-01T00:00:00",
        "mappings": [
            {
                "spec_id": sid,
                "status": "mapped",
                "code_refs": [
                    {
                        "path": "auth.py",
                        "symbol_name": f"handle_{sid}",
                        "symbol_type": "function",
                        "confidence": 0.9,
                        "consistency_score": 0.9,
                        "problems": "",
                    }
                ],
                "assumptions": None,
            }
            for sid in spec_ids
        ],
    }


def blocking_mapper_output() -> dict[str, Any]:
    return {
        "manual_resolution_items": [
            {
                "item_id": "MR-1",
                "kind": "ambiguity",
                "entity_id": "A1",
                "title": "Ambiguous mapping",
                "question": "Which symbol matches?",
                "options": [
                    {"option_id": "A", "label": "auth.handle_login"},
                    {"option_id": "B", "label": "auth.signin"},
                ],
                "blocking_reason": "Ambiguous code reference",
                "evidence_refs": ["A1"],
                "resolution_mode": "choose",
            }
        ],
        "run_summary": {
            "command": "agent map",
            "status": "blocked",
            "summary": "1 manual item",
            "blocking_items": 1,
            "storage_file": "",
        },
        "created_at": "2026-01-01T00:00:00",
        "mappings": [],
    }
