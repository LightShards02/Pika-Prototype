"""Shared execution lifecycle for PIKA commands per PROJECT_CONTEXT.

Lifecycle template:
1. create/validate run workspace (safety preflight) — done in cli before dispatch
2. load config, prompts, context — done in cli, passed to handler
3. load required inputs
4. (optional) deterministic preprocessing
5. invoke agent (stub)
6. validate output schema
7. manual-resolution loop
8. translate output into doc/code changes (dry-run aware)
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from core.time_utils import format_timestamp_local_minutes
from pathlib import Path
from typing import Any, Callable

from core.pika_config import get_pika_config
from core.resolution import generate_resolution_template
from core.agent_invoker import (
    _parse_combined_prompt,
    render_prompt,
    run_api_invoke,
)
from core.context import RuntimeContext
from core.errors import AgentInvocationError, AgentSchemaError, SafetyPreconditionError
from core.pika_paths import get_default_schema_path
from core.prompt_registry import PromptRegistry
from core.vocab_loader import resolve_control_vocab_content

RUN_LOGGER_NAME = "agent_cli.run"
_LOCAL_AGENT_TEMP_PREFIX = "pika-local-agent-"


def _emit_agent_conclusion(
    prompt_name: str,
    elapsed_sec: float,
    token_usage: dict[str, int] | None = None,
) -> None:
    """Emit agent call conclusion to stderr: elapsed time and token usage (always)."""
    try:
        elapsed_str = f"{elapsed_sec:.1f}s"
        if token_usage:
            inp = token_usage.get("input_tokens", 0) + token_usage.get("cached_input_tokens", 0)
            out = token_usage.get("output_tokens", 0)
            msg = f"[PIKA] Agent complete ({prompt_name}): {elapsed_str}, in={inp}, out={out}\n"
        else:
            msg = f"[PIKA] Agent complete ({prompt_name}): {elapsed_str}, in=N/A, out=N/A\n"
        sys.stderr.write(msg)
        sys.stderr.flush()
    except OSError:
        pass


def _get_effective_inputs(config: dict[str, Any], command: str | None) -> dict[str, Any]:
    """Return commands.<cmd>.inputs. Single source of truth; no top-level merge."""
    if not command:
        return {}
    cmd_cfg = (config.get("commands") or {}).get(command)
    if not isinstance(cmd_cfg, dict):
        return {}
    cmd_inputs = cmd_cfg.get("inputs")
    if not isinstance(cmd_inputs, dict):
        return {}
    return dict(cmd_inputs)


def _get_effective_outputs(config: dict[str, Any], command: str | None) -> dict[str, Any]:
    """Return commands.<cmd>.outputs. Single source of truth; no top-level merge."""
    if not command:
        return {}
    cmd_cfg = (config.get("commands") or {}).get(command)
    if not isinstance(cmd_cfg, dict):
        return {}
    cmd_outputs = cmd_cfg.get("outputs")
    if not isinstance(cmd_outputs, dict):
        return {}
    return dict(cmd_outputs)


def resolve_output_schema_path(
    config: dict[str, Any],
    workspace_root: Path,
    schema_key: str,
    *,
    command: str | None = None,
) -> Path | None:
    """Resolve output schema path from pika.yaml schema_map.

    Schema paths are project-independent; resolved from PIKA root only.
    The ``config``, ``workspace_root``, and ``command`` parameters are kept
    for backward compatibility but ignored.
    """
    return get_default_schema_path(schema_key)


def _get_project_context_filename(config: dict[str, Any], command: str | None = None) -> str:
    """Return project context filename from config (required in commands.<cmd>.inputs).

    Uses commands.<cmd>.inputs.project_context_filename when command is provided.
    """
    inputs = _get_effective_inputs(config, command)
    val = inputs.get("project_context_filename")
    if isinstance(val, str) and val.strip():
        return val.strip()
    raise ValueError(
        "commands.<cmd>.inputs.project_context_filename is required in config"
    )


def _get_extra_prompt_filename(config: dict[str, Any], command: str | None = None) -> str | None:
    """Return extra prompt filename from config. None when not configured.

    Uses commands.<cmd>.inputs.extra_prompt_filename when command is provided.
    """
    inputs = _get_effective_inputs(config, command)
    val = inputs.get("extra_prompt_filename")
    if isinstance(val, str) and val.strip():
        return val.strip()
    return None


def resolve_extra_prompt_content(
    config: dict[str, Any],
    project_root: Path,
    ctx: RuntimeContext,
) -> str:
    """Resolve extra prompt content for map command. Optional; returns empty string when not configured or file not found.

    Resolution order:
    1. CLI --extra-prompt (explicit path)
    2. project_root / inputs.extra_prompt_filename (only when configured)

    When both CLI and config omit the extra prompt, no file is looked for; returns empty string.
    """
    context_path = resolve_input_path(
        config, project_root, "extra_prompt_path", overrides=ctx.input_overrides
    )
    if context_path is not None and context_path.exists() and context_path.is_file():
        return context_path.read_text(encoding="utf-8")
    filename = _get_extra_prompt_filename(config, ctx.command)
    if filename is None:
        return ""
    fallback_path = project_root / filename
    if fallback_path.exists() and fallback_path.is_file():
        return fallback_path.read_text(encoding="utf-8")
    return ""


def get_run_logger() -> logging.Logger:
    """Return the run logger instance."""
    return logging.getLogger(RUN_LOGGER_NAME)


def log_lifecycle_event(
    event: str,
    *,
    command: str,
    run_id: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit a structured lifecycle event to the run logger."""
    logger = get_run_logger()
    level = logger.getEffectiveLevel()
    payload: dict[str, Any] = {"event": event, "command": command, "run_id": run_id}
    if extra:
        payload.update(extra)
    logger.log(level, event, extra=payload)


def load_prompt_registry(config: dict[str, Any]) -> PromptRegistry:
    """Load and return the prompt registry from config. Prompts resolved from PIKA root."""
    return PromptRegistry.from_config(config)


def _resolve_path_from_value(value: str, project_root: Path) -> Path:
    """Resolve path string to Path. Handles absolute and relative paths."""
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate.resolve()
    return (project_root / value).resolve()


def resolve_project_state_path(
    config: dict[str, Any],
    project_root: Path,
    key: str,
) -> Path | None:
    """Resolve a path from project.state (design_spec_path, id_registry_path, sads_id_mapping_path)."""
    project = config.get("project")
    if not isinstance(project, dict):
        return None
    state = project.get("state")
    if not isinstance(state, dict):
        return None
    value = state.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    return _resolve_path_from_value(value.strip(), project_root)


