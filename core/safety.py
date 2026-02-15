from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Iterable

from core.errors import SafetyPreconditionError
from core.logger import _resolve_log_dir


_DEFAULT_STATE_DIR = Path("out/state")
_LOAD_INPUT_KEY_GROUPS = (
    ("design_spec_path", "design_spec"),
    ("issue_tracking_path", "issue_tracking"),
)


def validate_common_preconditions(config: dict[str, Any], ctx: Any) -> None:
    """Validate common preconditions."""
    project_root = _resolve_project_root(ctx)

    if not project_root.exists():
        raise SafetyPreconditionError(
            f"Project root does not exist: {project_root}"
        )
    if not project_root.is_dir():
        raise SafetyPreconditionError(
            f"Project root is not a directory: {project_root}"
        )

    log_dir = _resolve_log_dir(project_root, config)
    if not _is_under_root(project_root, log_dir):
        raise SafetyPreconditionError(
            f"Unsafe log_dir: {log_dir} resolves outside project root ({project_root})."
        )
    _ensure_directory_writable(log_dir, label="log_dir")

    checked_dirs: set[Path] = set()
    for output_key, output_path, _no_overwrite in _iter_output_specs(config):
        resolved_output = _resolve_path(project_root, output_path)
        if not _is_under_root(project_root, resolved_output):
            raise SafetyPreconditionError(
                f"Unsafe output path: outputs.{output_key}.path={output_path!r} "
                f"resolves outside project root ({project_root})."
            )

        target_dir = _target_directory_for_output(output_key, resolved_output)
        if target_dir in checked_dirs:
            continue
        _ensure_directory_writable(target_dir, label=f"outputs.{output_key}")
        checked_dirs.add(target_dir)

    state_dir = _resolve_state_dir(config, project_root)
    if not _is_under_root(project_root, state_dir):
        raise SafetyPreconditionError(
            f"Unsafe state_dir: {state_dir} resolves outside project root ({project_root})."
        )
    _ensure_directory_writable(state_dir, label="state_dir")

    for output_key, output_path, no_overwrite in _iter_output_specs(config):
        if no_overwrite and not output_key.endswith("_dir"):
            resolved_output = _resolve_path(project_root, output_path)
            if resolved_output.exists():
                raise SafetyPreconditionError(
                    "Refusing to overwrite existing output file "
                    f"'{resolved_output}' because no-overwrite is enabled "
                    f"(outputs.{output_key}.no_overwrite=true)."
                )


def validate_command_preconditions(command: str, config: dict[str, Any], ctx: Any) -> None:
    """Validate command preconditions."""
    validate_common_preconditions(config, ctx)

    project_root = _resolve_project_root(ctx)
    inputs = config.get("inputs")
    inputs_map = inputs if isinstance(inputs, dict) else {}

    if command == "load":
        for keys in _LOAD_INPUT_KEY_GROUPS:
            _validate_input_file_if_defined(
                inputs_map, keys=keys, project_root=project_root, command=command
            )
        return

    if command in {"index", "implement", "issue"}:
        for keys in _LOAD_INPUT_KEY_GROUPS:
            _validate_input_file_if_defined(
                inputs_map, keys=keys, project_root=project_root, command=command
            )
        return

    raise SafetyPreconditionError(f"Unsupported command for safety validation: {command}")


def _resolve_project_root(ctx: Any) -> Path:
    """Resolve project root."""
    project_root: Any = getattr(ctx, "project_root", None)
    if project_root is None and isinstance(ctx, dict):
        project_root = ctx.get("project_root")
    if isinstance(project_root, Path):
        return project_root.resolve()
    if isinstance(project_root, str) and project_root.strip():
        return Path(project_root).resolve()
    raise SafetyPreconditionError("Runtime context missing a valid 'project_root'.")


def _resolve_path(project_root: Path, path_value: str) -> Path:
    """Resolve path."""
    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate.resolve()
    return (project_root / candidate).resolve()


def _iter_output_specs(config: dict[str, Any]) -> Iterable[tuple[str, str, bool]]:
    """Iterate output specs."""
    outputs = config.get("outputs")
    if not isinstance(outputs, dict):
        return ()
    return (
        (key, path_value, no_overwrite)
        for key, value in outputs.items()
        if isinstance(value, dict)
        and isinstance((path_value := value.get("path")), str)
        and path_value.strip()
        and isinstance((no_overwrite := value.get("no_overwrite")), bool)
    )


def _target_directory_for_output(output_key: str, resolved_output: Path) -> Path:
    """Return target directory for output."""
    if output_key.endswith("_dir"):
        return resolved_output
    if resolved_output.exists() and resolved_output.is_dir():
        return resolved_output
    return resolved_output.parent


def _ensure_directory_writable(directory: Path, *, label: str) -> None:
    """Return ensure directory writable."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SafetyPreconditionError(
            f"Unable to create directory for {label}: {directory} ({exc})"
        ) from exc

    if not directory.is_dir():
        raise SafetyPreconditionError(
            f"Path for {label} is not a directory: {directory}"
        )

    probe = directory / f".safety_write_probe_{uuid.uuid4().hex}.tmp"
    try:
        probe.write_text("probe", encoding="utf-8")
    except OSError as exc:
        raise SafetyPreconditionError(
            f"Directory for {label} is not writable: {directory} ({exc})"
        ) from exc
    finally:
        try:
            if probe.exists():
                probe.unlink()
        except OSError:
            pass


def _resolve_state_dir(config: dict[str, Any], project_root: Path) -> Path:
    """Resolve state dir."""
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
        return (project_root / _DEFAULT_STATE_DIR).resolve()
    return _resolve_path(project_root, state_dir_value)


def _validate_input_file_if_defined(
    inputs_map: dict[str, Any],
    *,
    keys: tuple[str, ...],
    project_root: Path,
    command: str,
) -> None:
    """Validate input file if defined."""
    for key in keys:
        value = inputs_map.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        resolved_input = _resolve_path(project_root, value)
        if not resolved_input.exists():
            raise SafetyPreconditionError(
                f"Missing input file for '{command}': inputs.{key}={value!r} "
                f"(resolved: {resolved_input})"
            )
        if not resolved_input.is_file():
            raise SafetyPreconditionError(
                f"Input path for '{command}' is not a file: inputs.{key}={value!r} "
                f"(resolved: {resolved_input})"
            )
        return


def _is_under_root(project_root: Path, candidate: Path) -> bool:
    """Return whether under root."""
    try:
        candidate.relative_to(project_root)
        return True
    except ValueError:
        return False
