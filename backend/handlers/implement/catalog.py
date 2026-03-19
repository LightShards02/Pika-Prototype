"""Module catalog and workset selection for implement workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.constants import ImplementStatus
from core.implement_types import ModuleCatalog, ModuleCatalogEntry

from handlers.implement.helpers import _find_col, _report_implement_phase


def _select_workset(headers: list[str], rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Select rows with implementation_status != Completed and required fields present."""
    spec_col = _find_col(headers, "spec_id")
    tag_col = _find_col(headers, "module_tag")
    role_col = _find_col(headers, "module_role")
    status_col = _find_col(headers, "implementation_status")
    missing = [
        name
        for name, col in (("spec_id", spec_col), ("module_tag", tag_col), ("module_role", role_col))
        if col is None
    ]
    if missing:
        raise ValueError("Missing required columns for implement: " + ", ".join(missing))
    selected: list[dict[str, str]] = []
    for idx, row in enumerate(rows, start=1):
        status = (row.get(status_col, "") if status_col else "").strip().lower()
        if status == ImplementStatus.COMPLETED:
            continue
        spec_id = (row.get(spec_col, "") or "").strip()
        tag = (row.get(tag_col, "") or "").strip()
        role = (row.get(role_col, "") or "").strip().lower()
        if not spec_id or not tag or not role:
            raise ValueError(
                f"Selected row {idx} is missing required spec_id/module_tag/module_role"
            )
        updated = dict(row)
        updated["spec_id"] = spec_id
        updated["module_tag"] = tag
        updated["module_role"] = role
        selected.append(updated)
    return selected


def _build_module_catalog(
    rows: list[dict[str, str]],
    allowed_roles: set[str],
    codebase_dir: Path | None = None,
) -> ModuleCatalog:
    """Build module catalog by module_tag with strict role consistency.

    When codebase_dir is provided and exists, scans for actual subdirectories
    matching each module_tag. Falls back to fabricated root_dirs when not found,
    with a warning.
    """
    grouped: dict[str, set[str]] = {}
    for row in rows:
        grouped.setdefault(row["module_tag"], set()).add(row["module_role"])
    modules: list[ModuleCatalogEntry] = []
    search_root = codebase_dir if (codebase_dir and codebase_dir.exists() and codebase_dir.is_dir()) else None
    existing_dirs: set[str] = set()
    if search_root:
        for p in search_root.iterdir():
            if p.is_dir():
                existing_dirs.add(p.name)
    for module_tag in sorted(grouped):
        roles = grouped[module_tag]
        if len(roles) != 1:
            raise ValueError(
                f"Inconsistent module_role for module_tag '{module_tag}': {sorted(roles)}"
            )
        role = next(iter(roles))
        if role not in allowed_roles:
            raise ValueError(f"Invalid module_role '{role}' for module_tag '{module_tag}'")
        root_dirs: list[str]
        if existing_dirs:
            match = next((d for d in existing_dirs if d.upper() == module_tag.upper()), None)
            if match:
                root_dirs = [f"{match}/"]
            else:
                root_dirs = [f"{module_tag}/"]
                _report_implement_phase(
                    "Catalog",
                    "fallback",
                    f"module {module_tag}: no matching dir in codebase, using fabricated root_dirs",
                )
        else:
            root_dirs = [f"{module_tag}/"]
            if search_root is None and codebase_dir:
                _report_implement_phase(
                    "Catalog",
                    "fallback",
                    f"module {module_tag}: codebase_dir not found, using fabricated root_dirs",
                )
        modules.append(
            {
                "module_tag": module_tag,
                "module_role": role,
                "root_dirs": root_dirs,
                "languages": [],
            }
        )
    return {"modules": modules}


def _minimal_specs(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Return narrow set of row fields for planner prompt packets."""
    keys = ["spec_id", "title", "requirement", "acceptance_criteria", "module_tag", "module_role"]
    return [{k: row.get(k, "") for k in keys} for row in rows]
