"""Deterministic harness gates run before the code_evaluator agent.

Six small, language-agnostic checks whose output is *input* to the evaluator
prompt — not a direct lifecycle gate. Every harness returns a list of result
dicts shaped:

    {
        "harness_id": str,
        "spec_id": str | None,
        "passed": bool,
        "details": str,
        "duration_ms": int,
    }

Harnesses never raise: their own errors are surfaced as ``passed=False`` with
``details="<error>"`` so the lifecycle continues.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ALL_HARNESS_IDS: tuple[str, ...] = (
    "syntax_check",
    "import_smoke",
    "unresolved_symbol",
    "forbidden_path_violation",
    "anchor_preservation",
    "diff_size_sanity",
)

DEFAULT_DIFF_SIZE_MAX_LINES = 2000
_PER_FILE_TIMEOUT_S = 5
_RUFF_TOTAL_TIMEOUT_S = 30


def _now_ms() -> int:
    return int(time.monotonic() * 1000)


def _result(
    harness_id: str,
    *,
    spec_id: str | None,
    passed: bool,
    details: str,
    started_ms: int,
) -> dict[str, Any]:
    return {
        "harness_id": harness_id,
        "spec_id": spec_id,
        "passed": passed,
        "details": details[:4000],
        "duration_ms": max(0, _now_ms() - started_ms),
    }


def _iter_spec_touched_files(
    spec_outputs: Mapping[str, Mapping[str, Any]],
) -> Iterable[tuple[str, str]]:
    """Yield (spec_id, touched_file) for every diff touched by each spec."""
    for spec_id, payload in spec_outputs.items():
        diffs = payload.get("diffs") or []
        for diff in diffs:
            if not isinstance(diff, Mapping):
                continue
            touched = diff.get("touched_files") or []
            for path in touched:
                if isinstance(path, str) and path.strip():
                    yield spec_id, path.strip()


def _spec_touched_map(
    spec_outputs: Mapping[str, Mapping[str, Any]],
) -> dict[str, set[str]]:
    """Map spec_id -> set of touched relative paths."""
    out: dict[str, set[str]] = {}
    for spec_id, path in _iter_spec_touched_files(spec_outputs):
        out.setdefault(spec_id, set()).add(path)
    return out


def _all_touched_files(
    spec_outputs: Mapping[str, Mapping[str, Any]],
) -> set[str]:
    return {path for _spec, path in _iter_spec_touched_files(spec_outputs)}


def _is_python_path(rel_path: str) -> bool:
    return rel_path.endswith(".py")


def _resolve(project_root: Path, rel_path: str) -> Path | None:
    """Return absolute path under project_root, or None if it escapes the root."""
    try:
        candidate = (project_root / rel_path).resolve()
        root = project_root.resolve()
    except OSError:
        return None
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _dotted_module_for(project_root: Path, rel_path: str) -> str | None:
    """Convert a project-relative .py path to a dotted module path."""
    if not _is_python_path(rel_path):
        return None
    parts = Path(rel_path).with_suffix("").parts
    if not parts:
        return None
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return None
    return ".".join(parts)


def _normalize_prefix(prefix: str) -> str:
    p = prefix.strip().replace("\\", "/").lstrip("./")
    if not p:
        return ""
    if not p.endswith("/"):
        p += "/"
    return p


def _path_under_forbidden(rel_path: str, forbidden: Sequence[str]) -> str | None:
    """Return the matching forbidden prefix, or None."""
    norm = rel_path.replace("\\", "/").lstrip("./")
    for fp in forbidden:
        nfp = _normalize_prefix(fp)
        if not nfp:
            continue
        if norm == nfp.rstrip("/") or norm.startswith(nfp):
            return nfp
    return None


def run_syntax_check(
    project_root: Path,
    spec_outputs: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Per-touched-file parser invocation. Python: ``ast.parse``. Others skipped."""
    started = _now_ms()
    failures: list[str] = []
    checked = 0
    for path in sorted(_all_touched_files(spec_outputs)):
        if not _is_python_path(path):
            continue
        abs_path = _resolve(project_root, path)
        if abs_path is None or not abs_path.exists() or not abs_path.is_file():
            continue
        checked += 1
        try:
            source = abs_path.read_text(encoding="utf-8")
        except Exception as exc:
            failures.append(f"{path}: read error: {exc}")
            continue
        try:
            ast.parse(source, filename=str(abs_path))
        except SyntaxError as exc:
            failures.append(f"{path}:{exc.lineno or '?'}: {exc.msg}")
        except Exception as exc:
            failures.append(f"{path}: parse error: {exc}")
    if not checked:
        details = "no python files touched; skipped"
        passed = True
    elif failures:
        details = "; ".join(failures)
        passed = False
    else:
        details = f"parsed {checked} python files"
        passed = True
    return [_result("syntax_check", spec_id=None, passed=passed, details=details, started_ms=started)]