def resolve_input_path(
    config: dict[str, Any],
    project_root: Path,
    key: str,
    *,
    overrides: dict[str, str] | None = None,
    command: str | None = None,
) -> Path | None:
    """Resolve an input path from CLI overrides, command inputs, or config.

    For design_spec_path when command is map, implement, review, or resolve_plan:
    Resolution order: CLI override > commands.<cmd>.inputs.design_spec_path >
    project.state.design_spec_path.

    For other keys: CLI override > commands.<cmd>.inputs.<key>.

    Args:
        config: Full PIKA config.
        project_root: Project root path.
        key: Input key (e.g. design_spec_path, srs_path, issue_tracking_path).
        overrides: Optional dict of key -> path from CLI args. Takes precedence.
        command: Optional command name for command-specific resolution (design_spec_path).

    Returns:
        Resolved Path or None if not configured.
    """
    if overrides:
        value = overrides.get(key)
        if isinstance(value, str) and value.strip():
            return _resolve_path_from_value(value.strip(), project_root)

    # design_spec_path: command-specific resolution for map, implement, review, resolve_plan
    if key == "design_spec_path" and command in ("map", "implement", "review", "resolve_plan", "refine"):
        commands_cfg = config.get("commands")
        if isinstance(commands_cfg, dict):
            cmd_cfg = commands_cfg.get(command)
            if isinstance(cmd_cfg, dict):
                inputs = cmd_cfg.get("inputs")
                if isinstance(inputs, dict):
                    value = inputs.get("design_spec_path")
                    if isinstance(value, str) and value.strip():
                        return _resolve_path_from_value(value.strip(), project_root)
        state_path = resolve_project_state_path(config, project_root, "design_spec_path")
        if state_path is not None:
            return state_path

        default = (
            get_pika_config()
            .get("default_workspace", {})
            .get("project", {})
            .get("state", {})
            .get("design_spec_path")
        )
        if isinstance(default, str) and default.strip():
            return _resolve_path_from_value(default.strip(), project_root)
        return None

    # Merged inputs (top-level + commands.<cmd>.inputs)
    inputs = _get_effective_inputs(config, command)
    value = inputs.get(key)
    if isinstance(value, str) and value.strip():
        return _resolve_path_from_value(value.strip(), project_root)
    return None


def resolve_format_source_path(
    config: dict[str, Any],
    project_root: Path,
    overrides: dict[str, str] | None,
) -> Path:
    """Resolve format command source path.

    Resolution order: CLI override (--design-spec) > commands.format.inputs.design_spec_path.
    No further fallback. Raises ValueError if neither is set.
    """
    if overrides:
        v = overrides.get("design_spec_path")
        if isinstance(v, str) and v.strip():
            return _resolve_path_from_value(v.strip(), project_root)
    commands_cfg = config.get("commands")
    if isinstance(commands_cfg, dict):
        fmt = commands_cfg.get("format")
        if isinstance(fmt, dict):
            inputs = fmt.get("inputs")
            if isinstance(inputs, dict):
                v = inputs.get("design_spec_path")
                if isinstance(v, str) and v.strip():
                    return _resolve_path_from_value(v.strip(), project_root)
    raise ValueError(
        "Format command requires input. Provide via CLI (--design-spec PATH) or "
        "commands.format.inputs.design_spec_path in config."
    )


def resolve_format_output_path(
    config: dict[str, Any],
    project_root: Path,
) -> Path | None:
    """Resolve format command output path.

    Resolution order: commands.format.outputs.design_spec_path > project.state.design_spec_path.
    """
    commands_cfg = config.get("commands")
    if isinstance(commands_cfg, dict):
        fmt = commands_cfg.get("format")
        if isinstance(fmt, dict):
            outputs = fmt.get("outputs")
            if isinstance(outputs, dict):
                spec = outputs.get("design_spec_path")
                if isinstance(spec, dict):
                    path_value = spec.get("path")
                    if isinstance(path_value, str) and path_value.strip():
                        return _resolve_path_from_value(path_value.strip(), project_root)
    state_path = resolve_project_state_path(config, project_root, "design_spec_path")
    if state_path is not None:
        return state_path

    default = (
        get_pika_config()
        .get("default_workspace", {})
        .get("project", {})
        .get("state", {})
        .get("design_spec_path")
    )
    if isinstance(default, str) and default.strip():
        return _resolve_path_from_value(default.strip(), project_root)
    return None


def resolve_codebase_dir_path(
    config: dict[str, Any],
    project_root: Path,
    ctx: RuntimeContext,
) -> Path:
    """Resolve codebase directory path. Defaults to project_root when not provided.

    Uses --codebase-dir or commands.<cmd>.inputs.codebase_dir if set.
    When the configured path is "." returns project_root.
    When path does not exist, it is created relative to project_root and returned.
    If configured path exists but is not a directory, falls back to project_root.
    """
    codebase_path = resolve_input_path(
        config, project_root, "codebase_dir",
        overrides=ctx.input_overrides, command=ctx.command,
    )
    if codebase_path is None:
        return project_root.resolve()

    resolved = codebase_path.resolve()
    if resolved == project_root.resolve():
        return project_root.resolve()
    if not resolved.exists():
        resolved.mkdir(parents=True, exist_ok=True)
    if not resolved.is_dir():
        return project_root.resolve()
    return resolved


def resolve_project_context_path(
    config: dict[str, Any],
    project_root: Path,
    ctx: RuntimeContext,
    codebase_dir_path: Path,
) -> Path | None:
    """Resolve project_context file path. Returns None if not found.

    Does not raise; use for preflight validation.
    Fallback: project_root / inputs.project_context_filename.
    """
    context_path = resolve_input_path(
        config, project_root, "project_context_path",
        overrides=ctx.input_overrides, command=ctx.command,
    )
    if context_path is not None and context_path.exists() and context_path.is_file():
        return context_path
    filename = _get_project_context_filename(config, ctx.command)
    fallback_path = project_root / filename
    if fallback_path.exists() and fallback_path.is_file():
        return fallback_path
    return None


def resolve_project_context_content(
    config: dict[str, Any],
    project_root: Path,
    ctx: RuntimeContext,
    codebase_dir_path: Path,
) -> str:
    """Resolve project_context content: CLI path or project_root/project_context_filename.

    Used by plan, map, and implement commands. Resolution order:
    1. CLI --project-context (explicit path)
    2. project_root / inputs.project_context_filename (fallback)

    Raises:
        SafetyPreconditionError: If project context cannot be found, with clear instructions.
    """
    context_path = resolve_project_context_path(
        config, project_root, ctx, codebase_dir_path
    )
    if context_path is not None:
        return context_path.read_text(encoding="utf-8")

    filename = _get_project_context_filename(config, ctx.command)
    raise SafetyPreconditionError(
        "Project context file not found. Provide it via:\n"
        f"  1. CLI: --project-context PATH (path to your project context file)\n"
        f"  2. Or place {filename} in the project root directory "
        f"({project_root})."
    )


def resolve_output_path(
    config: dict[str, Any],
    project_root: Path,
    output_key: str,
    *,
    command: str | None = None,
) -> Path | None:
    """Resolve an output path from config outputs section.

    For command-specific outputs (e.g. commands.format.outputs.design_spec_path),
    pass command. Otherwise uses top-level outputs.
    """
    if command == "format" and output_key == "design_spec_path":
        return resolve_format_output_path(config, project_root)
    outputs = _get_effective_outputs(config, command)
    spec = outputs.get(output_key)
    if not isinstance(spec, dict):
        return None
    path_value = spec.get("path")
    if not isinstance(path_value, str) or not path_value.strip():
        return None
    return _resolve_path_from_value(path_value.strip(), project_root)


