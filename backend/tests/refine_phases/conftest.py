"""Shared fixtures for backend/tests/refine_phases/."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


_SAMPLE_HEADERS = ["spec_id", "module_tag", "module_role", "requirement"]

_DECOMPOSABLE_ROWS = [
    {
        "spec_id": "S1",
        "module_tag": "core",
        "module_role": "domain",
        "requirement": "The system shall validate user input.",
    },
    {
        "spec_id": "S2",
        "module_tag": "core",
        "module_role": "domain",
        "requirement": "The system shall return results quickly.",
    },
]


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [",".join(headers)]
    for row in rows:
        lines.append(",".join(row.get(h, "") for h in headers))
    path.write_text("\n".join(lines), encoding="utf-8")


@pytest.fixture()
def workspace_root(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    (root / "PROJECT_CONTEXT.md").write_text("# test ctx", encoding="utf-8")
    return root


@pytest.fixture()
def design_csv(workspace_root: Path) -> Path:
    path = workspace_root / "DESIGN-SPEC.csv"
    _write_csv(path, _SAMPLE_HEADERS, _DECOMPOSABLE_ROWS)
    return path


def make_config(workspace: Path, design_path: str | None = None, *, decomposition_enabled: bool = True, decomposition_blocking: bool = False) -> dict[str, Any]:
    return {
        "agent": {"provider": "stub", "schema_validation_retries": 0},
        "project": {"name": "test", "root_dir": str(workspace)},
        "commands": {
            "refine": {
                "enabled": True,
                "decomposition": {
                    "enabled": decomposition_enabled,
                    "blocking": decomposition_blocking,
                    "similarity_threshold": 0.85,
                    "variance_threshold": 0.15,
                },
                "inputs": {
                    "design_spec_path": design_path or "",
                    "project_context_filename": "PROJECT_CONTEXT.md",
                },
                "outputs": {
                    "root_dir": {"path": str(workspace / "out"), "no_overwrite": False},
                    "design_spec_path": {
                        "path": str(workspace / "out" / "REFINED-SPEC.csv"),
                        "no_overwrite": False,
                    },
                },
            }
        },
    }


def make_ctx(workspace: Path, run_id: str = "phase-test") -> Any:
    from core.context import RuntimeContext

    return RuntimeContext(
        command="refine",
        dry_run=False,
        verbose=False,
        command_only_validation=False,
        run_id=run_id,
        project_root=str(workspace),
        config_path="config/config.yaml",
        input_overrides={},
    )
