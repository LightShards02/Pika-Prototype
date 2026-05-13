"""Shared fixtures for backend/tests/implement_planner_phase/."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


_HEADERS = [
    "spec_id",
    "title",
    "requirement",
    "acceptance_criteria",
    "module_tag",
    "module_role",
    "implementation_status",
]

_ROWS = [
    {
        "spec_id": "S1",
        "title": "Validate user input",
        "requirement": "The system shall validate user input.",
        "acceptance_criteria": "AC1",
        "module_tag": "core",
        "module_role": "domain",
        "implementation_status": "pending",
    },
    {
        "spec_id": "S2",
        "title": "Return quickly",
        "requirement": "The system shall return results within 200ms.",
        "acceptance_criteria": "AC2",
        "module_tag": "core",
        "module_role": "domain",
        "implementation_status": "pending",
    },
]


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [",".join(headers)]
    for row in rows:
        lines.append(",".join(row.get(h, "") for h in headers))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture()
def workspace_root(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    (root / "PROJECT_CONTEXT.md").write_text("# test ctx\n", encoding="utf-8")
    (root / "codebase").mkdir(parents=True, exist_ok=True)
    (root / "codebase" / "core").mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture()
def design_csv(workspace_root: Path) -> Path:
    path = workspace_root / "DESIGN-SPEC.csv"
    _write_csv(path, _HEADERS, _ROWS)
    return path


@pytest.fixture()
def codebase_dir(workspace_root: Path) -> Path:
    return workspace_root / "codebase"


def make_config(workspace: Path) -> dict[str, Any]:
    return {
        "agent": {"provider": "stub", "schema_validation_retries": 0},
        "project": {"name": "test", "root_dir": str(workspace)},
        "commands": {
            "implement": {
                "enabled": True,
                "type_placement_path": "shared/types",
                "allowed_module_roles": ["frontend", "api", "domain", "infra", "shared", "cli", "worker"],
                "forbidden_paths": ["docs/", "specs/"],
                "budgets": {"max_files": 10, "max_specs_per_batch": 15, "max_lines_changed": 600, "max_parallel_batches": 3},
                "inputs": {
                    "design_spec_path": "",
                    "project_context_filename": "PROJECT_CONTEXT.md",
                },
                "outputs": {
                    "root_dir": {"path": str(workspace / "out"), "no_overwrite": False},
                },
            }
        },
    }


def make_ctx(workspace: Path, run_id: str = "planner-test") -> Any:
    from core.context import RuntimeContext

    return RuntimeContext(
        command="implement",
        dry_run=False,
        verbose=False,
        command_only_validation=False,
        run_id=run_id,
        project_root=str(workspace),
        config_path=str(workspace / "config.yaml"),
        input_overrides={},
    )


def empty_plan() -> dict[str, Any]:
    return {
        "module_plans": [{"module_tag": "core", "planned_anchors": []}],
        "spec_dependencies": [],
        "shared_contracts": [],
        "spec_issues": [],
        "manual_resolution_items": [],
    }


def planner_mr_item(item_id: str = "MR-1") -> dict[str, Any]:
    return {
        "item_id": item_id,
        "kind": "ambiguity",
        "title": "Ambiguous requirement",
        "question": "Which CORE module does this belong to?",
        "options": [{"option_id": "A", "label": "core/auth"}, {"option_id": "B", "label": "core/profile"}],
        "blocking_reason": "Ambiguous",
        "evidence_refs": ["S1"],
        "resolution_mode": "choose",
    }


def spec_issue(issue_id: str = "SI-1", kind: str = "ambiguity", spec_id: str = "S1") -> dict[str, Any]:
    return {
        "issue_id": issue_id,
        "kind": kind,
        "affected_spec_ids": [spec_id],
        "description": "Spec issue description",
        "resolution_hint": "Edit the AC",
    }