def _agent_runs_base(
    config: dict[str, Any], project_root: Path, command: str | None = None
) -> Path:
    """Return base path for agent_runs_dir (used for command-aware resolution)."""
    base = resolve_output_path(
        config, project_root, "agent_runs_dir", command=command
    )
    if base is not None:
        return base
    return (project_root / "out" / "agent_runs").resolve()


def _agent_artifacts_base(
    config: dict[str, Any], project_root: Path, command: str | None = None
) -> Path:
    """Return base path for agent_artifacts_dir (used for command-aware resolution)."""
    base = resolve_output_path(
        config, project_root, "agent_artifacts_dir", command=command
    )
    if base is not None:
        return base
    return (project_root / "out" / "agent_artifacts").resolve()


def resolve_agent_runs_dir_for_command(
    config: dict[str, Any],
    project_root: Path,
    command_name: str,
    run_id: str | None = None,
) -> Path:
    """Resolve agent_runs path with command layer: out/agent_runs/{command}/{run_id}/...

    Returns base/command_name when run_id is None, else base/command_name/run_id.
    """
    base = _agent_runs_base(config, project_root, command=command_name)
    path = base / command_name
    if run_id:
        path = path / run_id
    return path.resolve()


def find_most_recent_blocked_run_id_across_commands(
    config: dict[str, Any],
    project_root: Path,
    commands: list[str],
) -> str | None:
    """Return run_id of the most recently modified blocked run across multiple commands.

    Iterates all run directories for each command and returns the run_id whose
    run_meta.json has a non-empty blocked_at_stage and the highest mtime.
    """
    best_mtime: float = -1.0
    best_run_id: str | None = None
    for cmd in commands:
        runs_base = resolve_agent_runs_dir_for_command(config, project_root, cmd)
        if not runs_base.is_dir():
            continue
        for run_dir in runs_base.iterdir():
            if not run_dir.is_dir():
                continue
            meta_path = run_dir / "run_meta.json"
            if not meta_path.exists():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not str(meta.get("blocked_at_stage", "")).strip():
                continue
            mtime = run_dir.stat().st_mtime
            if mtime > best_mtime:
                best_mtime = mtime
                best_run_id = run_dir.name
    return best_run_id


def find_most_recent_blocked_run_id(
    config: dict[str, Any],
    project_root: Path,
    command_name: str,
) -> str | None:
    """Return the run_id of the most recently modified blocked run for command, or None.

    Scans subdirectories of the command's runs base dir, sorted by mtime descending,
    and returns the first whose run_meta.json has a non-empty blocked_at_stage.
    """
    runs_base = resolve_agent_runs_dir_for_command(config, project_root, command_name)
    if not runs_base.is_dir():
        return None
    candidates = sorted(
        (d for d in runs_base.iterdir() if d.is_dir()),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    for run_dir in candidates:
        meta_path = run_dir / "run_meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(meta.get("blocked_at_stage", "")).strip():
            return run_dir.name
    return None


def resolve_agent_artifacts_dir_for_command(
    config: dict[str, Any],
    project_root: Path,
    command_name: str,
    run_id: str,
) -> Path:
    """Resolve agent_artifacts path with command layer: out/agent_artifacts/{command}/{run_id}/."""
    base = _agent_artifacts_base(config, project_root, command=command_name)
    return (base / command_name / run_id).resolve()


def resolve_run_summary_path_for_command(
    config: dict[str, Any],
    project_root: Path,
    command_name: str,
) -> Path:
    """Resolve run_summary path: out/agent_runs/{command}/run_summary.jsonl."""
    base = _agent_runs_base(config, project_root, command=command_name)
    return (base / command_name / "run_summary.jsonl").resolve()


def resolve_manual_resolution_path_for_command(
    config: dict[str, Any],
    project_root: Path,
    command_name: str,
) -> Path:
    """Resolve manual_resolution path: out/agent_runs/{command}/manual_resolution.csv."""
    base = _agent_runs_base(config, project_root, command=command_name)
    return (base / command_name / "manual_resolution.csv").resolve()


def resolve_resolution_template_path_for_run(
    config: dict[str, Any],
    project_root: Path,
    command_name: str,
    run_id: str,
) -> Path:
    """Resolve run-scoped manual resolution template path.

    Returns: out/agent_runs/{command}/{run_id}/manual_resolution/resolutions.yaml
    """
    run_dir = resolve_agent_runs_dir_for_command(
        config, project_root, command_name, run_id
    )
    return (run_dir / "manual_resolution" / "resolutions.yaml").resolve()


def persist_manual_resolution_block_for_run(
    config: dict[str, Any],
    project_root: Path,
    command_name: str,
    run_id: str,
    stage: str,
    items: list[dict[str, Any]],
    *,
    source: str = "agent",
    completed_stages: list[str] | None = None,
    spec_rows: list[dict[str, Any]] | None = None,
    headers: list[str] | None = None,
    shared_contracts: list[dict[str, Any]] | None = None,
) -> Path:
    """Persist blocking manual-resolution artifacts for a run.

    Writes:
    - run-scoped stage JSON: manual_resolution/{stage}.json
    - run-scoped template: manual_resolution/resolutions.yaml
    - run_meta updates: blocked_at_stage, completed_stages, resolution_status
    """
    run_dir = resolve_agent_runs_dir_for_command(config, project_root, command_name, run_id)
    manual_dir = run_dir / "manual_resolution"
    manual_dir.mkdir(parents=True, exist_ok=True)

    stage_payload = {"stage": stage, "items": items}
    (manual_dir / f"{stage}.json").write_text(
        json.dumps(stage_payload, indent=2),
        encoding="utf-8",
    )

    template_path = generate_resolution_template(
        run_dir=run_dir,
        stage=stage,
        items=items,
        command=command_name,
        run_id=run_id,
        source=source,
        spec_rows=spec_rows,
        headers=headers,
        shared_contracts=shared_contracts,
    )

    run_meta_path = run_dir / "run_meta.json"
    run_meta: dict[str, Any] = {}
    if run_meta_path.exists():
        try:
            run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
        except Exception:
            run_meta = {}
    run_meta["command"] = command_name
    run_meta["run_id"] = run_id
    run_meta["blocked_at_stage"] = stage
    run_meta["completed_stages"] = completed_stages or []
    run_meta["resolution_status"] = "pending"
    run_meta_path.write_text(json.dumps(run_meta, indent=2), encoding="utf-8")

    return template_path


def resolve_intermediate_map_dir(
    config: dict[str, Any], project_root: Path, *, command: str = "map"
) -> Path:
    """Resolve directory for per-subunit map outputs.

    Uses commands.map.outputs.intermediate_map_dir or outputs.intermediate_map_dir
    if configured; otherwise falls back to pika_config default_outputs.
    """
    resolved = resolve_output_path(
        config, project_root, "intermediate_map_dir", command=command
    )
    if resolved is not None:
        return resolved
    default = get_pika_config().get("default_outputs", {}).get(
        "intermediate_map_dir", "out/intermediate/map"
    )
    return (project_root / default).resolve()


def resolve_agent_input_codebase_content_dir(
    config: dict[str, Any], project_root: Path, *, command: str | None = None
) -> Path:
    """Resolve directory for writing codebase_content before each agent invocation.

    Uses commands.<cmd>.outputs.agent_input_codebase_content_dir if configured;
    otherwise falls back to pika_config default_outputs.agent_input_codebase_content_dir
    (out/agent_input/codebase_content).
    """
    resolved = resolve_output_path(
        config, project_root, "agent_input_codebase_content_dir", command=command
    )
    if resolved is not None:
        return resolved
    default = get_pika_config().get("default_outputs", {}).get(
        "agent_input_codebase_content_dir", "out/agent_input/codebase_content"
    )
    return (project_root / default).resolve()


def _filter_output_to_schema_properties(
    output: dict[str, Any], schema: dict[str, Any]
) -> dict[str, Any]:
    """Return output with only keys defined in schema root properties.

    Strips extra fields (e.g. Kimi's top-level summary) that violate
    additionalProperties: false. Preserves all schema-defined keys.
    """
    root_props = schema.get("properties", {})
    pattern_props = schema.get("patternProperties", {})
    if not root_props and not pattern_props:
        # Schemas using oneOf/anyOf at root may not define root properties.
        return output
    compiled_patterns = [
        re.compile(pattern)
        for pattern in pattern_props.keys()
        if isinstance(pattern, str) and pattern
    ]

    def _matches_pattern(key: str) -> bool:
        return any(pattern.search(key) is not None for pattern in compiled_patterns)

    return {
        k: v
        for k, v in output.items()
        if k in root_props or (isinstance(k, str) and _matches_pattern(k))
    }


def _backfill_missing_required_output_fields(
    output: dict[str, Any],
    schema: dict[str, Any],
    *,
    command: str | None = None,
    invocation_timestamp: str | None = None,
) -> dict[str, Any]:
    """Add minimal valid values for missing required root-level fields.

    Backfills run_summary and created_at when absent. Does not overwrite
    present values. Used when agents (e.g. Kimi) omit required fields.
    When invocation_timestamp is provided, uses it for created_at backfill
    instead of current time (e.g. for mapped_at = agent invocation time).
    """
    required = schema.get("required", [])
    if not required:
        return output
    result = dict(output)
    cmd_label = f"agent {command}" if command else "agent map"
    for key in required:
        if key in result:
            continue
        if key == "run_summary":
            result[key] = {
                "command": cmd_label,
                "status": "success",
                "summary": "(auto-generated)",
                "blocking_items": 0,
                "storage_file": "-",
            }
        elif key == "created_at":
            result[key] = (
                invocation_timestamp
                if invocation_timestamp
                else format_timestamp_local_minutes()
            )
    return result


def validate_output_against_schema(
    output: dict[str, Any],
    schema_path: Path,
    *,
    command: str | None = None,
    invocation_timestamp: str | None = None,
) -> dict[str, Any]:
    """Validate agent output against JSON schema. Raises ValueError on failure.

    Strips unknown root-level properties (e.g. Kimi's summary) and backfills
    missing required fields before validation. Returns the filtered/backfilled
    output on success.
    """
    schema_content = schema_path.read_text(encoding="utf-8")
    schema = json.loads(schema_content)
    output = _filter_output_to_schema_properties(output, schema)
    output = _backfill_missing_required_output_fields(
        output, schema, command=command, invocation_timestamp=invocation_timestamp
    )
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors(output))
    if errors:
        first = errors[0]
        raise AgentSchemaError(
            f"Output schema validation failed: {first.message} at {list(first.path)}"
        ) from first
    return output


