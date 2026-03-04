"""Preflight validation: paths, writability, CSV contracts, PROJECT_CONTEXT per PROJECT_CONTEXT.

All pre-run checks are aggregated here. Errors are collected and reported together
before the program exits.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Iterable

from core.contracts import (
    get_design_spec_required_columns,
    get_issue_tracking_required_columns,
    get_project_context_required_sections,
)
from core.errors import SafetyPreconditionError
from core.lifecycle import (
    _get_effective_inputs,
    _get_effective_outputs,
    resolve_codebase_dir_path,
    resolve_format_source_path,
    resolve_input_path,
    resolve_project_context_path,
)
from core.logger import _resolve_log_dir


_INPUT_KEY_GROUPS = (
    ("design_spec_path", "design_spec"),
    ("issue_tracking_path", "issue_tracking"),
)
_PLAN_INPUT_KEYS = ("srs_path",)
_REVIEW_INPUT_KEYS = ("design_spec_path",)


def validate_command_preconditions(command: str, config: dict[str, Any], ctx: Any) -> None:
    """Run all preflight checks for the command. Collect and report all errors before exiting.

    Preflight steps (in order):
    1. Project root exists and is a directory
    2. Log dir, output dirs, state dir are writable and under project root
    3. No-overwrite outputs: refuse to overwrite existing files
    4. Input file existence: required input files exist (when defined)
    5. CSV contract validation: required CSV columns for design_spec and issue_tracking
    6. PROJECT_CONTEXT contract: Purpose, Overview, Workflow sections (plan, map, implement)
    """
    errors: list[str] = []
    project_root = _run_step_1_project_root(ctx, errors)
    if project_root is None:
        _raise_if_errors(errors, command)
        return  # unreachable

    _run_step_2_dirs_writable(config, project_root, command, errors)
    _run_step_3_no_overwrite(config, project_root, command, errors)
    _run_step_4_input_files(command, config, project_root, ctx, errors)
    _run_step_5_csv_contracts(command, config, project_root, ctx, errors)
    _run_step_6_project_context_contract(command, config, project_root, ctx, errors)

    _run_step_7_unsupported_command(command, errors)

    _raise_if_errors(errors, command)


# ---------------------------------------------------------------------------
# Step 1: Project root exists and is a directory
# ---------------------------------------------------------------------------
def _run_step_1_project_root(ctx: Any, errors: list[str]) -> Path | None:
    """Step 1: Validate project root. Returns Path or None if invalid."""
    try:
        project_root = _resolve_project_root(ctx)
    except SafetyPreconditionError:
        errors.append("Runtime context missing a valid 'project_root'.")
        return None
    if not project_root.exists():
        errors.append(f"Project root does not exist: {project_root}")
        return None
    if not project_root.is_dir():
        errors.append(f"Project root is not a directory: {project_root}")
        return None
    return project_root


# ---------------------------------------------------------------------------
# Step 2: Log dir, output dirs, state dir writable and under project root
# ---------------------------------------------------------------------------
def _run_step_2_dirs_writable(
    config: dict[str, Any],
    project_root: Path,
    command: str,
    errors: list[str],
) -> None:
    """Step 2: Validate log dir, output dirs, state dir."""
    log_dir = _resolve_log_dir(project_root, config)
    if not _is_under_root(project_root, log_dir):
        errors.append(
            f"Unsafe log_dir: {log_dir} resolves outside project root ({project_root})."
        )
    else:
        _ensure_directory_writable(log_dir, "log_dir", errors)

    checked_dirs: set[Path] = set()
    for output_key, output_path, _ in _iter_output_specs(config, command):
        resolved_output = _resolve_path(project_root, output_path)
        if not _is_under_root(project_root, resolved_output):
            errors.append(
                f"Unsafe output path: outputs.{output_key}.path={output_path!r} "
                f"resolves outside project root ({project_root})."
            )
            continue
        target_dir = _target_directory_for_output(output_key, resolved_output)
        if target_dir not in checked_dirs:
            _ensure_directory_writable(target_dir, f"outputs.{output_key}", errors)
            checked_dirs.add(target_dir)

    state_dir = _resolve_state_dir(config, project_root)
    if not _is_under_root(project_root, state_dir):
        errors.append(
            f"Unsafe state_dir: {state_dir} resolves outside project root ({project_root})."
        )
    else:
        _ensure_directory_writable(state_dir, "state_dir", errors)


# ---------------------------------------------------------------------------
# Step 3: No-overwrite outputs
# ---------------------------------------------------------------------------
def _run_step_3_no_overwrite(
    config: dict[str, Any],
    project_root: Path,
    command: str,
    errors: list[str],
) -> None:
    """Step 3: Refuse to overwrite existing files when no_overwrite is enabled."""
    for output_key, output_path, no_overwrite in _iter_output_specs(config, command):
        if no_overwrite and not output_key.endswith("_dir"):
            resolved_output = _resolve_path(project_root, output_path)
            if resolved_output.exists():
                errors.append(
                    f"Refusing to overwrite existing output file '{resolved_output}' "
                    f"because no-overwrite is enabled (outputs.{output_key}.no_overwrite=true)."
                )


# ---------------------------------------------------------------------------
# Step 4: Input file existence
# ---------------------------------------------------------------------------
def _run_step_4_input_files(
    command: str,
    config: dict[str, Any],
    project_root: Path,
    ctx: Any,
    errors: list[str],
) -> None:
    """Step 4: Validate required input files exist when defined."""
    try:
        inputs_map = _build_inputs_map(config, ctx, project_root, command)
    except ValueError as exc:
        errors.append(str(exc))
        return

    if command == "plan":
        _validate_input_file_if_defined(
            inputs_map, keys=_PLAN_INPUT_KEYS, project_root=project_root, command=command, errors=errors
        )
        return
    if command == "format":
        _validate_input_file_if_defined(
            inputs_map,
            keys=("design_spec_path",),
            project_root=project_root,
            command=command,
            errors=errors,
            config=config,
            check_format_extension=True,
        )
        return
    if command == "review":
        _validate_input_file_if_defined(
            inputs_map, keys=_REVIEW_INPUT_KEYS, project_root=project_root, command=command, errors=errors
        )
        return
    if command in {"map", "implement", "resolve_plan"}:
        for keys in _INPUT_KEY_GROUPS:
            _validate_input_file_if_defined(
                inputs_map, keys=keys, project_root=project_root, command=command, errors=errors
            )


# ---------------------------------------------------------------------------
# Step 5: CSV contract validation
# ---------------------------------------------------------------------------
def _run_step_5_csv_contracts(
    command: str,
    config: dict[str, Any],
    project_root: Path,
    ctx: Any,
    errors: list[str],
) -> None:
    """Step 5: Validate required CSV columns per contract (docs/csv_contracts.md)."""
    try:
        inputs_map = _build_inputs_map(config, ctx, project_root, command)
    except ValueError as exc:
        errors.append(str(exc))
        return

    try:
        design_required = get_design_spec_required_columns()
        issue_required = get_issue_tracking_required_columns()
    except (FileNotFoundError, ValueError) as exc:
        errors.append(str(exc))
        return

    if command in {"map", "implement", "resolve_plan"}:
        design_path = _resolve_input_path_from_map(inputs_map, project_root, "design_spec_path")
        if design_path is not None and design_path.exists() and design_path.is_file():
            _validate_csv_columns(
                design_path,
                design_required,
                "Design Spec (inputs.design_spec_path)",
                errors,
            )

    if command == "resolve_plan":
        issue_path = _resolve_input_path_from_map(inputs_map, project_root, "issue_tracking_path")
        if issue_path is not None and issue_path.exists() and issue_path.is_file():
            _validate_csv_columns(
                issue_path,
                issue_required,
                "Implementation Issue Tracker (inputs.issue_tracking_path)",
                errors,
            )


# ---------------------------------------------------------------------------
# Step 6: PROJECT_CONTEXT.md contract
# ---------------------------------------------------------------------------
def _run_step_6_project_context_contract(
    command: str,
    config: dict[str, Any],
    project_root: Path,
    ctx: Any,
    errors: list[str],
) -> None:
    """Step 6: Validate PROJECT_CONTEXT.md has Purpose, Overview, Workflow sections."""
    if command not in {"plan", "map", "implement"}:
        return

    project_root_path = Path(project_root) if isinstance(project_root, str) else project_root
    codebase_dir_path = resolve_codebase_dir_path(config, project_root_path, ctx)
    context_path = resolve_project_context_path(config, project_root_path, ctx, codebase_dir_path)

    if context_path is None:
        inputs = _get_effective_inputs(config, command)
        filename = inputs.get("project_context_filename", "PROJECT_CONTEXT.md")
        if isinstance(filename, str):
            errors.append(
                f"Project context file not found. Provide via --project-context PATH or place "
                f"{filename} in project root ({project_root_path})."
            )
        return

    content = context_path.read_text(encoding="utf-8")

    try:
        required_sections = get_project_context_required_sections()
    except (FileNotFoundError, ValueError) as exc:
        errors.append(str(exc))
        return

    section_errors = _validate_project_context_sections(
        content, str(context_path), required_sections
    )
    errors.extend(section_errors)


def _validate_project_context_sections(
    content: str, file_label: str, required_sections: tuple[str, ...]
) -> list[str]:
    """Validate PROJECT_CONTEXT has required sections with non-empty content."""
    errors: list[str] = []
    sections = _parse_markdown_sections(content)

    for required in required_sections:
        matched = False
        for heading, body in sections:
            if required in heading.lower():
                if not body or not body.strip():
                    errors.append(
                        f"{file_label}: Section '{heading}' must have non-empty content "
                        f"(contract requires: {', '.join(required_sections)})."
                    )
                matched = True
                break
        if not matched:
            errors.append(
                f"{file_label}: Missing required section containing '{required}' "
                f"(contract requires: {', '.join(required_sections)})."
            )

    return errors


def _parse_markdown_sections(content: str) -> list[tuple[str, str]]:
    """Parse markdown into (heading, body) pairs. Headings are ### or ##."""
    sections: list[tuple[str, str]] = []
    pattern = re.compile(r"^#{2,3}\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(content))
    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        sections.append((heading, body))
    return sections


def _validate_csv_columns(
    path: Path,
    required_columns: tuple[str, ...],
    label: str,
    errors: list[str],
) -> None:
    """Validate CSV has required columns. Case-insensitive header match."""
    try:
        from core.format_sads import load_sads_csv_or_xlsx
    except ImportError:
        errors.append(f"{label}: Cannot load file for validation (format_sads not available).")
        return

    try:
        headers, _ = load_sads_csv_or_xlsx(path)
    except Exception as exc:
        errors.append(f"{label}: Failed to read file: {exc}")
        return

    header_lower = {h.strip().lower(): h for h in headers if h}
    missing: list[str] = []
    for col in required_columns:
        if col.lower() not in header_lower:
            missing.append(col)

    if missing:
        errors.append(
            f"{label} ({path}): Missing required columns: {', '.join(missing)}. "
            f"Contract: docs/csv_contracts.md"
        )


# ---------------------------------------------------------------------------
# Step 7: Unsupported command
# ---------------------------------------------------------------------------
def _run_step_7_unsupported_command(command: str, errors: list[str]) -> None:
    """Step 7: Reject unsupported commands."""
    supported = {"plan", "format", "review", "map", "implement", "resolve_plan"}
    if command not in supported:
        errors.append(f"Unsupported command for safety validation: {command}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _raise_if_errors(errors: list[str], command: str) -> None:
    """If any errors, format and raise SafetyPreconditionError."""
    if not errors:
        return
    lines = [
        f"Preflight validation failed for command '{command}'. Fix the following and retry:",
        "",
    ]
    for i, e in enumerate(errors, 1):
        lines.append(f"  {i}. {e}")
    lines.append("")
    lines.append("See docs/csv_contracts.md for CSV contracts and docs/project_context_contracts.md for PROJECT_CONTEXT.")
    raise SafetyPreconditionError("\n".join(lines))


def _resolve_project_root(ctx: Any) -> Path:
    """Resolve project root from context."""
    project_root: Any = getattr(ctx, "project_root", None)
    if project_root is None and isinstance(ctx, dict):
        project_root = ctx.get("project_root")
    if isinstance(project_root, Path):
        return project_root.resolve()
    if isinstance(project_root, str) and project_root.strip():
        return Path(project_root).resolve()
    raise SafetyPreconditionError("Runtime context missing a valid 'project_root'.")


def _build_inputs_map(
    config: dict[str, Any],
    ctx: Any,
    project_root: Path,
    command: str,
) -> dict[str, str]:
    """Build merged inputs from config and overrides.

    For design_spec_path: uses resolve_input_path/resolve_format_source_path
    (CLI > commands.<cmd>.inputs > project.state). For format, uses format source resolution.
    Uses merged inputs (top-level + commands.<cmd>.inputs).
    """
    inputs = _get_effective_inputs(config, command)
    inputs_map = dict(inputs) if isinstance(inputs, dict) else {}
    overrides = getattr(ctx, "input_overrides", None) or {}
    inputs_map.update({k: v for k, v in overrides.items() if isinstance(v, str) and v.strip()})
    if command == "format":
        src = resolve_format_source_path(config, project_root, overrides)
        inputs_map["design_spec_path"] = str(src)
    elif command in ("map", "implement", "review", "resolve_plan"):
        design_path = resolve_input_path(
            config, project_root, "design_spec_path",
            overrides=overrides, command=command
        )
        if design_path is not None:
            inputs_map["design_spec_path"] = str(design_path)
    return inputs_map


def _resolve_input_path_from_map(
    inputs_map: dict[str, Any], project_root: Path, key: str
) -> Path | None:
    """Resolve input path from inputs map."""
    value = inputs_map.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate.resolve()
    return (project_root / value).resolve()


def _resolve_path(project_root: Path, path_value: str) -> Path:
    """Resolve path relative to project root."""
    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate.resolve()
    return (project_root / candidate).resolve()


def _iter_output_specs(
    config: dict[str, Any], command: str | None = None
) -> Iterable[tuple[str, str, bool]]:
    """Iterate output specs (key, path, no_overwrite).

    Includes merged outputs (top-level + commands.<cmd>.outputs).
    When command is format, includes commands.format.outputs.design_spec_path.
    """
    outputs = _get_effective_outputs(config, command)
    seen: set[str] = set()
    for key, value in outputs.items():
        if not isinstance(value, dict):
            continue
        path_value = value.get("path")
        no_overwrite = value.get("no_overwrite")
        if (
            isinstance(path_value, str)
            and path_value.strip()
            and isinstance(no_overwrite, bool)
            and key not in seen
        ):
            seen.add(key)
            yield key, path_value, no_overwrite


def _target_directory_for_output(output_key: str, resolved_output: Path) -> Path:
    """Return target directory for output path."""
    if output_key.endswith("_dir"):
        return resolved_output
    if resolved_output.exists() and resolved_output.is_dir():
        return resolved_output
    return resolved_output.parent


def _ensure_directory_writable(directory: Path, label: str, errors: list[str]) -> None:
    """Ensure directory exists and is writable. Append to errors on failure."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        errors.append(f"Unable to create directory for {label}: {directory} ({exc})")
        return

    if not directory.is_dir():
        errors.append(f"Path for {label} is not a directory: {directory}")
        return

    probe = directory / f".safety_write_probe_{uuid.uuid4().hex}.tmp"
    try:
        probe.write_text("probe", encoding="utf-8")
    except OSError as exc:
        errors.append(f"Directory for {label} is not writable: {directory} ({exc})")
    finally:
        try:
            if probe.exists():
                probe.unlink()
        except OSError:
            pass


def _resolve_state_dir(config: dict[str, Any], project_root: Path) -> Path:
    """Resolve state directory from config."""
    state_dir_value: str | None = None
    root_state = config.get("state_dir")
    if isinstance(root_state, str) and root_state.strip():
        state_dir_value = root_state
    outputs = config.get("outputs")
    if state_dir_value is None and isinstance(outputs, dict):
        outputs_state = outputs.get("state_dir")
        if isinstance(outputs_state, dict):
            outputs_state_path = outputs_state.get("path")
            if isinstance(outputs_state_path, str) and outputs_state_path.strip():
                state_dir_value = outputs_state_path
    if state_dir_value is None:
        from core.pika_config import get_pika_config

        state_dir = get_pika_config().get("default_outputs", {}).get(
            "state_dir", "out/state"
        )
        return (project_root / state_dir).resolve()
    return _resolve_path(project_root, state_dir_value)


def _get_allowed_extensions(
    config: dict[str, Any], command: str = "format"
) -> tuple[str, ...]:
    """Return allowed extensions for format input from config. Default (.csv, .xlsx)."""
    inputs = _get_effective_inputs(config, command)
    if not isinstance(inputs, dict):
        return (".csv", ".xlsx")
    ext_list = inputs.get("allowed_extensions")
    if not isinstance(ext_list, list) or len(ext_list) < 2:
        return (".csv", ".xlsx")
    return tuple(str(e).lower() if str(e).startswith(".") else f".{str(e).lower()}" for e in ext_list)


def _validate_input_file_if_defined(
    inputs_map: dict[str, Any],
    *,
    keys: tuple[str, ...],
    project_root: Path,
    command: str,
    errors: list[str],
    config: dict[str, Any] | None = None,
    check_format_extension: bool = False,
) -> None:
    """Validate that at least one input in keys group exists if defined.

    When check_format_extension is True (for format command), also validate
    the input file has an allowed extension (.csv or .xlsx per config).
    """
    for key in keys:
        value = inputs_map.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        resolved_input = _resolve_path(project_root, value)
        if not resolved_input.exists():
            errors.append(
                f"Missing input file for '{command}': inputs.{key}={value!r} "
                f"(resolved: {resolved_input})"
            )
            return
        if not resolved_input.is_file():
            errors.append(
                f"Input path for '{command}' is not a file: inputs.{key}={value!r} "
                f"(resolved: {resolved_input})"
            )
            return
        if check_format_extension and config:
            allowed = _get_allowed_extensions(config, command)
            suffix = resolved_input.suffix.lower()
            if suffix not in allowed:
                errors.append(
                    f"Format input must be CSV or XLSX: inputs.{key}={value!r} "
                    f"has extension {suffix!r} (allowed: {', '.join(allowed)})."
                )
            return
        return


def _is_under_root(project_root: Path, candidate: Path) -> bool:
    """Return whether candidate is under project root."""
    try:
        candidate.relative_to(project_root)
        return True
    except ValueError:
        return False
