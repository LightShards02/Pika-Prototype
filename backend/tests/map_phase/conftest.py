"""Shared fixtures for backend/tests/map_phase/."""

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
    "subunit",
    "map_status",
]

_ROWS = [
    {
        "spec_id": "A1",
        "title": "Validate input",
        "requirement": "The system shall validate input.",
        "acceptance_criteria": "AC1",
        "subunit": "auth",
        "map_status": "",
    },
    {
        "spec_id": "A2",
        "title": "Return quickly",
        "requirement": "The system shall return results within 200ms.",
        "acceptance_criteria": "AC2",
        "subunit": "auth",
        "map_status": "",
    },
    {
        "spec_id": "B1",
        "title": "Persist user",
        "requirement": "The system shall persist users.",
        "acceptance_criteria": "AC3",
        "subunit": "profile",
        "map_status": "",
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
    (root / "codebase" / "auth.py").write_text("# stub\n", encoding="utf-8")
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
            "map": {
                "enabled": True,
                "skip_mapped": True,
                "max_acceptance_chars": 0,
                "max_specs_per_subunit": 0,
                "min_remapping_confidence_threshold": 0.0,
                "max_problem_threshold": 1.0,
                "inputs": {
                    "design_spec_path": "",
                    "project_context_filename": "PROJECT_CONTEXT.md",
                },
                "outputs": {
                    "root_dir": {"path": str(workspace / "out"), "no_overwrite": False},
                    "backups_dir": {"path": str(workspace / "out" / "backups"), "no_overwrite": False},
                    "agent_runs_dir": {"path": str(workspace / "out" / "agent_runs"), "no_overwrite": False},
                },
            }
        },
    }


def make_ctx(workspace: Path, run_id: str = "map-test") -> Any:
    from core.context import RuntimeContext

    return RuntimeContext(
        command="map",
        dry_run=False,
        verbose=False,
        command_only_validation=False,
        run_id=run_id,
        project_root=str(workspace),
        config_path=str(workspace / "config.yaml"),
        input_overrides={},
    )


def clean_subunit_output(spec_ids: list[str]) -> dict[str, Any]:
    """Return a clean (non-blocking) per-subunit mapper output for the given spec_ids."""
    mappings = []
    for sid in spec_ids:
        mappings.append({
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
        })
    return {
        "manual_resolution_items": [],
        "run_summary": {"command": "agent map", "status": "success", "summary": "", "blocking_items": 0, "storage_file": ""},
        "created_at": "2026-01-01T00:00:00",
        "mappings": mappings,
    }


def blocking_subunit_output(item_id: str = "MR-1", entity_id: str = "A1") -> dict[str, Any]:
    """Return a blocking per-subunit mapper output."""
    return {
        "manual_resolution_items": [
            {
                "item_id": item_id,
                "kind": "ambiguity",
                "entity_id": entity_id,
                "title": "Ambiguous mapping",
                "question": "Which symbol matches?",
                "options": [
                    {"option_id": "A", "label": "auth.handle_login"},
                    {"option_id": "B", "label": "auth.signin"},
                ],
                "blocking_reason": "Ambiguous code reference",
                "evidence_refs": [entity_id],
                "resolution_mode": "choose",
            }
        ],
        "run_summary": {"command": "agent map", "status": "blocked", "summary": "1 manual item", "blocking_items": 1, "storage_file": ""},
        "created_at": "2026-01-01T00:00:00",
        "mappings": [],
    }