def get_schema_validation_retries(config: dict[str, Any]) -> int:
    """Return number of schema validation retries from config. Default 0."""
    agent = config.get("agent")
    if not isinstance(agent, dict):
        return 0
    val = agent.get("schema_validation_retries")
    if isinstance(val, int) and val >= 0:
        return val
    return 0


def get_agent_provider(config: dict[str, Any]) -> str:
    """Return agent provider from config: 'stub', 'api', or 'local'. Default 'stub'."""
    agent = config.get("agent")
    if not isinstance(agent, dict):
        return "stub"
    val = agent.get("provider")
    if val in ("stub", "api", "local"):
        return val
    return "stub"


def get_local_command(config: dict[str, Any]) -> str:
    """Return deprecated `local_command` workspace value (historical Codex CLI).

    The local provider uses Loca in-process; this setting is not read by
    ``invoke_agent_local`` / ``build_loca_config``. Kept for config compatibility.
    """
    agent = config.get("agent")
    if not isinstance(agent, dict):
        return get_pika_config().get("local", {}).get("command", "codex")
    val = agent.get("local_command")
    if isinstance(val, str) and val.strip():
        return val.strip()
    return get_pika_config().get("local", {}).get("command", "codex")


def get_local_exec_timeout_sec(config: dict[str, Any]) -> int:
    """Return Loca agent call timeout in seconds (local provider).

    Resolution order:
    1) workspace config `agent.local_exec_timeout_sec` (positive number),
    2) pika default `local.exec_timeout_sec`,
    3) hard default `600`.
    """
    agent = config.get("agent")
    if isinstance(agent, dict):
        override = agent.get("local_exec_timeout_sec")
        if isinstance(override, (int, float)) and override > 0:
            return int(override)

    default_timeout = get_pika_config().get("local", {}).get("exec_timeout_sec", 600)
    if isinstance(default_timeout, (int, float)) and default_timeout > 0:
        return int(default_timeout)
    return 600


def get_reasoning_effort(config: dict[str, Any], prompt_name: str) -> str:
    """Return Codex model_reasoning_effort for the given prompt.

    Resolves: project agent.reasoning_effort[prompt_name] or .default,
    then pika local.reasoning_effort, then 'medium'.

    Returns:
        One of: low, medium, high, xhigh.
    """
    agent = config.get("agent")
    project_effort: dict[str, str] = {}
    if isinstance(agent, dict):
        re_obj = agent.get("reasoning_effort")
        if isinstance(re_obj, dict):
            project_effort = {k: str(v) for k, v in re_obj.items() if isinstance(v, str)}

    pika_effort: dict[str, str] = {}
    pika_local = get_pika_config().get("local", {})
    re_pika = pika_local.get("reasoning_effort")
    if isinstance(re_pika, dict):
        pika_effort = {k: str(v) for k, v in re_pika.items() if isinstance(v, str)}

    valid = ("low", "medium", "high", "xhigh")
    if prompt_name in project_effort and project_effort[prompt_name] in valid:
        return project_effort[prompt_name]
    if "default" in project_effort and project_effort["default"] in valid:
        return project_effort["default"]
    if prompt_name in pika_effort and pika_effort[prompt_name] in valid:
        return pika_effort[prompt_name]
    if "default" in pika_effort and pika_effort["default"] in valid:
        return pika_effort["default"]
    return "medium"


