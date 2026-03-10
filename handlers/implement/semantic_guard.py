"""Semantic contract guards and retry helpers for implement agent calls."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from core.context import RuntimeContext
from core.lifecycle import invoke_agent_with_schema_retry, log_lifecycle_event


_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:/")
_UNIFIED_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")


def _normalize_rel_path(path_value: Any) -> str:
    """Normalize a repo-relative path and reject absolute/traversal paths."""
    value = str(path_value or "").replace("\\", "/").strip()
    if not value:
        raise ValueError("empty path")
    while value.startswith("./"):
        value = value[2:]
    if value.startswith("/") or _DRIVE_PREFIX.match(value):
        raise ValueError(f"absolute path is not allowed: {value}")
    parts = [part for part in value.split("/") if part and part != "."]
    if any(part == ".." for part in parts):
        raise ValueError(f"path traversal is not allowed: {value}")
    if not parts:
        raise ValueError("empty path")
    return "/".join(parts)


def _normalize_prefix(path_value: Any) -> str:
    """Normalize path prefix and ensure trailing slash."""
    normalized = _normalize_rel_path(path_value)
    return normalized if normalized.endswith("/") else f"{normalized}/"


def _resolve_diff_path(diff_path: str, project_root: Path) -> Path:
    """Resolve diff path from agent output to an absolute path."""
    path = Path(str(diff_path).strip())
    if path.is_absolute():
        return path
    return (project_root / path).resolve()


def _validate_diff_file_structure(diff_path: str, project_root: Path) -> str | None:
    """Validate that a diff file looks like a unified text patch."""
    resolved = _resolve_diff_path(diff_path, project_root)
    if not resolved.exists() or not resolved.is_file():
        return f"diff_path does not exist: {resolved}"
    try:
        text = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"diff_path is unreadable ({resolved}): {exc}"

    lines = text.splitlines()
    if not lines:
        return f"diff file is empty: {resolved}"

    has_file_headers = False
    has_valid_hunk = False
    for line in lines:
        if line.startswith("--- ") or line.startswith("+++ "):
            has_file_headers = True
        if line.startswith("@@"):
            if not _UNIFIED_HUNK_HEADER.match(line):
                return f"invalid hunk header in {resolved}: {line!r}"
            has_valid_hunk = True

    if not has_file_headers:
        return f"missing file headers in diff: {resolved}"
    if not has_valid_hunk:
        return f"missing unified hunk headers in diff: {resolved}"
    return None


def _git_repo_root_and_prefix(root: Path) -> tuple[Path | None, str]:
    """Return git top-level root and prefix; (None, '') when unavailable."""
    top = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if top.returncode != 0:
        return None, ""
    git_root = Path(top.stdout.strip()).resolve()
    pref = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-prefix"],
        capture_output=True,
        text=True,
        check=False,
    )
    prefix = pref.stdout.strip().replace("\\", "/") if pref.returncode == 0 else ""
    return git_root, prefix


def _normalize_dir_arg(path: str) -> str:
    """Normalize git apply --directory arg."""
    value = str(path or "").replace("\\", "/").strip("/")
    return value


def _patch_check_directory_candidates(
    *,
    git_prefix: str,
    codebase_prefix_rel: str,
) -> list[str]:
    """Return deterministic directory candidates for git apply --check."""
    candidates: list[str] = []
    gp = _normalize_dir_arg(git_prefix)
    cp = _normalize_dir_arg(codebase_prefix_rel)
    if gp and cp:
        candidates.append(f"{gp}/{cp}")
    elif cp:
        candidates.append(cp)
    if gp:
        candidates.append(gp)
    candidates.append("")
    deduped: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _validate_diff_patch_applies(
    diff_path: str,
    project_root: Path,
    *,
    codebase_prefix_rel: str = "",
) -> str | None:
    """Validate patch applicability with git apply --check when git is available."""
    git_root, git_prefix = _git_repo_root_and_prefix(project_root)
    if git_root is None:
        return None
    resolved = _resolve_diff_path(diff_path, project_root)
    if not resolved.exists() or not resolved.is_file():
        return f"diff_path does not exist: {resolved}"

    candidates = _patch_check_directory_candidates(
        git_prefix=git_prefix,
        codebase_prefix_rel=codebase_prefix_rel,
    )
    failures: list[str] = []
    for directory in candidates:
        cmd = ["git", "-C", str(git_root), "apply", "--check"]
        if directory:
            cmd.extend(["--directory", directory])
        cmd.append(str(resolved))
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            return None
        stderr = (proc.stderr or "").strip()
        failures.append(stderr or f"non-zero exit ({proc.returncode})")

    detail = failures[0] if failures else "patch check failed"
    return f"git apply --check failed for {resolved}: {detail}"


def build_directory_tree_snapshot(
    root: Path,
    *,
    max_depth: int = 3,
    max_entries: int = 300,
) -> str:
    """Build a deterministic, bounded directory tree snapshot."""
    root_resolved = root.resolve()
    lines = [f"Root: {root_resolved}"]
    entries = 0

    def walk(dir_path: Path, depth: int) -> None:
        nonlocal entries
        if depth > max_depth or entries >= max_entries:
            return
        try:
            children = sorted(dir_path.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            return
        for child in children:
            if entries >= max_entries:
                return
            rel = child.relative_to(root_resolved).as_posix()
            suffix = "/" if child.is_dir() else ""
            lines.append(f"- {rel}{suffix}")
            entries += 1
            if child.is_dir():
                walk(child, depth + 1)

    walk(root_resolved, 1)
    if entries >= max_entries:
        lines.append(f"- ... truncated after {max_entries} entries")
    return "\n".join(lines)


def build_planner_path_contract(
    module_catalog: dict[str, Any],
    type_placement_path: str,
    forbidden_paths: list[str],
) -> dict[str, Any]:
    """Build planner path constraints from module catalog and config."""
    by_module: dict[str, list[str]] = {}
    for module in module_catalog.get("modules", []) if isinstance(module_catalog.get("modules"), list) else []:
        if not isinstance(module, dict):
            continue
        module_tag = str(module.get("module_tag", "")).strip()
        if not module_tag:
            continue
        roots: list[str] = []
        for raw_root in module.get("root_dirs", []) if isinstance(module.get("root_dirs"), list) else []:
            try:
                roots.append(_normalize_prefix(raw_root))
            except ValueError:
                continue
        if roots:
            by_module[module_tag] = sorted(set(roots))

    shared_prefix = _normalize_prefix(type_placement_path)
    forbidden: list[str] = []
    for path in forbidden_paths:
        try:
            forbidden.append(_normalize_prefix(path))
        except ValueError:
            continue

    return {
        "module_root_prefixes_by_tag": by_module,
        "shared_contract_prefix": shared_prefix,
        "forbidden_path_prefixes": sorted(set(forbidden)),
    }


def validate_unified_plan_semantics(
    plan: dict[str, Any],
    path_contract: dict[str, Any],
) -> list[str]:
    """Validate planner output path semantics against module/path constraints."""
    violations: list[str] = []
    by_module = path_contract.get("module_root_prefixes_by_tag", {})
    shared_prefix = str(path_contract.get("shared_contract_prefix", ""))
    forbidden = [str(p) for p in path_contract.get("forbidden_path_prefixes", [])]

    for module_plan in plan.get("module_plans", []) if isinstance(plan.get("module_plans"), list) else []:
        if not isinstance(module_plan, dict):
            continue
        module_tag = str(module_plan.get("module_tag", "")).strip()
        allowed_roots = [str(p) for p in by_module.get(module_tag, [])]
        for anchor in module_plan.get("planned_anchors", []) if isinstance(module_plan.get("planned_anchors"), list) else []:
            if not isinstance(anchor, dict):
                continue
            raw_path = anchor.get("planned_file_path", "")
            try:
                rel = _normalize_rel_path(raw_path)
            except ValueError as exc:
                violations.append(f"module {module_tag} planned_file_path invalid ({raw_path}): {exc}")
                continue
            if any(rel.lower().startswith(prefix.lower()) for prefix in forbidden):
                violations.append(f"module {module_tag} planned_file_path forbidden: {rel}")
            if allowed_roots and not any(rel.lower().startswith(prefix.lower()) for prefix in allowed_roots):
                violations.append(
                    f"module {module_tag} planned_file_path outside module roots {allowed_roots}: {rel}"
                )

    for contract in plan.get("shared_contracts", []) if isinstance(plan.get("shared_contracts"), list) else []:
        if not isinstance(contract, dict):
            continue
        raw_path = contract.get("planned_file_path", "")
        try:
            rel = _normalize_rel_path(raw_path)
        except ValueError as exc:
            violations.append(f"shared_contract planned_file_path invalid ({raw_path}): {exc}")
            continue
        if shared_prefix and not rel.lower().startswith(shared_prefix.lower()):
            violations.append(
                f"shared_contract planned_file_path must be under {shared_prefix}: {rel}"
            )
        if any(rel.lower().startswith(prefix.lower()) for prefix in forbidden):
            violations.append(f"shared_contract planned_file_path forbidden: {rel}")

    return sorted(set(violations))


def build_batch_path_contract(
    brief: dict[str, Any],
    type_placement_path: str,
    forbidden_paths: list[str],
) -> dict[str, Any]:
    """Build implementer batch path constraints from brief/config."""
    prefixes: set[str] = set()
    exact_paths: set[str] = set()
    for row in brief.get("spec_rows", []) if isinstance(brief.get("spec_rows"), list) else []:
        if not isinstance(row, dict):
            continue
        module_tag = str(row.get("module_tag", "")).strip()
        if module_tag:
            prefixes.add(f"{module_tag}/")
    for anchor in brief.get("planned_anchors", []) if isinstance(brief.get("planned_anchors"), list) else []:
        if not isinstance(anchor, dict):
            continue
        try:
            rel = _normalize_rel_path(anchor.get("planned_file_path", ""))
            exact_paths.add(rel)
            parent = Path(rel).parent.as_posix()
            if parent and parent != ".":
                prefixes.add(f"{parent}/")
        except ValueError:
            continue
    for contract in brief.get("shared_contracts", []) if isinstance(brief.get("shared_contracts"), list) else []:
        if not isinstance(contract, dict):
            continue
        try:
            rel = _normalize_rel_path(contract.get("planned_file_path", ""))
            exact_paths.add(rel)
            parent = Path(rel).parent.as_posix()
            if parent and parent != ".":
                prefixes.add(f"{parent}/")
        except ValueError:
            continue
    shared_contracts = (
        brief.get("shared_contracts", [])
        if isinstance(brief.get("shared_contracts", []), list)
        else []
    )
    if shared_contracts:
        try:
            prefixes.add(_normalize_prefix(type_placement_path))
        except ValueError:
            pass
    forbidden: list[str] = []
    for path in forbidden_paths:
        try:
            forbidden.append(_normalize_prefix(path))
        except ValueError:
            continue
    return {
        "allowed_prefixes": sorted(prefixes),
        "allowed_exact_paths": sorted(exact_paths),
        "forbidden_path_prefixes": sorted(set(forbidden)),
    }


def validate_implement_output_semantics(
    output: dict[str, Any],
    batch_path_contract: dict[str, Any],
    project_root: Path,
    *,
    codebase_prefix_rel: str = "",
) -> list[str]:
    """Validate implementer output path semantics before patch apply."""
    violations: list[str] = []
    allowed_prefixes = [str(p) for p in batch_path_contract.get("allowed_prefixes", [])]
    allowed_exact = {str(p) for p in batch_path_contract.get("allowed_exact_paths", [])}
    forbidden_prefixes = [str(p) for p in batch_path_contract.get("forbidden_path_prefixes", [])]
    touched_all: set[str] = set()
    diff_file_checks: dict[str, str | None] = {}
    diff_plan_by_id: dict[str, dict[str, Any]] = {}
    spec_id_pattern = re.compile(r"^[A-Za-z][0-9]+$")

    raw_plan = output.get("diff_plan", [])
    if raw_plan not in (None, ""):
        if not isinstance(raw_plan, list):
            violations.append("diff_plan must be an array when provided")
        else:
            for idx, item in enumerate(raw_plan, start=1):
                if not isinstance(item, dict):
                    violations.append(f"diff_plan[{idx}] must be an object")
                    continue
                diff_id = str(item.get("diff_id", "")).strip()
                if not diff_id:
                    violations.append(f"diff_plan[{idx}] missing diff_id")
                    continue
                if diff_id in diff_plan_by_id:
                    violations.append(f"diff_plan has duplicate diff_id: {diff_id}")
                    continue
                owner_spec_id = str(item.get("owner_spec_id", "")).strip()
                if owner_spec_id and not spec_id_pattern.fullmatch(owner_spec_id):
                    violations.append(f"diff_plan[{idx}] owner_spec_id invalid: {owner_spec_id}")
                related = item.get("related_spec_ids", [])
                if isinstance(related, list) and owner_spec_id:
                    related_ids = [str(ref).strip() for ref in related if str(ref).strip()]
                    if related_ids and owner_spec_id not in related_ids:
                        violations.append(
                            f"diff_plan[{idx}] related_spec_ids must include owner_spec_id {owner_spec_id}"
                        )
                diff_plan_by_id[diff_id] = item
    else:
        has_spec_payload = any(
            key not in {"run_summary", "diff_plan"} and isinstance(payload, dict)
            for key, payload in output.items()
        )
        if has_spec_payload:
            violations.append("diff_plan is required when spec results are present")

    for spec_id, payload in output.items():
        if spec_id in {"run_summary", "diff_plan"} or not isinstance(payload, dict):
            continue
        diffs: list[dict[str, Any]] = []
        raw_refs = payload.get("diff_refs")
        if isinstance(raw_refs, list):
            refs = [str(ref).strip() for ref in raw_refs if str(ref).strip()]
            if not refs:
                violations.append(f"{spec_id} diff_refs is empty")
                continue
            if not diff_plan_by_id:
                violations.append(f"{spec_id} uses diff_refs but diff_plan is missing")
                continue
            missing_refs = [ref for ref in refs if ref not in diff_plan_by_id]
            if missing_refs:
                violations.append(f"{spec_id} diff_refs unknown diff_id(s): {', '.join(missing_refs)}")
                continue
            diffs = [diff_plan_by_id[ref] for ref in refs]
        else:
            violations.append(f"{spec_id} must include diff_refs[]")
            continue

        for diff in diffs:
            raw_diff_path = str(diff.get("diff_path", "")).strip()
            diff_id = str(diff.get("diff_id", "")).strip() or "<missing_diff_id>"
            if not raw_diff_path:
                violations.append(f"{spec_id} diff {diff_id} missing diff_path")
            else:
                if raw_diff_path not in diff_file_checks:
                    diff_file_checks[raw_diff_path] = _validate_diff_file_structure(
                        raw_diff_path,
                        project_root,
                    )
                diff_issue = diff_file_checks.get(raw_diff_path)
                if diff_issue:
                    violations.append(f"{spec_id} diff {diff_id} invalid patch: {diff_issue}")
                else:
                    apply_issue = _validate_diff_patch_applies(
                        raw_diff_path,
                        project_root,
                        codebase_prefix_rel=codebase_prefix_rel,
                    )
                    if apply_issue:
                        violations.append(f"{spec_id} diff {diff_id} invalid patch: {apply_issue}")
            touched = diff.get("touched_files", [])
            if not isinstance(touched, list):
                continue
            for touched_path in touched:
                raw = str(touched_path)
                try:
                    rel = _normalize_rel_path(raw)
                except ValueError as exc:
                    violations.append(f"{spec_id} touched_files invalid ({raw}): {exc}")
                    continue
                touched_all.add(rel)
                if any(rel.lower().startswith(prefix.lower()) for prefix in forbidden_prefixes):
                    violations.append(f"{spec_id} touched_files forbidden path: {rel}")
                if allowed_prefixes and not (
                    rel in allowed_exact
                    or any(rel.lower().startswith(prefix.lower()) for prefix in allowed_prefixes)
                ):
                    violations.append(
                        f"{spec_id} touched_files outside allowed prefixes {allowed_prefixes}: {rel}"
                    )

    for spec_id, payload in output.items():
        if spec_id in {"run_summary", "diff_plan"} or not isinstance(payload, dict):
            continue
        mapped = payload.get("mapped_classes_functions", [])
        if isinstance(mapped, list):
            for item in mapped:
                if not isinstance(item, dict):
                    continue
                raw = str(item.get("file_path", "")).strip()
                if not raw:
                    continue
                try:
                    rel = _normalize_rel_path(raw)
                except ValueError as exc:
                    violations.append(f"{spec_id} mapped_classes_functions.file_path invalid ({raw}): {exc}")
                    continue
                exists = (project_root / rel).is_file()
                if not exists and rel not in touched_all:
                    violations.append(
                        f"{spec_id} mapped_classes_functions.file_path not present in codebase or touched_files: {rel}"
                    )

        mapped_tests = payload.get("mapped_test_cases", [])
        if isinstance(mapped_tests, list):
            for item in mapped_tests:
                if not isinstance(item, dict):
                    continue
                raw = str(item.get("test_file", "")).strip()
                if not raw:
                    continue
                try:
                    rel = _normalize_rel_path(raw)
                except ValueError as exc:
                    violations.append(f"{spec_id} mapped_test_cases.test_file invalid ({raw}): {exc}")
                    continue
                exists = (project_root / rel).is_file()
                if not exists and rel not in touched_all:
                    violations.append(
                        f"{spec_id} mapped_test_cases.test_file not present in codebase or touched_files: {rel}"
                    )

    return sorted(set(violations))


def _format_semantic_retry_context(
    label: str,
    attempt: int,
    max_attempts: int,
    violations: list[str],
) -> str:
    """Render semantic retry context for prompt injection."""
    lines = [
        f"[Semantic Retry] {label} violated path/contract constraints.",
        f"Attempt {attempt}/{max_attempts}. Fix all violations and regenerate complete output.",
        "Violations:",
    ]
    for violation in violations[:20]:
        lines.append(f"- {violation}")
    if len(violations) > 20:
        lines.append(f"- ... and {len(violations) - 20} more")
    lines.append(
        "Regenerate diff files from the CURRENT filesystem state. Do not reuse stale diff files or stale hunk contexts."
    )
    lines.append(
        "For every diff, ensure `git apply --check` would pass against the current codebase path scope."
    )
    return "\n".join(lines)


def _is_within(child: Path, parent: Path) -> bool:
    """Return True when child is equal to or contained by parent."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _collect_output_diff_paths(output: dict[str, Any]) -> list[str]:
    """Collect diff_path values from top-level diff_plan."""
    collected: list[str] = []
    raw_plan = output.get("diff_plan", [])
    if isinstance(raw_plan, list):
        for item in raw_plan:
            if isinstance(item, dict):
                path = str(item.get("diff_path", "")).strip()
                if path:
                    collected.append(path)
    deduped: list[str] = []
    seen: set[str] = set()
    for path in collected:
        if path in seen:
            continue
        seen.add(path)
        deduped.append(path)
    return deduped


