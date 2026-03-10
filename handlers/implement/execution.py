"""Batch execution, patch application, and verification for implement workflow."""

from __future__ import annotations

import difflib
import json
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from core.codebase_snapshot import build_codebase_snapshot
from core.constants import ImplementStatus
from core.context import RuntimeContext
from core.contracts import get_design_spec_column_definitions
from core.format_sads import rows_to_csv
from core.lifecycle import (
    get_agent_provider,
    log_lifecycle_event,
    resolve_agent_artifacts_dir_for_command,
    resolve_codebase_dir_path,
    sync_local_agent_workspace,
)

from handlers.implement.config import _DEFAULT_BUDGETS
from handlers.implement.helpers import _manual_block, _sha256, _write_json
from handlers.implement.semantic_guard import (
    build_batch_path_contract,
    build_directory_tree_snapshot,
    default_verification_commands_for_batch,
    invoke_with_semantic_retry,
    validate_implement_output_semantics,
)


def _collect_spec_output(output: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate and normalize spec-keyed implement output entries.

    Required mode:
    - top-level `diff_plan[]` + per-spec `diff_refs[]`
    """
    if not isinstance(output.get("run_summary"), dict):
        raise ValueError("Implement output must include run_summary for non-manual responses")
    diff_plan_by_id = _collect_diff_plan_by_id(output)
    parsed: dict[str, dict[str, Any]] = {}
    for key, value in output.items():
        if key in {"run_summary", "diff_plan"}:
            continue
        if not re.fullmatch(r"[A-Za-z][0-9]+", str(key)):
            raise ValueError(f"Invalid implement output key: {key}")
        if not isinstance(value, dict):
            raise ValueError(f"Spec entry for {key} must be an object")
        normalized = dict(value)
        diffs = _resolve_spec_diffs(str(key), normalized, diff_plan_by_id)
        normalized["diffs"] = diffs
        parsed[str(key)] = normalized
    return parsed


def _collect_diff_plan_by_id(output: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate top-level diff_plan and return a diff_id -> diff payload map."""
    raw_plan = output.get("diff_plan", [])
    if not isinstance(raw_plan, list):
        raise ValueError("diff_plan must be an array")
    if not raw_plan:
        has_spec_payload = any(
            key not in {"run_summary", "diff_plan"} and isinstance(payload, dict)
            for key, payload in output.items()
        )
        if has_spec_payload:
            raise ValueError("diff_plan must not be empty when spec results are present")
        return {}

    collected: dict[str, dict[str, Any]] = {}
    for idx, item in enumerate(raw_plan, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"diff_plan[{idx}] must be an object")
        diff_id = str(item.get("diff_id", "")).strip()
        if not diff_id:
            raise ValueError(f"diff_plan[{idx}] missing diff_id")
        if diff_id in collected:
            raise ValueError(f"diff_plan has duplicate diff_id: {diff_id}")
        diff_path = str(item.get("diff_path", "")).strip()
        if not diff_path:
            raise ValueError(f"diff_plan[{idx}] missing diff_path")
        touched = item.get("touched_files", [])
        if not isinstance(touched, list) or not [str(p).strip() for p in touched if str(p).strip()]:
            raise ValueError(f"diff_plan[{idx}] missing touched_files")
        normalized = dict(item)
        normalized["diff_id"] = diff_id
        normalized["diff_path"] = diff_path
        normalized["touched_files"] = [str(p).strip() for p in touched if str(p).strip()]
        normalized["verification_notes"] = str(item.get("verification_notes", "")).strip()
        collected[diff_id] = normalized
    return collected


def _resolve_spec_diffs(
    spec_id: str,
    payload: dict[str, Any],
    diff_plan_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve effective per-spec diffs from diff_refs[] against top-level diff_plan[]."""
    raw_refs = payload.get("diff_refs")
    if not isinstance(raw_refs, list):
        raise ValueError(f"Spec entry for {spec_id} must include diff_refs[]")
    refs = [str(ref).strip() for ref in raw_refs if str(ref).strip()]
    if not refs:
        raise ValueError(f"Spec entry for {spec_id} diff_refs[] is empty")
    if not diff_plan_by_id:
        raise ValueError(f"Spec entry for {spec_id} uses diff_refs[] but diff_plan is missing")

    resolved: list[dict[str, Any]] = []
    for ref in refs:
        item = diff_plan_by_id.get(ref)
        if item is None:
            raise ValueError(f"Spec entry for {spec_id} references unknown diff_id: {ref}")
        resolved.append(dict(item))
    return resolved


def _collect_and_copy_patches(
    root: Path,
    paths: dict[str, Path],
    batch_id: str,
    parsed: dict[str, dict[str, Any]],
    constraints: dict[str, Any],
) -> tuple[list[str], list[str]]:
    """Validate/copy patch files and enforce forbidden-path + budget constraints."""
    forbidden = (
        [str(p).replace("\\", "/").strip("/") for p in constraints.get("forbidden_paths", []) if str(p).strip()]
        if isinstance(constraints.get("forbidden_paths", []), list)
        else []
    )
    budgets = constraints.get("budgets_applied", {}) if isinstance(constraints.get("budgets_applied", {}), dict) else {}
    max_files = int(budgets.get("max_files", _DEFAULT_BUDGETS["max_files"]))
    max_lines = int(budgets.get("max_lines_changed", _DEFAULT_BUDGETS["max_lines_changed"]))
    copied: list[str] = []
    touched_all: list[str] = []
    seen_patch_hashes: set[str] = set()
    patch_name_counts: dict[str, int] = {}
    for spec_id, payload in parsed.items():
        for diff in payload.get("diffs", []):
            if not isinstance(diff, dict):
                continue
            diff_id = str(diff.get("diff_id", "")).strip() or f"{spec_id}_diff"
            raw_path = str(diff.get("diff_path", "")).strip()
            if not raw_path:
                raise ValueError(f"Missing diff_path for {spec_id}:{diff_id}")
            source = (root / raw_path).resolve() if raw_path and not Path(raw_path).is_absolute() else Path(raw_path)
            if not source.exists() or not source.is_file():
                raise ValueError(f"Missing diff_path for {spec_id}:{diff_id}: {raw_path}")
            touched = [str(p).replace("\\", "/") for p in diff.get("touched_files", []) if str(p).strip()]
            if not touched:
                raise ValueError(f"Diff {diff_id} for {spec_id} missing touched_files")
            if len(set(touched)) > max_files:
                raise ValueError(f"Diff {diff_id} exceeds max_files budget")
            for path in touched:
                for prefix in forbidden:
                    if prefix and path.strip("/").lower().startswith(prefix.lower()):
                        raise ValueError(f"Diff {diff_id} touches forbidden path {path}")
            line_count = sum(
                1
                for line in source.read_text(encoding="utf-8", errors="replace").splitlines()
                if line.startswith("+") or line.startswith("-")
            )
            if line_count > max_lines:
                raise ValueError(f"Diff {diff_id} exceeds max_lines_changed budget")

            patch_hash = _sha256(source.read_bytes())
            # Same patch payload can be repeated across specs in a batch.
            if patch_hash in seen_patch_hashes:
                touched_all.extend(touched)
                continue
            seen_patch_hashes.add(patch_hash)

            safe_diff_id = re.sub(r"[^A-Za-z0-9._-]+", "_", diff_id).strip("._-") or f"{spec_id}_diff"
            base_name = f"{batch_id}_{safe_diff_id}"
            count = patch_name_counts.get(base_name, 0) + 1
            patch_name_counts[base_name] = count
            suffix = "" if count == 1 else f"_{count}"
            dest = paths["patches"] / f"{base_name}{suffix}.diff"
            shutil.copy2(source, dest)
            copied.append(str(dest))
            touched_all.extend(touched)
    return copied, sorted(set(touched_all))


def _git_repo_root_and_prefix(root: Path) -> tuple[Path, str]:
    """Return git top-level root and command prefix for the provided root."""
    fallback = root.resolve()

    top = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if top.returncode != 0:
        return fallback, ""
    git_root = Path(top.stdout.strip() or str(fallback)).resolve()

    pref = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-prefix"],
        capture_output=True,
        text=True,
        check=False,
    )
    prefix = pref.stdout.strip().replace("\\", "/") if pref.returncode == 0 else ""
    if prefix and not prefix.endswith("/"):
        prefix = f"{prefix}/"
    return git_root, prefix


def _normalize_patch_repo_path(path: str, git_prefix: str) -> str:
    """Normalize patch path token to a root-relative file path."""
    value = str(path).replace("\\", "/").strip()
    if value.startswith("a/") or value.startswith("b/"):
        value = value[2:]
    while value.startswith("./"):
        value = value[2:]
    value = value.lstrip("/")
    if git_prefix and value.startswith(git_prefix):
        value = value[len(git_prefix) :]
    return value.lstrip("/")


def _split_patch_sections(patch_text: str) -> tuple[str, list[str]]:
    """Split unified diff text into preamble and per-file `diff --git` sections."""
    lines = patch_text.splitlines(keepends=True)
    if not lines:
        return "", []

    preamble_parts: list[str] = []
    sections: list[str] = []
    current: list[str] = []
    in_section = False
    for line in lines:
        if line.startswith("diff --git "):
            if in_section and current:
                sections.append("".join(current))
            elif not in_section and current:
                preamble_parts = list(current)
            current = [line]
            in_section = True
            continue
        current.append(line)

    if in_section:
        if current:
            sections.append("".join(current))
        return "".join(preamble_parts), sections
    return patch_text, []


def _extract_patch_paths_for_scope(patch_text: str) -> list[str]:
    """Extract normalized file paths referenced by a unified diff payload."""
    paths: set[str] = set()
    for raw_line in patch_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("diff --git "):
            match = re.match(r"^diff --git a/(.+?) b/(.+)$", line)
            if match:
                for candidate in (match.group(1), match.group(2)):
                    normalized = _normalize_patch_repo_path(candidate, "")
                    if normalized:
                        paths.add(normalized)
            continue
        if line.startswith("--- ") or line.startswith("+++ "):
            candidate = line[4:].strip()
            if candidate == "/dev/null":
                continue
            normalized = _normalize_patch_repo_path(candidate, "")
            if normalized:
                paths.add(normalized)
    return sorted(paths)


def _path_has_prefix(path_value: str, prefix_value: str) -> bool:
    """Return True when a normalized path is equal to or under prefix_value."""
    path_norm = str(path_value).replace("\\", "/").strip().strip("/")
    prefix_norm = str(prefix_value).replace("\\", "/").strip().strip("/")
    if not prefix_norm:
        return False
    path_low = path_norm.lower()
    prefix_low = prefix_norm.lower()
    return path_low == prefix_low or path_low.startswith(f"{prefix_low}/")


def _resolve_codebase_prefix_rel(root: Path, codebase_dir: Path | None) -> str:
    """Return codebase path relative to project root, or empty when not nested."""
    if codebase_dir is None:
        return ""
    try:
        relative = codebase_dir.resolve().relative_to(root.resolve())
    except ValueError:
        return ""
    normalized = str(relative).replace("\\", "/").strip("/")
    return "" if normalized in {"", "."} else normalized


def _resolve_patch_target_path(
    root: Path,
    repo_rel_path: str,
    codebase_prefix_rel: str,
) -> Path:
    """Resolve existing-file lookup target for project/codebase-relative patch paths."""
    normalized = str(repo_rel_path).replace("\\", "/").lstrip("/")
    primary = (root / normalized).resolve()
    if primary.exists():
        return primary
    if codebase_prefix_rel and not _path_has_prefix(normalized, codebase_prefix_rel):
        secondary = (root / codebase_prefix_rel / normalized).resolve()
        if secondary.exists():
            return secondary
    return primary


def _determine_patch_apply_directory_args(
    root: Path,
    patch_file: Path,
    repo_prefix_rel: str,
    codebase_prefix_rel: str = "",
) -> tuple[list[str], str | None]:
    """Return git-apply directory args for patch scope, or conflict reason."""
    project_prefix = str(repo_prefix_rel).replace("\\", "/").strip("/")
    codebase_prefix = str(codebase_prefix_rel).replace("\\", "/").strip("/")

    try:
        patch_text = patch_file.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [], f"Failed to read patch for scope detection: {exc}"

    paths = _extract_patch_paths_for_scope(patch_text)
    if not paths:
        return [], None

    if project_prefix:
        repo_prefixed_flags = [_path_has_prefix(p, project_prefix) for p in paths]
        if all(repo_prefixed_flags):
            return [], None
        if any(repo_prefixed_flags):
            sample = ", ".join(paths[:6])
            return [], f"Mixed patch path scope (prefixed and unprefixed paths): {sample}"
        candidate_paths = paths
    else:
        candidate_paths = paths

    # Legacy/default behavior when codebase == project root.
    if not codebase_prefix:
        if project_prefix:
            return ["--directory", project_prefix], None
        return [], None

    project_relative_flags: list[bool] = []
    for path in candidate_paths:
        if _path_has_prefix(path, codebase_prefix):
            project_relative_flags.append(True)
            continue
        project_target = (root / path).resolve()
        if project_target.exists():
            project_relative_flags.append(True)
            continue
        project_relative_flags.append(False)

    if all(project_relative_flags):
        if project_prefix:
            return ["--directory", project_prefix], None
        return [], None

    if not any(project_relative_flags):
        combined_prefix = "/".join(part for part in (project_prefix, codebase_prefix) if part)
        if combined_prefix:
            return ["--directory", combined_prefix], None
        return [], None

    sample = ", ".join(candidate_paths[:6])
    return [], (
        "Mixed patch path scope (project-relative and codebase-relative paths): "
        f"{sample}"
    )


def _contains_skipped_patch_output(proc: subprocess.CompletedProcess[str]) -> bool:
    """Return True when git apply output indicates the patch was skipped/no-op."""
    output = f"{proc.stdout}\n{proc.stderr}".lower()
    return "skipped patch" in output


def _extract_new_file_desired_content(section: str) -> tuple[str | None, str | None, str | None]:
    """Return (path, desired_content, error) for new-file sections; else (None, None, None)."""
    lines = section.splitlines(keepends=True)
    if not lines:
        return None, None, None
    if not any(line.startswith("new file mode ") for line in lines):
        return None, None, None
    if any("GIT binary patch" in line for line in lines):
        return "", None, "Cannot normalize binary new-file patch for existing target."

    minus = next((line.strip() for line in lines if line.startswith("--- ")), "")
    plus = next((line.strip() for line in lines if line.startswith("+++ ")), "")
    if minus != "--- /dev/null" or not plus.startswith("+++ "):
        return "", None, "Malformed new-file patch headers; expected --- /dev/null and +++ b/<path>."

    path = plus[4:]
    if path.startswith("b/"):
        path = path[2:]
    path = path.replace("\\", "/").lstrip("/")

    desired_parts: list[str] = []
    in_hunk = False
    saw_hunk = False
    no_newline = False
    for line in lines:
        if line.startswith("@@ "):
            in_hunk = True
            saw_hunk = True
            continue
        if not in_hunk:
            continue
        if line.startswith("\\ No newline at end of file"):
            no_newline = True
            continue
        if line.startswith("+") and not line.startswith("+++"):
            desired_parts.append(line[1:])
            continue
        if line.startswith(" "):
            desired_parts.append(line[1:])
            continue
        if line.startswith("-") and not line.startswith("---"):
            return path, None, "New-file patch unexpectedly contains deletion lines."

    if not saw_hunk:
        return path, "", None

    desired = "".join(desired_parts)
    if no_newline and desired.endswith("\n"):
        desired = desired[:-1]
    return path, desired, None


def _extract_implicit_new_file_desired_content(section: str) -> tuple[str | None, str | None, str | None]:
    """Detect create-file diffs missing explicit new-file metadata.

    Accepts only hunks with zero old-side lines and added content lines.
    Returns `(path, desired_content, error)` when recognized.
    """
    lines = section.splitlines(keepends=True)
    if not lines:
        return None, None, None
    if not lines[0].startswith("diff --git "):
        return None, None, None
    if any(line.startswith("new file mode ") for line in lines):
        return None, None, None
    if any("GIT binary patch" in line for line in lines):
        return "", None, "Cannot normalize binary implicit-create patch."

    minus = next((line.strip() for line in lines if line.startswith("--- ")), "")
    plus = next((line.strip() for line in lines if line.startswith("+++ ")), "")
    if not minus.startswith("--- a/") or not plus.startswith("+++ b/"):
        return None, None, None

    minus_path = minus[6:].replace("\\", "/").lstrip("/")
    plus_path = plus[6:].replace("\\", "/").lstrip("/")
    if not plus_path or minus_path != plus_path:
        return None, None, None

    hunk_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    desired_parts: list[str] = []
    in_hunk = False
    saw_hunk = False
    no_newline = False
    for line in lines:
        if line.startswith("@@ "):
            in_hunk = True
            saw_hunk = True
            match = hunk_re.match(line)
            if not match:
                return plus_path, None, "Malformed hunk header in implicit-create patch."
            old_count = int(match.group(2) or "1")
            if old_count != 0:
                return None, None, None
            continue
        if not in_hunk:
            continue
        if line.startswith("\\ No newline at end of file"):
            no_newline = True
            continue
        if line.startswith("+") and not line.startswith("+++"):
            desired_parts.append(line[1:])
            continue
        if line.startswith(" "):
            return None, None, None
        if line.startswith("-") and not line.startswith("---"):
            return None, None, None

    if not saw_hunk:
        return None, None, None
    desired = "".join(desired_parts)
    if no_newline and desired.endswith("\n"):
        desired = desired[:-1]
    return plus_path, desired, None


def _build_modify_patch_for_existing_file(path: str, current_text: str, desired_text: str) -> str:
    """Build a modify unified diff patch from current file text to desired file text."""
    current_lines = current_text.splitlines(keepends=True)
    desired_lines = desired_text.splitlines(keepends=True)
    diff_lines = list(
        difflib.unified_diff(
            current_lines,
            desired_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="\n",
        )
    )
    if not diff_lines:
        return ""
    return f"diff --git a/{path} b/{path}\n{''.join(diff_lines)}"


def _build_create_patch_for_new_file(path: str, desired_text: str) -> str:
    """Build a canonical create-file patch payload for a missing file path."""
    desired_lines = desired_text.splitlines(keepends=True)
    diff_lines = list(
        difflib.unified_diff(
            [],
            desired_lines,
            fromfile="/dev/null",
            tofile=f"b/{path}",
            lineterm="\n",
        )
    )
    if not diff_lines:
        diff_lines = ["--- /dev/null\n", f"+++ b/{path}\n", "@@ -0,0 +1,0 @@\n"]
    return f"diff --git a/{path} b/{path}\nnew file mode 100644\n{''.join(diff_lines)}"


def _split_concatenated_hunk_markers(patch_text: str) -> tuple[str, int]:
    """Split malformed hunk lines that accidentally glue a new marker mid-line."""
    lines = patch_text.splitlines(keepends=True)
    if not lines:
        return patch_text, 0

    marker_tokens = (
        "+def ",
        "+class ",
        "+from ",
        "+import ",
        "+@",
        "+if ",
        "+for ",
        "+while ",
        "+return ",
        "+assert ",
        "+try:",
        "+except ",
        "+with ",
        "+async ",
    )
    rewritten: list[str] = []
    in_hunk = False
    split_count = 0

    for line in lines:
        if line.startswith("diff --git "):
            in_hunk = False
            rewritten.append(line)
            continue
        if line.startswith("@@ "):
            in_hunk = True
            rewritten.append(line)
            continue
        if not in_hunk:
            rewritten.append(line)
            continue
        if not (line.startswith("-") or line.startswith(" ")):
            rewritten.append(line)
            continue

        split_index: int | None = None
        for token in marker_tokens:
            pos = line.find(token, 1)
            if pos > 1 and (split_index is None or pos < split_index):
                split_index = pos
        if split_index is None:
            rewritten.append(line)
            continue

        has_newline = line.endswith("\n")
        core = line[:-1] if has_newline else line
        first = core[:split_index]
        second = core[split_index:]
        rewritten.append(f"{first}\n")
        rewritten.append(f"{second}{'\n' if has_newline else ''}")
        split_count += 1

    if split_count == 0:
        return patch_text, 0
    return "".join(rewritten), split_count


def _normalize_unified_hunk_headers(
    patch_text: str,
) -> tuple[str, list[dict[str, int | str]]]:
    """Normalize hunk line counts to match patch bodies.

    Some model-generated patches contain incorrect hunk counts (for example,
    `@@ -0,0 +1,90 @@` with only 89 added lines), which causes git-apply to fail
    with a corrupt-patch error. This pass recomputes counts deterministically.
    """
    lines = patch_text.splitlines(keepends=True)
    if not lines:
        return patch_text, []

    hunk_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*?)(\r?\n)?$")
    normalized = list(lines)
    changes: list[dict[str, int | str]] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        match = hunk_re.match(line)
        if not match:
            i += 1
            continue

        old_start = int(match.group(1))
        old_count_declared = int(match.group(2) or "1")
        new_start = int(match.group(3))
        new_count_declared = int(match.group(4) or "1")
        trailer = match.group(5) or ""
        newline = match.group(6) or ""

        j = i + 1
        old_count_actual = 0
        new_count_actual = 0
        while j < len(lines):
            body = lines[j]
            if body.startswith("@@ ") or body.startswith("diff --git "):
                break
            if body.startswith("\\ No newline at end of file"):
                j += 1
                continue
            if body.startswith("--- ") or body.startswith("+++ "):
                break
            marker = body[:1]
            if marker == " ":
                old_count_actual += 1
                new_count_actual += 1
            elif marker == "-":
                old_count_actual += 1
            elif marker == "+":
                new_count_actual += 1
            j += 1

        if old_count_actual != old_count_declared or new_count_actual != new_count_declared:
            normalized[i] = f"@@ -{old_start},{old_count_actual} +{new_start},{new_count_actual} @@{trailer}{newline}"
            changes.append(
                {
                    "hunk_index": len(changes) + 1,
                    "old_declared": old_count_declared,
                    "old_actual": old_count_actual,
                    "new_declared": new_count_declared,
                    "new_actual": new_count_actual,
                }
            )
        i = j

    if not changes:
        return patch_text, []
    return "".join(normalized), changes


def _ensure_patch_terminal_newline(patch_text: str) -> tuple[str, bool]:
    """Ensure patch text ends with newline so git apply does not read truncated hunks."""
    if not patch_text:
        return patch_text, False
    if patch_text.endswith("\n"):
        return patch_text, False
    return f"{patch_text}\n", True


def _prepare_patch_files_for_apply(
    root: Path,
    batch_id: str,
    patch_files: list[str],
    verification_dir: Path,
    *,
    codebase_prefix_rel: str = "",
) -> dict[str, Any]:
    """Normalize create-on-existing patches into safe apply-ready patch files."""
    prepared: list[str] = []
    records: list[dict[str, Any]] = []
    git_root, git_prefix = _git_repo_root_and_prefix(root)
    prepared_dir = verification_dir / "prepared_patches"
    prepared_dir.mkdir(parents=True, exist_ok=True)

    for idx, patch in enumerate(patch_files, start=1):
        patch_path = Path(patch)
        try:
            patch_text = patch_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            log = verification_dir / f"{batch_id}_patch_semantic_conflict_{idx}.log"
            log.write_text(
                f"patch={patch}\nerror=Failed to read patch file: {exc}\n",
                encoding="utf-8",
            )
            records.append(
                {
                    "kind": "patch_semantic_conflict",
                    "patch": patch,
                    "log_ref": str(log),
                }
            )
            return {"success": False, "patch_files": [], "records": records}

        patch_text, concatenated_hunk_splits = _split_concatenated_hunk_markers(patch_text)
        if concatenated_hunk_splits:
            records.append(
                {
                    "kind": "patch_hunk_line_split",
                    "patch": patch,
                    "line_count": concatenated_hunk_splits,
                }
            )
        patch_text, hunk_header_fixes = _normalize_unified_hunk_headers(patch_text)
        if hunk_header_fixes:
            records.append(
                {
                    "kind": "patch_hunk_header_normalized",
                    "patch": patch,
                    "hunk_count": len(hunk_header_fixes),
                }
            )
        patch_text, trailing_newline_added = _ensure_patch_terminal_newline(patch_text)
        if trailing_newline_added:
            records.append(
                {
                    "kind": "patch_trailing_newline_added",
                    "patch": patch,
                }
            )

        preamble, sections = _split_patch_sections(patch_text)
        if not sections:
            if concatenated_hunk_splits or hunk_header_fixes or trailing_newline_added:
                out_path = prepared_dir / f"{batch_id}_{patch_path.stem}_prepared_{idx}.diff"
                out_path.write_text(patch_text, encoding="utf-8")
                prepared.append(str(out_path))
            else:
                prepared.append(str(patch_path))
            continue

        rewritten_sections: list[str] = []
        skipped_paths: list[str] = []
        rewritten_paths: list[str] = []
        implicit_create_paths: list[str] = []
        for section in sections:
            path, desired_text, error = _extract_new_file_desired_content(section)
            if path is None:
                implicit_path, implicit_desired, implicit_error = _extract_implicit_new_file_desired_content(section)
                if implicit_path is None:
                    rewritten_sections.append(section)
                    continue
                if implicit_error:
                    log = verification_dir / f"{batch_id}_patch_semantic_conflict_{idx}.log"
                    log.write_text(
                        f"patch={patch}\npath={implicit_path}\nerror={implicit_error}\n",
                        encoding="utf-8",
                    )
                    records.append(
                        {
                            "kind": "patch_semantic_conflict",
                            "patch": patch,
                            "path": implicit_path,
                            "log_ref": str(log),
                        }
                    )
                    return {"success": False, "patch_files": [], "records": records}
                raw_path = implicit_path.replace("\\", "/").lstrip("/")
                repo_rel = _normalize_patch_repo_path(raw_path, git_prefix)
                target = _resolve_patch_target_path(root, repo_rel, codebase_prefix_rel)
                if target.exists() and target.is_file():
                    current_text = target.read_text(encoding="utf-8", errors="replace")
                    modify_patch = _build_modify_patch_for_existing_file(
                        raw_path,
                        current_text,
                        implicit_desired or "",
                    )
                    if not modify_patch:
                        skipped_paths.append(raw_path)
                        continue
                    if not modify_patch.endswith("\n"):
                        modify_patch = f"{modify_patch}\n"
                    rewritten_paths.append(raw_path)
                    rewritten_sections.append(modify_patch)
                    continue
                create_patch = _build_create_patch_for_new_file(raw_path, implicit_desired or "")
                if not create_patch.endswith("\n"):
                    create_patch = f"{create_patch}\n"
                implicit_create_paths.append(raw_path)
                rewritten_sections.append(create_patch)
                continue
            if error:
                log = verification_dir / f"{batch_id}_patch_semantic_conflict_{idx}.log"
                log.write_text(
                    f"patch={patch}\npath={path}\nerror={error}\n",
                    encoding="utf-8",
                )
                records.append(
                    {
                        "kind": "patch_semantic_conflict",
                        "patch": patch,
                        "path": path,
                        "log_ref": str(log),
                    }
                )
                return {"success": False, "patch_files": [], "records": records}

            raw_path = path.replace("\\", "/").lstrip("/")
            repo_rel = _normalize_patch_repo_path(raw_path, git_prefix)
            target = _resolve_patch_target_path(root, repo_rel, codebase_prefix_rel)
            if not target.exists() or not target.is_file():
                # Truly new target file: keep create patch as-is.
                rewritten_sections.append(section)
                continue

            current_bytes = target.read_bytes()
            desired_bytes = (desired_text or "").encode("utf-8")
            if _sha256(current_bytes) == _sha256(desired_bytes):
                skipped_paths.append(raw_path)
                continue

            current_text = target.read_text(encoding="utf-8", errors="replace")
            modify_patch = _build_modify_patch_for_existing_file(raw_path, current_text, desired_text or "")
            if not modify_patch:
                skipped_paths.append(raw_path)
                continue
            rewritten_paths.append(raw_path)
            if not modify_patch.endswith("\n"):
                modify_patch = f"{modify_patch}\n"
            rewritten_sections.append(modify_patch)

        if skipped_paths:
            records.append(
                {
                    "kind": "patch_already_applied_skip",
                    "patch": patch,
                    "paths": sorted(set(skipped_paths)),
                }
            )
        if rewritten_paths:
            records.append(
                {
                    "kind": "patch_create_to_modify_rewrite",
                    "patch": patch,
                    "paths": sorted(set(rewritten_paths)),
                }
            )
        if implicit_create_paths:
            records.append(
                {
                    "kind": "patch_implicit_create_rewrite",
                    "patch": patch,
                    "paths": sorted(set(implicit_create_paths)),
                }
            )

        if not rewritten_sections:
            # Entire patch was already applied.
            continue

        if (
            rewritten_paths
            or skipped_paths
            or implicit_create_paths
            or concatenated_hunk_splits
            or hunk_header_fixes
            or trailing_newline_added
        ):
            out_path = prepared_dir / f"{batch_id}_{patch_path.stem}_prepared_{idx}.diff"
            out_path.write_text(preamble + "".join(rewritten_sections), encoding="utf-8")
            prepared.append(str(out_path))
        else:
            prepared.append(str(patch_path))

    return {"success": True, "patch_files": prepared, "records": records, "git_root": str(git_root)}


def _apply_and_verify(
    root: Path,
    batch_id: str,
    patch_files: list[str],
    verification_commands: Any,
    verification_dir: Path,
    *,
    codebase_dir: Path | None = None,
) -> dict[str, Any]:
    """Apply patch files and run verification commands in a detached git worktree."""
    records: list[dict[str, Any]] = []
    if not patch_files:
        return {"success": True, "records": records, "applied_patch_files": []}
    repo_root, repo_prefix = _git_repo_root_and_prefix(root)
    repo_prefix_rel = repo_prefix.strip("/")
    codebase_prefix_rel = _resolve_codebase_prefix_rel(root, codebase_dir)

    commands = (
        [str(c) for c in verification_commands if str(c).strip()]
        if isinstance(verification_commands, list)
        else []
    )

    def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            check=False,
        )

    def record_failure(kind: str, command: list[str], proc: subprocess.CompletedProcess[str]) -> None:
        idx = len(records) + 1
        log = verification_dir / f"{batch_id}_{kind}_{idx}.log"
        rendered = " ".join(shlex.quote(part) for part in command)
        log.write_text(
            f"$ {rendered}\n\nSTDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}\n",
            encoding="utf-8",
        )
        records.append(
            {
                "kind": kind,
                "command": rendered,
                "exit_code": proc.returncode,
                "log_ref": str(log),
            }
        )

    prepared = _prepare_patch_files_for_apply(
        root,
        batch_id,
        patch_files,
        verification_dir,
        codebase_prefix_rel=codebase_prefix_rel,
    )
    records.extend(prepared.get("records", []))
    if not prepared.get("success"):
        return {"success": False, "records": records, "applied_patch_files": []}

    effective_patches = [str(p) for p in prepared.get("patch_files", []) if str(p).strip()]
    if not effective_patches:
        return {"success": True, "records": records, "applied_patch_files": []}

    worktree = verification_dir / f"worktree_{batch_id}"
    add_cmd = ["git", "-C", str(repo_root), "worktree", "add", "--detach", str(worktree), "HEAD"]
    added = run(add_cmd)
    if added.returncode != 0:
        record_failure("worktree_add", add_cmd, added)
        return {"success": False, "records": records, "applied_patch_files": []}
    try:
        worktree_project_root = (
            worktree / Path(repo_prefix_rel)
            if repo_prefix_rel
            else worktree
        )
        if not worktree_project_root.is_dir():
            missing_proc = subprocess.CompletedProcess(
                args=["worktree_project_root_missing"],
                returncode=1,
                stdout="",
                stderr=f"Worktree project root not found: {worktree_project_root}",
            )
            record_failure(
                "worktree_project_root_missing",
                ["test", "-d", str(worktree_project_root)],
                missing_proc,
            )
            return {"success": False, "records": records, "applied_patch_files": []}

        try:
            sync_local_agent_workspace(root.resolve(), worktree_project_root.resolve())
        except Exception as exc:  # pragma: no cover - defensive path
            idx = len(records) + 1
            log = verification_dir / f"{batch_id}_worktree_sync_{idx}.log"
            log.write_text(
                f"source={root.resolve()}\nworkspace={worktree_project_root.resolve()}\nerror={exc}\n",
                encoding="utf-8",
            )
            records.append(
                {
                    "kind": "worktree_sync_failed",
                    "log_ref": str(log),
                }
            )
            return {"success": False, "records": records, "applied_patch_files": []}

        for patch in effective_patches:
            directory_args, scope_error = _determine_patch_apply_directory_args(
                root,
                Path(patch),
                repo_prefix_rel,
                codebase_prefix_rel,
            )
            if scope_error:
                scope_proc = subprocess.CompletedProcess(
                    args=["patch_scope_conflict"],
                    returncode=1,
                    stdout="",
                    stderr=scope_error,
                )
                record_failure(
                    "patch_scope_conflict",
                    ["git", "apply", patch],
                    scope_proc,
                )
                return {"success": False, "records": records, "applied_patch_files": []}

            check_cmd = ["git", "-C", str(worktree), "apply", "--check", *directory_args, patch]
            checked = run(check_cmd)
            if checked.returncode != 0:
                record_failure("patch_check_worktree", check_cmd, checked)
                return {"success": False, "records": records, "applied_patch_files": []}
            if _contains_skipped_patch_output(checked):
                record_failure("patch_check_worktree_noop", check_cmd, checked)
                return {"success": False, "records": records, "applied_patch_files": []}

            apply_cmd = ["git", "-C", str(worktree), "apply", *directory_args, patch]
            applied = run(apply_cmd)
            if applied.returncode != 0:
                record_failure("patch_apply_worktree", apply_cmd, applied)
                return {"success": False, "records": records, "applied_patch_files": []}
            if _contains_skipped_patch_output(applied):
                record_failure("patch_apply_worktree_noop", apply_cmd, applied)
                return {"success": False, "records": records, "applied_patch_files": []}

        for idx, command in enumerate(commands, start=1):
            argv = shlex.split(command) if isinstance(command, str) else list(command)
            proc = subprocess.run(
                argv,
                cwd=str(worktree_project_root),
                capture_output=True,
                text=True,
                shell=False,
                check=False,
            )
            log = verification_dir / f"{batch_id}_verify_{idx}.log"
            log.write_text(
                f"$ {command}\n\nSTDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}\n",
                encoding="utf-8",
            )
            records.append({"command": command, "exit_code": proc.returncode, "log_ref": str(log)})
            if proc.returncode != 0:
                return {"success": False, "records": records, "applied_patch_files": []}

        patch_apply_args: dict[str, list[str]] = {}
        for patch in effective_patches:
            directory_args, scope_error = _determine_patch_apply_directory_args(
                root,
                Path(patch),
                repo_prefix_rel,
                codebase_prefix_rel,
            )
            if scope_error:
                scope_proc = subprocess.CompletedProcess(
                    args=["patch_scope_conflict"],
                    returncode=1,
                    stdout="",
                    stderr=scope_error,
                )
                record_failure(
                    "patch_scope_conflict",
                    ["git", "apply", patch],
                    scope_proc,
                )
                return {"success": False, "records": records, "applied_patch_files": []}
            patch_apply_args[patch] = directory_args
            pre_check_cmd = ["git", "-C", str(repo_root), "apply", "--check", *directory_args, patch]
            pre_check = run(pre_check_cmd)
            if pre_check.returncode != 0:
                record_failure("patch_check_root", pre_check_cmd, pre_check)
                return {"success": False, "records": records, "applied_patch_files": []}
            if _contains_skipped_patch_output(pre_check):
                record_failure("patch_check_root_noop", pre_check_cmd, pre_check)
                return {"success": False, "records": records, "applied_patch_files": []}

        applied_so_far: list[tuple[str, list[str]]] = []
        for patch in effective_patches:
            directory_args = patch_apply_args.get(patch, [])
            main_apply_cmd = ["git", "-C", str(repo_root), "apply", *directory_args, patch]
            main_apply = run(main_apply_cmd)
            if main_apply.returncode != 0:
                record_failure("patch_apply_root", main_apply_cmd, main_apply)
                for applied_patch, applied_directory_args in reversed(applied_so_far):
                    run(["git", "-C", str(repo_root), "apply", "--reverse", *applied_directory_args, applied_patch])
                return {"success": False, "records": records, "applied_patch_files": []}
            if _contains_skipped_patch_output(main_apply):
                record_failure("patch_apply_root_noop", main_apply_cmd, main_apply)
                for applied_patch, applied_directory_args in reversed(applied_so_far):
                    run(["git", "-C", str(repo_root), "apply", "--reverse", *applied_directory_args, applied_patch])
                return {"success": False, "records": records, "applied_patch_files": []}
            applied_so_far.append((patch, directory_args))

        return {
            "success": True,
            "records": records,
            "applied_patch_files": list(effective_patches),
        }
    finally:
        run(["git", "-C", str(repo_root), "worktree", "remove", "--force", str(worktree)])


def _hashes(root: Path, relative_paths: list[str]) -> list[dict[str, str]]:
    """Return SHA-256 hashes for files that currently exist under project root."""
    hashed: list[dict[str, str]] = []
    for rel in relative_paths:
        path = (root / rel).resolve()
        if path.exists() and path.is_file():
            hashed.append({"path": rel, "sha256": _sha256(path.read_bytes())})
    return hashed


def _build_runtime_file_facts(root: Path, brief: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build deterministic file-state facts for the current batch context."""
    planned_paths: set[str] = set()
    for anchor in brief.get("planned_anchors", []) if isinstance(brief.get("planned_anchors", []), list) else []:
        if not isinstance(anchor, dict):
            continue
        file_path = str(anchor.get("planned_file_path", "")).replace("\\", "/").strip().lstrip("/")
        if file_path:
            planned_paths.add(file_path)
    for contract in brief.get("shared_contracts", []) if isinstance(brief.get("shared_contracts", []), list) else []:
        if not isinstance(contract, dict):
            continue
        file_path = str(contract.get("planned_file_path", "")).replace("\\", "/").strip().lstrip("/")
        if file_path:
            planned_paths.add(file_path)

    facts: dict[str, dict[str, Any]] = {}
    for rel in sorted(planned_paths):
        target = (root / rel).resolve()
        exists = target.exists()
        is_file = target.is_file()
        sha256 = _sha256(target.read_bytes()) if is_file else ""
        facts[rel] = {
            "exists": bool(exists),
            "is_file": bool(is_file),
            "sha256": sha256,
        }
    return facts


def _execute_batch(
    config: dict[str, Any],
    ctx: RuntimeContext,
    impl: dict[str, Any],
    schema_path: Path,
    root: Path,
    context_text: str,
    paths: dict[str, Path],
    design_headers: list[str],
    brief: dict[str, Any],
    *,
    completed_stages: list[str],
    local_workspace_override: Path | None = None,
) -> dict[str, Any]:
    """Execute implementer for one batch, apply/verify patches, and append trace records."""
    codebase = resolve_codebase_dir_path(config, root, ctx)
    provider = get_agent_provider(config)
    codebase_dir_for_prompt = codebase
    if provider == "local" and local_workspace_override is not None:
        sync_local_agent_workspace(codebase, local_workspace_override)
        codebase_dir_for_prompt = local_workspace_override.resolve()
        log_lifecycle_event(
            "lifecycle_local_shared_workspace_resynced",
            command="implement",
            run_id=ctx.run_id,
            extra={
                "source_dir": str(codebase),
                "workspace_dir": str(codebase_dir_for_prompt),
                "phase": "batch_execute",
                "batch_id": brief.get("batch_id"),
            },
        )
    codebase_content = (
        build_codebase_snapshot(codebase, config, command="implement")
        if provider == "api"
        else ""
    )
    runtime_file_facts = _build_runtime_file_facts(root, brief)
    spec_rows = brief.get("spec_rows", []) if isinstance(brief.get("spec_rows", []), list) else []
    csv_rows = [{h: (row.get(h, "") if isinstance(row, dict) else "") for h in design_headers} for row in spec_rows]
    specs_csv = rows_to_csv(design_headers, csv_rows)

    artifacts = resolve_agent_artifacts_dir_for_command(config, root, "implement", ctx.run_id)
    artifacts.mkdir(parents=True, exist_ok=True)
    batch_path_contract = build_batch_path_contract(
        brief,
        impl.get("type_placement_path", ""),
        impl.get("forbidden_paths", []),
    )

    template_vars: dict[str, Any] = {
        "output_schema_file": str(schema_path),
        "project_context": context_text,
        "selected_specs_csv": specs_csv,
        "design_spec_column_definitions": get_design_spec_column_definitions(),
        "indexed_mappings_csv": specs_csv,
        "codebase_dir": str(codebase_dir_for_prompt),
        "codebase_content": codebase_content,
        "runtime_file_facts_json": json.dumps(runtime_file_facts, indent=2),
        "manual_resolution_file": str(paths["manual"]),
        "run_summary_file": str(paths["run"] / "summary.json"),
        "agent_artifacts_dir": str(artifacts),
        "batch_brief_json": json.dumps(brief, indent=2),
        "allowed_paths_json": json.dumps(batch_path_contract, indent=2),
        "directory_tree_snapshot": build_directory_tree_snapshot(codebase_dir_for_prompt),
        "forbidden_path_patterns_json": json.dumps(
            batch_path_contract.get("forbidden_path_prefixes", []),
            indent=2,
        ),
        "semantic_retry_context": "",
    }
    template_vars["resolved_decisions"] = getattr(ctx, "resolved_decisions", None) or ""

    def _prepare_semantic_attempt(attempt: int, render_vars: dict[str, Any]) -> None:
        if attempt <= 1:
            return
        if provider == "local" and local_workspace_override is not None:
            sync_local_agent_workspace(codebase, local_workspace_override)
            render_vars["directory_tree_snapshot"] = build_directory_tree_snapshot(
                local_workspace_override.resolve()
            )
            render_vars["runtime_file_facts_json"] = json.dumps(
                _build_runtime_file_facts(root, brief),
                indent=2,
            )
            log_lifecycle_event(
                "lifecycle_local_shared_workspace_resynced",
                command="implement",
                run_id=ctx.run_id,
                extra={
                    "source_dir": str(codebase),
                    "workspace_dir": str(local_workspace_override.resolve()),
                    "phase": "batch_execute_semantic_retry",
                    "batch_id": brief.get("batch_id"),
                    "attempt": attempt,
                },
            )

    output = invoke_with_semantic_retry(
        prompt_name=impl["prompt_name"],
        template_vars=template_vars,
        schema_path=schema_path,
        config=config,
        ctx=ctx,
        semantic_validator=lambda result: validate_implement_output_semantics(
            result,
            batch_path_contract,
            root,
            codebase_prefix_rel=(
                codebase.resolve().relative_to(root.resolve()).as_posix()
                if codebase.resolve() != root.resolve()
                else ""
            ),
        ),
        semantic_validation_retries=impl.get("semantic_validation_retries", 2),
        validation_label=f"implement_{brief['batch_id']}",
        local_workspace_override=local_workspace_override,
        pre_attempt_hook=_prepare_semantic_attempt,
    )
    _write_json(paths["agent_outputs"] / f"implement_{brief['batch_id']}.json", output)
    if _manual_block(
        output,
        paths["manual"],
        f"implement_{brief['batch_id']}",
        run_dir=paths["run"],
        command="implement",
        run_id=ctx.run_id,
        completed_stages=completed_stages,
    ):
        return {"status": ImplementStatus.BLOCKED, "blocking_items": len(output.get("manual_resolution_items", []))}

    parsed = _collect_spec_output(output)
    patch_paths, touched_files = _collect_and_copy_patches(
        root,
        paths,
        brief["batch_id"],
        parsed,
        brief.get("constraints", {}),
    )
    before = _hashes(root, touched_files)
    configured_verification_commands = brief.get("constraints", {}).get("verification_commands", [])
    effective_verification_commands = default_verification_commands_for_batch(
        root,
        brief,
        configured_verification_commands,
    )
    if not isinstance(configured_verification_commands, list) or not [
        str(cmd).strip() for cmd in configured_verification_commands if str(cmd).strip()
    ]:
        log_lifecycle_event(
            "lifecycle_verification_fallback_applied",
            command="implement",
            run_id=ctx.run_id,
            extra={
                "batch_id": brief.get("batch_id"),
                "commands": json.dumps(effective_verification_commands),
            },
        )
    verify = _apply_and_verify(
        root,
        brief["batch_id"],
        patch_paths,
        effective_verification_commands,
        paths["verification"],
        codebase_dir=codebase,
    )
    if not verify["success"]:
        return {"status": ImplementStatus.FAILED, "reason": f"verification_failed_{brief['batch_id']}"}

    applied_patch_paths = [str(p) for p in verify.get("applied_patch_files", [])]
    after = _hashes(root, touched_files)
    trace = {
        "run_id": ctx.run_id,
        "batch_id": brief["batch_id"],
        "spec_ids": sorted(parsed.keys()),
        "diff_sha256": _sha256(
            "\n".join(Path(p).read_text(encoding="utf-8") for p in applied_patch_paths).encode("utf-8")
        )
        if applied_patch_paths
        else "",
        "before_hashes": before,
        "after_hashes": after,
        "verification": verify["records"],
        "artifacts": [{"kind": "patch", "ref": f"patches/{Path(p).name}"} for p in patch_paths],
    }
    with (paths["trace"] / "trace.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(trace, separators=(",", ":")) + "\n")
    return {"status": ImplementStatus.COMPLETED, "spec_outputs": parsed}