def get_model_verbosity(config: dict[str, Any], prompt_name: str) -> str | None:
    """Return Codex model_verbosity for the given prompt.

    Resolves: project agent.local_model_verbosity[prompt_name] or .default,
    then pika local.model_verbosity[prompt_name] or .default.
    Returns None when not configured (Codex uses its default).

    Returns:
        Non-empty string (e.g. low, medium, high) or None.
    """
    def _from_obj(obj: dict[str, str], key: str) -> str | None:
        val = obj.get(key) or obj.get("default")
        return str(val).strip() if isinstance(val, str) and val.strip() else None

    agent = config.get("agent")
    if isinstance(agent, dict):
        project_mv = agent.get("local_model_verbosity")
        if isinstance(project_mv, str) and project_mv.strip():
            return project_mv.strip()
        if isinstance(project_mv, dict):
            out = _from_obj(
                {k: str(v) for k, v in project_mv.items() if isinstance(v, str)},
                prompt_name,
            )
            if out:
                return out

    pika_local = get_pika_config().get("local", {})
    pika_mv = pika_local.get("model_verbosity")
    if isinstance(pika_mv, str) and pika_mv.strip():
        return pika_mv.strip()
    if isinstance(pika_mv, dict):
        out = _from_obj(
            {k: str(v) for k, v in pika_mv.items() if isinstance(v, str)},
            prompt_name,
        )
        if out:
            return out
    return None


def get_web_search(config: dict[str, Any], prompt_name: str) -> bool:
    """Return whether Codex --search (web search) is enabled for the given prompt.

    Resolves: project agent.local_web_search[prompt_name] or .default,
    then pika local.web_search[prompt_name] or .default, then False.

    Returns:
        True to pass --search to Codex exec.
    """
    def _from_obj(obj: dict[str, Any], key: str) -> bool | None:
        val = obj.get(key) if key in obj else obj.get("default")
        if isinstance(val, bool):
            return val
        return None

    agent = config.get("agent")
    if isinstance(agent, dict):
        project_ws = agent.get("local_web_search")
        if isinstance(project_ws, bool):
            return project_ws
        if isinstance(project_ws, dict):
            out = _from_obj(project_ws, prompt_name)
            if out is not None:
                return out

    pika_local = get_pika_config().get("local", {})
    pika_ws = pika_local.get("web_search")
    if isinstance(pika_ws, bool):
        return pika_ws
    if isinstance(pika_ws, dict):
        out = _from_obj(pika_ws, prompt_name)
        if out is not None:
            return out
    return False


def get_local_model(config: dict[str, Any], prompt_name: str) -> str:
    """Return Codex model ID for local provider for the given prompt.

    Resolves: project agent.local_model[prompt_name] or .default,
    then pika local.model[prompt_name] or .default.
    pika local.model is required, so a value is always returned.

    Returns:
        Model ID string (e.g. gpt-5-codex).
    """
    def _from_obj(obj: dict[str, str], key: str) -> str | None:
        val = obj.get(key) or obj.get("default")
        return str(val).strip() if isinstance(val, str) and val.strip() else None

    agent = config.get("agent")
    if isinstance(agent, dict):
        project_model = agent.get("local_model")
        if isinstance(project_model, str) and project_model.strip():
            return project_model.strip()
        if isinstance(project_model, dict):
            out = _from_obj(
                {k: str(v) for k, v in project_model.items() if isinstance(v, str)},
                prompt_name,
            )
            if out:
                return out

    pika_model = get_pika_config().get("local", {}).get("model")
    if isinstance(pika_model, str) and pika_model.strip():
        return pika_model.strip()
    if isinstance(pika_model, dict):
        out = _from_obj(
            {k: str(v) for k, v in pika_model.items() if isinstance(v, str)},
            prompt_name,
        )
        if out:
            return out
    return "gpt-5-codex"