def _cleanup_retry_diff_artifacts(
    output: dict[str, Any],
    template_vars: dict[str, Any],
) -> int:
    """Best-effort cleanup of previously referenced diff files before retry."""
    artifacts_raw = str(template_vars.get("agent_artifacts_dir", "")).strip()
    if not artifacts_raw:
        return 0
    artifacts_dir = Path(artifacts_raw).resolve()
    if not artifacts_dir.exists() or not artifacts_dir.is_dir():
        return 0

    removed = 0
    for raw_path in _collect_output_diff_paths(output):
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = (artifacts_dir / raw_path).resolve()
        else:
            candidate = candidate.resolve()
        if not _is_within(candidate, artifacts_dir):
            continue
        if candidate.exists() and candidate.is_file():
            try:
                candidate.unlink()
                removed += 1
            except OSError:
                continue
    return removed


def invoke_with_semantic_retry(
    *,
    prompt_name: str,
    template_vars: dict[str, Any],
    schema_path: Path | None,
    config: dict[str, Any],
    ctx: RuntimeContext,
    semantic_validator: Callable[[dict[str, Any]], list[str]],
    semantic_validation_retries: int,
    validation_label: str,
    local_workspace_override: Path | None = None,
    pre_attempt_hook: Callable[[int, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Invoke agent with schema + semantic retry loops."""
    attempts = max(1, int(semantic_validation_retries) + 1)
    render_vars = dict(template_vars)
    render_vars.setdefault("semantic_retry_context", "")
    last_violations: list[str] = []

    for attempt in range(1, attempts + 1):
        if pre_attempt_hook is not None:
            pre_attempt_hook(attempt, render_vars)
        output = invoke_agent_with_schema_retry(
            prompt_name=prompt_name,
            template_vars=render_vars,
            schema_path=schema_path,
            config=config,
            ctx=ctx,
            local_workspace_override=local_workspace_override,
        )
        manual_items = output.get("manual_resolution_items")
        if isinstance(manual_items, list) and manual_items:
            return output

        violations = semantic_validator(output)
        if not violations:
            if attempt > 1:
                sys.stderr.write(
                    f"[PIKA] {validation_label}: semantic validation passed on attempt {attempt}\n"
                )
                sys.stderr.flush()
                log_lifecycle_event(
                    "lifecycle_semantic_validation_passed_after_retry",
                    command=ctx.command,
                    run_id=ctx.run_id,
                    extra={
                        "prompt_name": prompt_name,
                        "validation_label": validation_label,
                        "attempt": attempt,
                        "max_attempts": attempts,
                    },
                )
            return output

        last_violations = violations
        log_lifecycle_event(
            "lifecycle_semantic_validation_failed",
            command=ctx.command,
            run_id=ctx.run_id,
            extra={
                "prompt_name": prompt_name,
                "validation_label": validation_label,
                "attempt": attempt,
                "max_attempts": attempts,
                "violation_count": len(violations),
                "violations": json.dumps(violations[:8]),
            },
        )
        if attempt >= attempts:
            sys.stderr.write(
                f"[PIKA] {validation_label}: semantic validation failed after {attempts} attempt(s)\n"
            )
            sys.stderr.flush()
            break
        removed = _cleanup_retry_diff_artifacts(output, render_vars)
        if removed > 0:
            log_lifecycle_event(
                "lifecycle_semantic_retry_diff_cleanup",
                command=ctx.command,
                run_id=ctx.run_id,
                extra={
                    "prompt_name": prompt_name,
                    "validation_label": validation_label,
                    "attempt": attempt,
                    "removed_diff_files": removed,
                },
            )
        sys.stderr.write(
            f"[PIKA] {validation_label}: semantic validation failed (attempt {attempt}/{attempts}), retrying...\n"
        )
        sys.stderr.flush()
        render_vars["semantic_retry_context"] = _format_semantic_retry_context(
            validation_label,
            attempt + 1,
            attempts,
            violations,
        )

    raise ValueError(
        f"{validation_label} semantic validation failed after {attempts} attempt(s): "
        + "; ".join(last_violations[:8])
    )


def default_verification_commands_for_batch(
    root: Path,
    brief: dict[str, Any],
    configured_commands: Any,
) -> list[str]:
    """Return configured verification commands or deterministic safe defaults."""
    if isinstance(configured_commands, list):
        resolved = [str(cmd).strip() for cmd in configured_commands if str(cmd).strip()]
        if resolved:
            return resolved

    module_tags = sorted(
        {
            str(row.get("module_tag", "")).strip()
            for row in brief.get("spec_rows", [])
            if isinstance(row, dict) and str(row.get("module_tag", "")).strip()
        }
    )
    existing_module_dirs = [tag for tag in module_tags if (root / tag).is_dir()]
    if not existing_module_dirs:
        existing_module_dirs = ["."]

    has_pytest = (
        subprocess.run(
            ["python", "-c", "import pytest"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        == 0
    )
    if has_pytest:
        test_targets = _verification_test_targets_for_batch(root, brief, existing_module_dirs)
        if test_targets:
            return [f"python -m pytest {target} -q" for target in test_targets]
    return [f"python -m compileall {' '.join(existing_module_dirs)} -q"]


def _git_show_prefix(root: Path) -> str:
    """Return git prefix for root relative to repo top-level, or empty when unavailable."""
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-prefix"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    prefix = proc.stdout.strip().replace("\\", "/")
    if prefix and not prefix.endswith("/"):
        prefix = f"{prefix}/"
    return prefix


def _is_git_repo(root: Path) -> bool:
    """Return True when root is inside a git work tree."""
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0 and proc.stdout.strip().lower() == "true"


def _git_head_path_exists(root: Path, rel_path: str) -> bool:
    """Return True when rel_path exists in git HEAD (tree or blob)."""
    normalized = str(rel_path).replace("\\", "/").strip().strip("/")
    if not normalized:
        return False
    prefix = _git_show_prefix(root)
    candidate = f"{prefix}{normalized}" if prefix else normalized
    proc = subprocess.run(
        ["git", "-C", str(root), "cat-file", "-e", f"HEAD:{candidate}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def _verification_test_targets_for_batch(
    root: Path,
    brief: dict[str, Any],
    module_dirs: list[str],
) -> list[str]:
    """Resolve deterministic pytest targets visible in verification worktree context."""
    planned_anchor_paths: list[str] = []
    for anchor in brief.get("planned_anchors", []) if isinstance(brief.get("planned_anchors", []), list) else []:
        if not isinstance(anchor, dict):
            continue
        file_path = str(anchor.get("planned_file_path", "")).replace("\\", "/").strip().lstrip("/")
        if file_path:
            planned_anchor_paths.append(file_path)

    targets: list[str] = []
    in_git_repo = _is_git_repo(root)
    for module in module_dirs:
        target = f"{module}/tests"
        if not (root / module / "tests").is_dir():
            continue
        target_prefix = f"{target}/".lower()
        planned_test_files = [
            path
            for path in planned_anchor_paths
            if path.lower().startswith(target_prefix) and _looks_like_pytest_file(path)
        ]
        if planned_test_files:
            targets.append(target)
            continue
        if not in_git_repo:
            if _local_has_pytest_files(root / module / "tests"):
                targets.append(target)
            continue
        if _git_head_path_exists(root, target) and _git_head_has_pytest_files(root, target):
            targets.append(target)
    return targets


def _looks_like_pytest_file(path: str) -> bool:
    """Return True when path appears to be a pytest test module."""
    name = Path(str(path)).name.lower()
    return name.endswith(".py") and (name.startswith("test_") or name == "conftest.py")


def _local_has_pytest_files(test_dir: Path) -> bool:
    """Return True when local filesystem contains pytest modules under test_dir."""
    try:
        for path in test_dir.rglob("*.py"):
            if _looks_like_pytest_file(path.as_posix()):
                return True
    except OSError:
        return False
    return False


def _git_head_has_pytest_files(root: Path, rel_test_dir: str) -> bool:
    """Return True when git HEAD contains pytest modules under rel_test_dir."""
    prefix = _git_show_prefix(root)
    candidate = f"{prefix}{str(rel_test_dir).replace('\\', '/').strip('/')}" if prefix else str(rel_test_dir).replace(
        "\\", "/"
    ).strip("/")
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "--name-only", "HEAD", "--", candidate],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return False
    return any(_looks_like_pytest_file(line.strip()) for line in proc.stdout.splitlines() if line.strip())
