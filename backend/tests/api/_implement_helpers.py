"""Helpers shared by M3 implement.unified-planner phase tests."""

from __future__ import annotations

from pathlib import Path

import yaml


_PLANNER_SADS_HEADERS = (
    "spec_id,title,requirement,acceptance_criteria,module_tag,module_role,implementation_status\n"
)
_PLANNER_SADS_ROWS = (
    "S1,Validate,The system shall validate user input.,AC1,core,domain,pending\n"
    "S2,Latency,The system shall respond within 200ms.,AC2,core,domain,pending\n"
)


def enable_implement(ws: Path) -> None:
    cfg_path = ws / "config" / "config.yaml"
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    impl = data["commands"].setdefault("implement", {})
    impl["enabled"] = True
    inputs = impl.setdefault("inputs", {})
    inputs.setdefault("project_context_filename", "PROJECT_CONTEXT.md")
    impl.setdefault("type_placement_path", "shared/types")
    impl.setdefault("forbidden_paths", ["docs/", "specs/"])
    impl.setdefault("budgets", {
        "max_files": 10,
        "max_specs_per_batch": 15,
        "max_lines_changed": 600,
    })
    cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    (ws / "PROJECT_CONTEXT.md").write_text("# test context\n", encoding="utf-8")


def write_planner_inputs(ws: Path) -> tuple[str, str]:
    """Write a planner-ready SADS + codebase tree. Returns (design_spec_rel, codebase_rel)."""
    sads = ws / "specs" / "planner_input.csv"
    sads.parent.mkdir(parents=True, exist_ok=True)
    sads.write_text(_PLANNER_SADS_HEADERS + _PLANNER_SADS_ROWS, encoding="utf-8")
    codebase = ws / "codebase"
    (codebase / "core").mkdir(parents=True, exist_ok=True)
    return "specs/planner_input.csv", "codebase"


def empty_planner_output() -> dict:
    return {
        "module_plans": [{"module_tag": "core", "planned_anchors": []}],
        "spec_dependencies": [],
        "shared_contracts": [],
        "spec_issues": [],
        "manual_resolution_items": [],
    }


def blocking_planner_output() -> dict:
    return {
        "module_plans": [{"module_tag": "core", "planned_anchors": []}],
        "spec_dependencies": [],
        "shared_contracts": [],
        "spec_issues": [],
        "manual_resolution_items": [
            {
                "item_id": "MR-1",
                "kind": "ambiguity",
                "title": "Ambiguous",
                "question": "Which submodule?",
                "options": [
                    {"option_id": "A", "label": "core/auth"},
                    {"option_id": "B", "label": "core/profile"},
                ],
                "blocking_reason": "Ambiguous module",
                "evidence_refs": ["S1"],
                "resolution_mode": "choose",
            }
        ],
    }
