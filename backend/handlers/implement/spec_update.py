"""Design spec and test spec update logic for implement workflow."""

from __future__ import annotations

import csv
import re
import shutil
from pathlib import Path
from typing import Any

from core.context import RuntimeContext
from core.format_sads import load_sads_csv_or_xlsx, rows_to_csv
from core.lifecycle import resolve_output_path
from core.time_utils import format_timestamp_local_minutes_filename

from handlers.implement.helpers import _find_col, _write_json

_TEST_SPEC_HEADERS = [
    "test_id",
    "test_name",
    "test_description",
    "framework",
    "test_file",
    "test_case",
]


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read rows from CSV file into dictionaries."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def _write_csv_rows(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    """Write dictionary rows to CSV with explicit headers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in headers})


def _next_test_id(rows: list[dict[str, str]]) -> int:
    """Return next numeric suffix for test_id values formatted as T{N}."""
    max_value = 0
    for row in rows:
        match = re.fullmatch(r"T(\d+)", str(row.get("test_id", "")).strip())
        if match:
            max_value = max(max_value, int(match.group(1)))
    return max_value + 1


def _backup_file(config: dict[str, Any], ctx: RuntimeContext, root: Path, source: Path, category: str) -> None:
    """Create timestamped backup copy when source file exists."""
    if not source.exists() or not source.is_file():
        return
    backups = resolve_output_path(
        config, root, "backups_dir", command="implement"
    ) or (root / "out" / "backups")
    destination = backups / category
    destination.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix or ".csv"
    name = f"{source.stem}_{format_timestamp_local_minutes_filename()}_{ctx.run_id[:8]}{suffix}"
    shutil.copy2(source, destination / name)


def _update_design_and_test_spec(
    config: dict[str, Any],
    ctx: RuntimeContext,
    impl: dict[str, Any],
    design_path: Path,
    spec_outputs: dict[str, dict[str, Any]],
) -> None:
    """Update design spec mapped columns and maintain deduplicated test_spec CSV."""
    if not spec_outputs:
        return
    root = Path(ctx.project_root)
    headers, rows = load_sads_csv_or_xlsx(design_path)
    spec_col = _find_col(headers, "spec_id")
    if spec_col is None:
        raise ValueError("Design spec missing spec_id; cannot apply implement mappings")
    if _find_col(headers, "mapped_code_symbols") is None:
        headers.append("mapped_code_symbols")
        for row in rows:
            row["mapped_code_symbols"] = ""
    if _find_col(headers, "mapped_test_cases") is None:
        headers.append("mapped_test_cases")
        for row in rows:
            row["mapped_test_cases"] = ""
    map_col = _find_col(headers, "mapped_code_symbols") or "mapped_code_symbols"
    test_col = _find_col(headers, "mapped_test_cases") or "mapped_test_cases"
    by_spec = {str(row.get(spec_col, "")).strip(): row for row in rows}

    test_path = (
        Path(impl["test_spec_path"])
        if Path(impl["test_spec_path"]).is_absolute()
        else (root / impl["test_spec_path"]).resolve()
    )
    test_rows = _read_csv_rows(test_path) if test_path.exists() else []
    tuple_to_id = {
        (str(row.get("framework", "")), str(row.get("test_file", "")), str(row.get("test_case", ""))): str(row.get("test_id", ""))
        for row in test_rows
        if str(row.get("test_id", "")).strip()
    }
    next_id = _next_test_id(test_rows)

    for spec_id, payload in spec_outputs.items():
        row = by_spec.get(spec_id)
        if row is None:
            continue
        symbols = [
            str(item.get("qualified_name", "")).strip()
            for item in payload.get("mapped_classes_functions", [])
            if isinstance(item, dict) and str(item.get("qualified_name", "")).strip()
        ]
        row[map_col] = ",".join(symbols)
        mapped_ids: list[str] = []
        for item in payload.get("mapped_test_cases", []):
            if not isinstance(item, dict):
                continue
            key = (
                str(item.get("framework", "")).strip(),
                str(item.get("test_file", "")).strip(),
                str(item.get("test_case", "")).strip(),
            )
            if not all(key):
                continue
            test_id = tuple_to_id.get(key)
            if not test_id:
                test_id = f"T{next_id}"
                next_id += 1
                tuple_to_id[key] = test_id
                test_rows.append(
                    {
                        "test_id": test_id,
                        "test_name": key[2],
                        "test_description": "",
                        "framework": key[0],
                        "test_file": key[1],
                        "test_case": key[2],
                    }
                )
            mapped_ids.append(test_id)
        row[test_col] = ",".join(mapped_ids)

    _backup_file(config, ctx, root, design_path, "implement")
    design_path.write_text(rows_to_csv(headers, rows), encoding="utf-8")
    _backup_file(config, ctx, root, test_path, "implement")
    _write_csv_rows(test_path, _TEST_SPEC_HEADERS, test_rows)