def get_api_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return API config (api_key_env, url, model) from workspace + pika config."""
    pika = get_pika_config()
    api_defaults = pika.get("api", {})
    agent = config.get("agent")
    if not isinstance(agent, dict):
        agent = {}

    env_var = agent.get("api_key_env") or api_defaults.get("api_key_env", "NVIDIA_API_KEY")
    if isinstance(env_var, str) and env_var.strip():
        env_var = env_var.strip()
    else:
        env_var = "NVIDIA_API_KEY"

    key = os.environ.get(env_var)
    if not key or not str(key).strip():
        raise AgentInvocationError(
            f"API provider requires {env_var} environment variable to be set. "
            "Get an API key from your provider (e.g. https://build.nvidia.com/explore/discover)"
        )

    url = agent.get("api_url") or api_defaults.get(
        "url", "https://integrate.api.nvidia.com/v1/chat/completions"
    )
    model = agent.get("api_model") or api_defaults.get("model", "moonshotai/kimi-k2.5")
    return {"api_key": str(key).strip(), "url": str(url), "model": str(model)}


def _safe_workspace_token(value: str, fallback: str) -> str:
    """Return filesystem-safe token for temp workspace names."""
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "").strip("_.-")
    return token[:48] if token else fallback


def _resolve_local_agent_temp_base_dir(config: dict[str, Any], project_root: Path) -> Path:
    """Resolve base directory for local agent isolated temp workspaces."""
    pika_local = get_pika_config().get("local", {})
    agent = config.get("agent")
    configured = None
    if isinstance(agent, dict):
        configured = agent.get("local_temp_workspace_dir")
    if not isinstance(configured, str) or not configured.strip():
        configured = pika_local.get("temp_workspace_base_dir")
    if isinstance(configured, str) and configured.strip():
        candidate = Path(configured.strip())
        if not candidate.is_absolute():
            candidate = (project_root / candidate).resolve()
        return candidate
    return Path(tempfile.gettempdir()).resolve()


def _resolve_local_agent_temp_ttl_sec(config: dict[str, Any]) -> int:
    """Resolve stale isolated workspace TTL in seconds."""
    pika_local = get_pika_config().get("local", {})
    default_ttl = pika_local.get("temp_workspace_ttl_sec", 86_400)
    agent = config.get("agent")
    configured = None
    if isinstance(agent, dict):
        configured = agent.get("local_temp_workspace_ttl_sec")
    value = configured if configured is not None else default_ttl
    try:
        ttl = int(value)
    except (TypeError, ValueError):
        return 86_400
    return max(0, ttl)


def _resolve_local_agent_temp_prefix(config: dict[str, Any]) -> str:
    """Resolve isolated workspace directory name prefix."""
    pika_local = get_pika_config().get("local", {})
    configured = pika_local.get("temp_workspace_prefix")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    return _LOCAL_AGENT_TEMP_PREFIX


def _resolve_local_agent_fallback_temp_base_dir(project_root: Path) -> Path:
    """Return project-local fallback base dir for local agent temp workspaces."""
    return (project_root / "out" / "local_agent_temp").resolve()


def _probe_local_agent_temp_workspace_access(path: Path) -> None:
    """Raise when the process cannot read/write inside workspace path."""
    probe_file = path / ".pika_access_probe"
    list(path.iterdir())
    probe_file.write_text("ok", encoding="utf-8")
    probe_file.unlink(missing_ok=True)


def _create_local_agent_workspace_dir(base_dir: Path, temp_name_prefix: str) -> Path:
    """Create a unique workspace directory using inherited ACLs from base_dir."""
    for _ in range(64):
        suffix = uuid.uuid4().hex[:8]
        candidate = base_dir / f"{temp_name_prefix}{suffix}"
        try:
            candidate.mkdir(parents=False, exist_ok=False)
            return candidate
        except FileExistsError:
            continue
    raise FileExistsError(
        f"Unable to create unique local agent workspace under {base_dir}"
    )


def _cleanup_stale_local_agent_workspaces(base_dir: Path, prefix: str, ttl_sec: int) -> None:
    """Best-effort cleanup for stale isolated local workspaces."""
    if ttl_sec <= 0:
        return
    now = time.time()
    try:
        children = list(base_dir.glob(f"{prefix}*"))
    except OSError:
        return
    for child in children:
        try:
            if not child.is_dir():
                continue
            age_sec = now - child.stat().st_mtime
            if age_sec >= ttl_sec:
                shutil.rmtree(child, ignore_errors=True)
        except OSError:
            continue


def _create_local_agent_temp_workspace(
    config: dict[str, Any],
    project_root: Path,
    *,
    command: str,
    run_id: str,
    prompt_name: str,
) -> Path:
    """Create isolated temp workspace for a local agent invocation."""
    prefix = _resolve_local_agent_temp_prefix(config)
    ttl_sec = _resolve_local_agent_temp_ttl_sec(config)
    safe_command = _safe_workspace_token(command, "cmd")
    safe_run = _safe_workspace_token(run_id, "run")
    safe_prompt = _safe_workspace_token(prompt_name, "prompt")
    temp_name_prefix = f"{prefix}{safe_command}_{safe_run}_{safe_prompt}_"
    primary_base = _resolve_local_agent_temp_base_dir(config, project_root)
    fallback_base = _resolve_local_agent_fallback_temp_base_dir(project_root)
    base_candidates: list[Path] = [primary_base]
    if fallback_base != primary_base:
        base_candidates.append(fallback_base)

    last_error: OSError | None = None
    for base_dir in base_candidates:
        created_workspace: Path | None = None
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
            _cleanup_stale_local_agent_workspaces(base_dir, prefix, ttl_sec)
            created_workspace = _create_local_agent_workspace_dir(
                base_dir, temp_name_prefix
            )
            _probe_local_agent_temp_workspace_access(created_workspace)
            return created_workspace
        except OSError as exc:
            last_error = exc
            if created_workspace is not None:
                _cleanup_local_agent_temp_workspace(created_workspace)

    if last_error is not None:
        raise AgentInvocationError(
            f"Unable to create local agent temp workspace: {last_error}"
        ) from last_error
    raise AgentInvocationError("Unable to create local agent temp workspace")


def _cleanup_local_agent_temp_workspace(path: Path | None) -> None:
    """Best-effort immediate cleanup for isolated temp workspace."""
    if path is None:
        return
    shutil.rmtree(path, ignore_errors=True)


def create_local_agent_shared_workspace(
    config: dict[str, Any],
    project_root: Path,
    *,
    command: str,
    run_id: str,
) -> Path:
    """Create a run-scoped shared temp workspace for local agent invocations."""
    return _create_local_agent_temp_workspace(
        config,
        project_root,
        command=command,
        run_id=run_id,
        prompt_name="shared",
    )


def cleanup_local_agent_temp_workspace(path: Path | None) -> None:
    """Public cleanup wrapper for shared/local agent temp workspaces."""
    _cleanup_local_agent_temp_workspace(path)


def _is_path_within(path: Path, ancestor: Path) -> bool:
    """Return True when path is equal to or contained by ancestor."""
    try:
        path.resolve().relative_to(ancestor.resolve())
        return True
    except ValueError:
        return False


def sync_local_agent_workspace(source_dir: Path, workspace_dir: Path) -> None:
    """Replace workspace contents with a deterministic mirror of source_dir."""
    source = source_dir.resolve()
    workspace = workspace_dir.resolve()
    if not source.exists() or not source.is_dir():
        raise AgentInvocationError(f"Local workspace sync source must be an existing directory: {source}")
    logger = get_run_logger()
    workspace.mkdir(parents=True, exist_ok=True)

    for child in workspace.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)

    source_children = sorted(source.iterdir(), key=lambda path: path.name.lower())
    for child in source_children:
        try:
            child_resolved = child.resolve()
            if child_resolved == workspace or _is_path_within(workspace, child_resolved):
                continue
            destination = workspace / child.name
            if child.is_dir():
                shutil.copytree(child, destination, symlinks=True)
            else:
                shutil.copy2(child, destination)
        except OSError as exc:
            logger.warning(
                "Skipping unreadable path while syncing local workspace: %s (%s)",
                child,
                exc,
            )
            continue


def invoke_agent_local(
    prompt_name: str,
    template_vars: dict[str, Any],
    *,
    schema_path: Path | None,
    config: dict[str, Any],
    ctx: RuntimeContext,
    local_workspace_override: Path | None = None,
    retry_instruction: str | None = None,
) -> dict[str, Any]:
    """Invoke agent via Loca (in-process) in an isolated temp workspace."""
    project_root = Path(ctx.project_root)
    registry = load_prompt_registry(config)
    spec = registry.get(prompt_name)

    prompt_text = render_prompt(
        spec.system_prompt,
        spec.user_prompt,
        template_vars,
    )
    if retry_instruction:
        prompt_text = prompt_text + "\n\n" + retry_instruction

    run_id = ctx.run_id or "run"
    run_dir = resolve_agent_artifacts_dir_for_command(
        config, project_root, ctx.command, run_id
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    output_path = run_dir / "local_output.json"
    managed_workspace = local_workspace_override is None
    if local_workspace_override is not None:
        isolated_workspace = local_workspace_override.resolve()
        isolated_workspace.mkdir(parents=True, exist_ok=True)
    else:
        isolated_workspace = _create_local_agent_temp_workspace(
            config,
            project_root,
            command=ctx.command,
            run_id=run_id,
            prompt_name=prompt_name,
        )
    isolated_output_path = isolated_workspace / "local_output.json"

    if schema_path and schema_path.exists():
        schema_path_resolved = (
            schema_path.resolve()
            if schema_path.is_absolute()
            else (project_root / schema_path).resolve()
        )
    else:
        schema_path_resolved = registry.get_schema_path(prompt_name)

    log_lifecycle_event(
        "agent_invoke_local",
        command=ctx.command,
        run_id=ctx.run_id,
        extra={
            "prompt_name": prompt_name,
            "output_path": str(output_path),
            "schema_path": str(schema_path_resolved),
            "workspace": str(isolated_workspace),
            "provider": "local",
        },
    )

    from core.loca_bridge import build_loca_config, check_loca_available, run_loca_agent

    stream_output = True
    agent = config.get("agent")
    if isinstance(agent, dict) and "stream_output" in agent:
        stream_output = bool(agent.get("stream_output", True))

    loca_config = build_loca_config(config, prompt_name, isolated_workspace)
    provider_sub = loca_config.model.provider

    try:
        if not check_loca_available(provider_sub):
            auth_hint = (
                "Run `loca --login` to authenticate."
                if provider_sub == "openai-codex"
                else "Set the OPENAI_API_KEY environment variable."
            )
            raise AgentInvocationError(
                f"Local provider ({provider_sub}) authentication is unavailable. {auth_hint}"
            )

        # Load JSON schema for API-level structured output enforcement
        json_schema = None
        if schema_path_resolved and schema_path_resolved.exists():
            json_schema = json.loads(schema_path_resolved.read_text(encoding="utf-8"))

        system_part, user_part = _parse_combined_prompt(prompt_text)

        t0 = time.perf_counter()
        result, token_usage = run_loca_agent(
            system_prompt=system_part,
            user_prompt=user_part,
            loca_config=loca_config,
            json_schema=json_schema,
            stream_output=stream_output,
            stream_reasoning=ctx.verbose,
        )

        # Save output artifact
        try:
            output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        except OSError as exc:
            get_run_logger().warning(
                "Could not write local output artifact to %s: %s",
                output_path,
                exc,
            )

        elapsed = time.perf_counter() - t0
        log_lifecycle_event(
            "agent_invoke_local_complete",
            command=ctx.command,
            run_id=ctx.run_id,
            extra={
                "prompt_name": prompt_name,
                "output_path": str(output_path),
            },
        )
        if token_usage:
            log_lifecycle_event(
                "agent_token_usage",
                command=ctx.command,
                run_id=ctx.run_id,
                extra={
                    "prompt_name": prompt_name,
                    "input_tokens": token_usage.get("input_tokens", 0),
                    "cached_input_tokens": token_usage.get("cached_input_tokens", 0),
                    "output_tokens": token_usage.get("output_tokens", 0),
                },
            )
        _emit_agent_conclusion(prompt_name, elapsed, token_usage)
        return result
    except AgentInvocationError:
        raise
    except (ValueError, RuntimeError) as exc:
        log_lifecycle_event(
            "agent_invoke_local_failed",
            command=ctx.command,
            run_id=ctx.run_id,
            extra={
                "prompt_name": prompt_name,
                "output_path": str(output_path),
                "error": str(exc),
            },
        )
        raise AgentInvocationError(
            f"Local agent invocation failed: {exc}"
        ) from exc
    finally:
        if managed_workspace:
            _cleanup_local_agent_temp_workspace(isolated_workspace)


def invoke_agent_api(
    prompt_name: str,
    template_vars: dict[str, Any],
    *,
    schema_path: Path | None,
    config: dict[str, Any],
    ctx: RuntimeContext,
    retry_instruction: str | None = None,
) -> dict[str, Any]:
    """Invoke agent via remote API. Renders prompt, calls chat completions API, returns parsed JSON."""
    project_root = Path(ctx.project_root)
    registry = load_prompt_registry(config)
    spec = registry.get(prompt_name)

    prompt_text = render_prompt(
        spec.system_prompt,
        spec.user_prompt,
        template_vars,
    )
    if retry_instruction:
        prompt_text = prompt_text + "\n\n" + retry_instruction

    run_id = ctx.run_id or "run"
    run_dir = resolve_agent_artifacts_dir_for_command(
        config, project_root, ctx.command, run_id
    )
    output_path = run_dir / "api_output.json"

    log_lifecycle_event(
        "agent_invoke_api",
        command=ctx.command,
        run_id=ctx.run_id,
        extra={
            "prompt_name": prompt_name,
            "output_path": str(output_path),
            "provider": "api",
        },
    )

    api_cfg = get_api_config(config)
    stream_output = True
    agent = config.get("agent")
    if isinstance(agent, dict) and "stream_output" in agent:
        stream_output = bool(agent.get("stream_output", True))

    try:
        sys.stderr.write("[PIKA] Agent running (API)...\n")
        sys.stderr.flush()
    except OSError:
        pass

    t0 = time.perf_counter()
    result, token_usage = run_api_invoke(
        prompt=prompt_text,
        api_key=api_cfg["api_key"],
        url=api_cfg["url"],
        model=api_cfg["model"],
        command=ctx.command,
        stream=stream_output,
        stream_output=stream_output,
        output_path=output_path,
    )
    elapsed = time.perf_counter() - t0

    log_lifecycle_event(
        "agent_invoke_api_complete",
        command=ctx.command,
        run_id=ctx.run_id,
        extra={
            "prompt_name": prompt_name,
            "output_path": str(output_path),
        },
    )
    if token_usage:
        log_lifecycle_event(
            "agent_token_usage",
            command=ctx.command,
            run_id=ctx.run_id,
            extra={
                "prompt_name": prompt_name,
                "input_tokens": token_usage.get("input_tokens", 0),
                "cached_input_tokens": token_usage.get("cached_input_tokens", 0),
                "output_tokens": token_usage.get("output_tokens", 0),
            },
        )
    _emit_agent_conclusion(prompt_name, elapsed, token_usage)
    return result


def _write_codebase_content_before_invoke(
    template_vars: dict[str, Any],
    *,
    config: dict[str, Any],
    ctx: RuntimeContext,
) -> None:
    """Write codebase_content to a human-readable file before agent invocation.

    Writes to {agent_input_codebase_content_dir}/{run_id}/codebase_content_{command}.md
    when template_vars contains non-empty codebase_content.
    """
    content = template_vars.get("codebase_content")
    if not content or not isinstance(content, str) or not content.strip():
        return
    project_root = Path(ctx.project_root)
    out_dir = resolve_agent_input_codebase_content_dir(
        config, project_root, command=ctx.command
    )
    run_subdir = out_dir / (ctx.run_id or "run")
    run_subdir.mkdir(parents=True, exist_ok=True)
    out_path = run_subdir / f"codebase_content_{ctx.command}.md"
    try:
        out_path.write_text(content, encoding="utf-8")
    except OSError as exc:
        get_run_logger().warning(
            "Could not write codebase_content to %s: %s", out_path, exc
        )


def invoke_agent_with_schema_retry(
    prompt_name: str,
    template_vars: dict[str, Any],
    *,
    schema_path: Path | None,
    config: dict[str, Any],
    ctx: RuntimeContext,
    local_workspace_override: Path | None = None,
    invocation_timestamp: str | None = None,
) -> dict[str, Any]:
    """Invoke agent and validate output. Retry up to configurable times on schema failure.

    When schema_path is None or missing, skips validation and returns immediately.
    """
    max_retries = get_schema_validation_retries(config)
    last_error: ValueError | None = None

    for attempt in range(max_retries + 1):
        retry_instruction: str | None = None
        if attempt > 0 and last_error is not None:
            retry_instruction = (
                "[Retry] Your previous output failed schema validation. "
                f"Error: {last_error}. Please fix the output to comply with the schema and try again."
            )
        provider = get_agent_provider(config)
        log_lifecycle_event(
            "lifecycle_invoke_agent",
            command=ctx.command,
            run_id=ctx.run_id,
            extra={
                "prompt_name": prompt_name,
                "provider": provider,
                "attempt": attempt + 1,
                "max_attempts": max_retries + 1,
            },
        )
        if "control_vocab_section" not in template_vars:
            project_root = Path(ctx.project_root)
            template_vars["control_vocab_section"] = resolve_control_vocab_content(
                config, project_root
            )
        _write_codebase_content_before_invoke(
            template_vars,
            config=config,
            ctx=ctx,
        )
        if provider == "local":
            output = invoke_agent_local(
                prompt_name=prompt_name,
                template_vars=template_vars,
                schema_path=schema_path,
                config=config,
                ctx=ctx,
                local_workspace_override=local_workspace_override,
                retry_instruction=retry_instruction,
            )
        elif provider == "api":
            output = invoke_agent_api(
                prompt_name=prompt_name,
                template_vars=template_vars,
                schema_path=schema_path,
                config=config,
                ctx=ctx,
                retry_instruction=retry_instruction,
            )
        else:
            output = invoke_agent_stub(
                prompt_name=prompt_name,
                template_vars=template_vars,
                ctx=ctx,
            )

        if schema_path is None or not schema_path.exists():
            return output

        try:
            output = validate_output_against_schema(
                output,
                schema_path,
                command=ctx.command,
                invocation_timestamp=invocation_timestamp,
            )
            log_lifecycle_event(
                "lifecycle_validate_output",
                command=ctx.command,
                run_id=ctx.run_id,
                extra={
                    "prompt_name": prompt_name,
                    "schema_path": str(schema_path),
                    "validation_result": "passed",
                },
            )
            return output
        except (ValueError, AgentSchemaError) as exc:
            last_error = exc
            log_lifecycle_event(
                "lifecycle_validate_output",
                command=ctx.command,
                run_id=ctx.run_id,
                extra={
                    "prompt_name": prompt_name,
                    "schema_path": str(schema_path),
                    "validation_result": "failed",
                    "validation_error": str(exc),
                    "attempt": attempt + 1,
                    "max_attempts": max_retries + 1,
                },
            )
            if attempt < max_retries:
                sys.stderr.write(
                    f"[PIKA] {prompt_name}: schema validation failed (attempt {attempt + 1}/{max_retries + 1}), retrying...\n"
                )
                sys.stderr.flush()
                log_lifecycle_event(
                    "lifecycle_schema_validation_retry",
                    command=ctx.command,
                    run_id=ctx.run_id,
                    extra={
                        "attempt": attempt + 1,
                        "max_retries": max_retries,
                        "error": str(exc),
                    },
                )
            else:
                sys.stderr.write(
                    f"[PIKA] {prompt_name}: schema validation failed after {max_retries + 1} attempt(s)\n"
                )
                sys.stderr.flush()
                raise last_error from exc

    raise last_error  # type: ignore[misc]


def has_blocking_manual_resolution(output: dict[str, Any]) -> bool:
    """Return True if output contains blocking manual_resolution_items."""
    items = output.get("manual_resolution_items")
    return isinstance(items, list) and len(items) > 0


def append_manual_resolution_items_to_file(
    items: list[dict[str, Any]],
    storage_path: Path,
) -> None:
    """Append each manual resolution item as a JSON line to the storage file."""
    logger = get_run_logger()
    if not items:
        return
    try:
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        with storage_path.open("a", encoding="utf-8") as f:
            for item in items:
                line = json.dumps(item, separators=(",", ":")) + "\n"
                f.write(line)
    except OSError as exc:
        logger.warning("Could not append manual resolution items: %s", exc)


def _stub_map_mappings_from_csv(csv_content: str) -> dict[str, dict[str, Any]]:
    """Parse design_spec_rows_csv and return stub mappings dict for each spec_id.

    Returns {spec_id: {status, code_refs, assumptions}} per schema. Falls back to A1 if
    no spec_ids found.
    """
    pattern = re.compile(r"^[A-Za-z][0-9]+$")
    result: dict[str, dict[str, Any]] = {}
    if not csv_content or not isinstance(csv_content, str):
        result["A1"] = {"status": "unmapped", "code_refs": [], "assumptions": "Stub"}
        return result
    try:
        reader = csv.DictReader(io.StringIO(csv_content.strip()))
        headers = reader.fieldnames or []
        spec_id_key = None
        for h in headers:
            if h and h.strip().lower() == "spec_id":
                spec_id_key = h
                break
        if spec_id_key:
            for row in reader:
                sid = (row.get(spec_id_key) or "").strip()
                if sid and pattern.match(sid):
                    result[sid] = {
                        "status": "unmapped",
                        "code_refs": [],
                        "assumptions": "Stub",
                    }
    except (csv.Error, ValueError):
        pass
    if not result:
        result["A1"] = {"status": "unmapped", "code_refs": [], "assumptions": "Stub"}
    return result


def invoke_agent_stub(
    prompt_name: str,
    template_vars: dict[str, Any],
    *,
    ctx: RuntimeContext,
) -> dict[str, Any]:
    """Stub for agent invocation. Returns schema-compliant minimal output.

    Real implementation would call LLM with prompt and template vars.
    """
    cmd_label = f"agent {ctx.command}"
    storage_file = template_vars.get("run_summary_file") or "-"
    if not isinstance(storage_file, str) or not storage_file.strip():
        storage_file = "-"
    base = {
        "manual_resolution_items": [],
        "run_summary": {
            "command": cmd_label,
            "status": "success",
            "summary": "Stub: no agent invocation",
            "blocking_items": 0,
            "storage_file": storage_file.strip(),
        },
        "created_at": "2020-01-01T00:00:00Z",
    }
    if ctx.command == "plan":
        base["milestones"] = [{"id": "M1", "title": "Stub milestone", "description": "Stub", "dependencies": []}]
        stub_path = get_pika_config().get("stub", {}).get(
            "plan_proposed_sads", "out/agent_artifacts/stub/plan_proposed_sads.csv"
        )
        base["proposed_sads_outline_path"] = stub_path
    elif ctx.command == "map":
        raw = _stub_map_mappings_from_csv(
            template_vars.get("design_spec_rows_csv") or ""
        )
        base["mappings"] = [
            {"spec_id": sid, **vals} for sid, vals in raw.items()
        ]
    elif ctx.command == "implement":
        if prompt_name == "implement_anchor_planner":
            return {
                "module_tag": "STUB",
                "planned_anchors": [],
                "provided_intents": [],
                "required_intents": [],
            }
        spec_ids = list(_stub_map_mappings_from_csv(
            template_vars.get("selected_specs_csv") or ""
        ).keys())
        if not spec_ids:
            spec_ids = ["A1"]
        output: dict[str, Any] = {
            "run_summary": {
                "status": "success",
                "notes": "Stub implement output",
            }
        }
        for spec_id in spec_ids:
            output[spec_id] = {
                "summary": "Stub diff output",
                "diffs": [],
                "mapped_classes_functions": [],
                "mapped_test_cases": [],
            }
        return output
    elif ctx.command == "resolve_plan":
        base["mappings"] = {"IS01": {"spec_ids": [], "notes": "Stub"}}
    return base