def _run_python(
    project_root: Path,
    code: str,
    *,
    timeout: int,
    extra_env: Mapping[str, str] | None = None,
) -> tuple[int, str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPYCACHEPREFIX"] = tempfile.gettempdir()
    pythonpath = str(project_root)
    if env.get("PYTHONPATH"):
        pythonpath = pythonpath + os.pathsep + env["PYTHONPATH"]
    env["PYTHONPATH"] = pythonpath
    if extra_env:
        env.update(extra_env)
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(project_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as exc:
        return 1, f"subprocess error: {exc}"
    stderr = (proc.stderr or "")[-4096:]
    return proc.returncode, stderr


def run_import_smoke(
    project_root: Path,
    spec_outputs: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Best-effort ``import <module>`` per touched python module."""
    started = _now_ms()
    modules: list[tuple[str, str]] = []
    for path in sorted(_all_touched_files(spec_outputs)):
        if not _is_python_path(path):
            continue
        abs_path = _resolve(project_root, path)
        if abs_path is None or not abs_path.exists():
            continue
        dotted = _dotted_module_for(project_root, path)
        if not dotted:
            continue
        modules.append((path, dotted))
    if not modules:
        return [_result("import_smoke", spec_id=None, passed=True, details="no python modules touched; skipped", started_ms=started)]
    failures: list[str] = []
    for rel_path, dotted in modules:
        sub_started = _now_ms()
        rc, stderr = _run_python(project_root, f"import {dotted}", timeout=_PER_FILE_TIMEOUT_S)
        if rc != 0:
            failures.append(f"{rel_path} ({dotted}): rc={rc} {stderr.strip()[:300]}")
        if _now_ms() - started > _RUFF_TOTAL_TIMEOUT_S * 1000:
            failures.append("import_smoke total budget exceeded; remaining modules skipped")
            break
        # discourage 100% CPU loops on extremely tiny modules
        _ = sub_started
    if failures:
        details = "; ".join(failures)
        return [_result("import_smoke", spec_id=None, passed=False, details=details, started_ms=started)]
    return [_result("import_smoke", spec_id=None, passed=True, details=f"imported {len(modules)} modules", started_ms=started)]


def run_unresolved_symbol(
    project_root: Path,
    spec_outputs: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """``ruff check --select F821,F401`` over touched python files (best-effort)."""
    started = _now_ms()
    py_files = [p for p in sorted(_all_touched_files(spec_outputs)) if _is_python_path(p)]
    if not py_files:
        return [_result("unresolved_symbol", spec_id=None, passed=True, details="no python files touched; skipped", started_ms=started)]
    abs_files: list[str] = []
    for rel in py_files:
        abs_path = _resolve(project_root, rel)
        if abs_path is not None and abs_path.exists():
            abs_files.append(str(abs_path))
    if not abs_files:
        return [_result("unresolved_symbol", spec_id=None, passed=True, details="no resolvable python files; skipped", started_ms=started)]
    try:
        proc = subprocess.run(
            ["ruff", "check", "--select", "F821,F401", "--no-cache", *abs_files],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=_RUFF_TOTAL_TIMEOUT_S,
        )
    except FileNotFoundError:
        return [_result("unresolved_symbol", spec_id=None, passed=True, details="ruff not installed; skipped", started_ms=started)]
    except subprocess.TimeoutExpired:
        return [_result("unresolved_symbol", spec_id=None, passed=False, details="ruff timeout", started_ms=started)]
    except Exception as exc:
        return [_result("unresolved_symbol", spec_id=None, passed=False, details=f"ruff error: {exc}", started_ms=started)]
    if proc.returncode == 0:
        return [_result("unresolved_symbol", spec_id=None, passed=True, details=f"ruff clean for {len(abs_files)} files", started_ms=started)]
    output = ((proc.stdout or "") + (proc.stderr or ""))[-4096:]
    return [_result("unresolved_symbol", spec_id=None, passed=False, details=output.strip(), started_ms=started)]


def run_forbidden_path_violation(
    project_root: Path,
    spec_outputs: Mapping[str, Mapping[str, Any]],
    forbidden_path_prefixes: Sequence[str],
) -> list[dict[str, Any]]:
    """Re-assert post-apply that no spec touched a forbidden prefix."""
    started = _now_ms()
    if not forbidden_path_prefixes:
        return [_result("forbidden_path_violation", spec_id=None, passed=True, details="no forbidden_path_prefixes configured", started_ms=started)]
    violations: list[str] = []
    for spec_id, path in _iter_spec_touched_files(spec_outputs):
        match = _path_under_forbidden(path, forbidden_path_prefixes)
        if match is not None:
            violations.append(f"{spec_id}: {path} under {match}")
    if violations:
        return [_result("forbidden_path_violation", spec_id=None, passed=False, details="; ".join(violations), started_ms=started)]
    return [_result("forbidden_path_violation", spec_id=None, passed=True, details="no forbidden-path touches", started_ms=started)]


def _collect_top_level_symbols(abs_path: Path) -> set[str]:
    """Return the set of top-level def/class/assignment names in a python file."""
    try:
        source = abs_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(abs_path))
    except Exception:
        return set()
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    names.add(tgt.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def run_anchor_preservation(
    project_root: Path,
    spec_outputs: Mapping[str, Mapping[str, Any]],
    anchor_plans_by_module: Mapping[str, Mapping[str, Any]],
    spec_to_module_tag: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Confirm every planned anchor exists in the post-implementation file."""
    started = _now_ms()
    if not anchor_plans_by_module:
        return [_result("anchor_preservation", spec_id=None, passed=True, details="no anchor plan available; skipped", started_ms=started)]
    spec_touched = _spec_touched_map(spec_outputs)
    missing: list[str] = []
    checked_anchors = 0
    for spec_id, touched in spec_touched.items():
        module_tag = spec_to_module_tag.get(spec_id)
        if not module_tag:
            continue
        plan = anchor_plans_by_module.get(module_tag)
        if not isinstance(plan, Mapping):
            continue
        for anchor in plan.get("planned_anchors", []) or []:
            if not isinstance(anchor, Mapping):
                continue
            if spec_id not in (anchor.get("spec_ids") or []):
                continue
            planned_path = str(anchor.get("planned_file_path") or "").strip()
            planned_symbol = str(anchor.get("planned_symbol") or "").strip()
            if not planned_path or not planned_symbol:
                continue
            if planned_path not in touched and not _is_python_path(planned_path):
                continue
            abs_path = _resolve(project_root, planned_path)
            if abs_path is None or not abs_path.exists() or not _is_python_path(planned_path):
                continue
            checked_anchors += 1
            symbols = _collect_top_level_symbols(abs_path)
            if planned_symbol not in symbols:
                missing.append(f"{spec_id}: {planned_symbol} missing in {planned_path}")
    if not checked_anchors:
        return [_result("anchor_preservation", spec_id=None, passed=True, details="no python anchors to verify; skipped", started_ms=started)]
    if missing:
        return [_result("anchor_preservation", spec_id=None, passed=False, details="; ".join(missing), started_ms=started)]
    return [_result("anchor_preservation", spec_id=None, passed=True, details=f"verified {checked_anchors} anchors", started_ms=started)]


def run_diff_size_sanity(
    project_root: Path,
    spec_outputs: Mapping[str, Mapping[str, Any]],
    *,
    max_lines: int,
) -> list[dict[str, Any]]:
    """Flag spec-attributed diffs with 0 lines or > max_lines."""
    started = _now_ms()
    flags: list[str] = []
    counted = 0
    for spec_id, payload in spec_outputs.items():
        for diff in payload.get("diffs") or []:
            if not isinstance(diff, Mapping):
                continue
            counted += 1
            diff_path = str(diff.get("diff_path") or "").strip()
            if not diff_path:
                continue
            abs_path = _resolve(project_root, diff_path)
            if abs_path is None or not abs_path.exists():
                continue
            try:
                line_count = sum(1 for _ in abs_path.open("r", encoding="utf-8", errors="replace"))
            except Exception as exc:
                flags.append(f"{spec_id}/{diff.get('diff_id')}: read error: {exc}")
                continue
            if line_count == 0:
                flags.append(f"{spec_id}/{diff.get('diff_id')}: empty diff")
            elif line_count > max_lines:
                flags.append(f"{spec_id}/{diff.get('diff_id')}: {line_count} lines > {max_lines}")
    if not counted:
        return [_result("diff_size_sanity", spec_id=None, passed=True, details="no diffs in batch; skipped", started_ms=started)]
    if flags:
        return [_result("diff_size_sanity", spec_id=None, passed=False, details="; ".join(flags), started_ms=started)]
    return [_result("diff_size_sanity", spec_id=None, passed=True, details=f"{counted} diffs within size bounds", started_ms=started)]


def collect_harness_results(
    *,
    enabled_harnesses: Sequence[str],
    project_root: Path,
    spec_outputs: Mapping[str, Mapping[str, Any]],
    forbidden_path_prefixes: Sequence[str],
    anchor_plans_by_module: Mapping[str, Mapping[str, Any]],
    spec_to_module_tag: Mapping[str, str],
    diff_size_max_lines: int = DEFAULT_DIFF_SIZE_MAX_LINES,
) -> list[dict[str, Any]]:
    """Run every enabled harness; aggregate and return results.

    Each harness is wrapped to never raise: harness internal errors surface as
    ``passed=False`` with ``details`` describing the cause.
    """
    selected = [h for h in enabled_harnesses if h in ALL_HARNESS_IDS]
    seen: set[str] = set()
    ordered: list[str] = []
    for h in selected:
        if h not in seen:
            ordered.append(h)
            seen.add(h)

    runners: dict[str, Any] = {
        "syntax_check": lambda: run_syntax_check(project_root, spec_outputs),
        "import_smoke": lambda: run_import_smoke(project_root, spec_outputs),
        "unresolved_symbol": lambda: run_unresolved_symbol(project_root, spec_outputs),
        "forbidden_path_violation": lambda: run_forbidden_path_violation(project_root, spec_outputs, forbidden_path_prefixes),
        "anchor_preservation": lambda: run_anchor_preservation(project_root, spec_outputs, anchor_plans_by_module, spec_to_module_tag),
        "diff_size_sanity": lambda: run_diff_size_sanity(project_root, spec_outputs, max_lines=diff_size_max_lines),
    }

    out: list[dict[str, Any]] = []
    for harness_id in ordered:
        runner = runners.get(harness_id)
        if runner is None:
            continue
        started = _now_ms()
        try:
            out.extend(runner())
        except Exception as exc:
            out.append(
                _result(
                    harness_id,
                    spec_id=None,
                    passed=False,
                    details=f"harness error: {exc}",
                    started_ms=started,
                )
            )
    return out
