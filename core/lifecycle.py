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
import re
import subprocess
import sys
from core.time_utils import format_timestamp_local_minutes
from pathlib import Path
from typing import Any, Callable

from core.agent_invoker import render_prompt, run_api_invoke, run_local_exec
from core.context import RuntimeContext
from core.errors import SafetyPreconditionError
from core.pika_paths import resolve_schema_path
from core.prompt_registry import PromptRegistry

RUN_LOGGER_NAME = "agent_cli.run"


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


def _get_effective_schemas(config: dict[str, Any], command: str | None) -> dict[str, Any]:
    """Return commands.<cmd>.schemas. Single source of truth; no top-level merge."""
    if not command:
        return {}
    cmd_cfg = (config.get("commands") or {}).get(command)
    if not isinstance(cmd_cfg, dict):
        return {}
    cmd_schemas = cmd_cfg.get("schemas")
    if not isinstance(cmd_schemas, dict):
        return {}
    return dict(cmd_schemas)


def resolve_output_schema_path(
    config: dict[str, Any],
    workspace_root: Path,
    schema_key: str,
    *,
    command: str | None = None,
) -> Path | None:
    """Resolve output schema path from config.

    Resolution order: commands.<cmd>.schemas.<key> > top-level schemas.<key>.
    Tries workspace first, then PIKA root.
    """
    schemas = _get_effective_schemas(config, command)
    if schema_key not in schemas:
        top = config.get("schemas") or {}
        if isinstance(top, dict) and schema_key in top:
            schemas = top
        else:
            return None
    path_val = schemas.get(schema_key)
    if not isinstance(path_val, str) or not path_val.strip():
        return None
    return resolve_schema_path(path_val, schema_key, workspace_root)


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
    if key == "design_spec_path" and command in ("map", "implement", "review", "resolve_plan"):
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
        from core.pika_config import get_pika_config

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
    from core.pika_config import get_pika_config

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

    Uses --codebase-dir or commands.<cmd>.inputs.codebase_dir if set and the path exists;
    otherwise returns project_root.
    """
    codebase_path = resolve_input_path(
        config, project_root, "codebase_dir",
        overrides=ctx.input_overrides, command=ctx.command,
    )
    if codebase_path is not None and codebase_path.exists():
        return codebase_path.resolve()
    return project_root.resolve()


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


def resolve_intermediate_map_dir(
    config: dict[str, Any], project_root: Path, *, command: str = "map"
) -> Path:
    """Resolve directory for per-subunit map outputs.

    Uses commands.map.outputs.intermediate_map_dir or outputs.intermediate_map_dir
    if configured; otherwise falls back to pika_config default_outputs.
    """
    from core.pika_config import get_pika_config

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
    from core.pika_config import get_pika_config

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
        raise ValueError(
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
    """Return local CLI executable name from config. Default 'codex'."""
    from core.pika_config import get_pika_config

    agent = config.get("agent")
    if not isinstance(agent, dict):
        return get_pika_config().get("local", {}).get("command", "codex")
    val = agent.get("local_command")
    if isinstance(val, str) and val.strip():
        return val.strip()
    return get_pika_config().get("local", {}).get("command", "codex")


def get_reasoning_effort(config: dict[str, Any], prompt_name: str) -> str:
    """Return Codex model_reasoning_effort for the given prompt.

    Resolves: project agent.reasoning_effort[prompt_name] or .default,
    then pika local.reasoning_effort, then 'medium'.

    Returns:
        One of: low, medium, high, xhigh.
    """
    from core.pika_config import get_pika_config

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


def get_api_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return API config (api_key_env, url, model) from workspace + pika config."""
    import os

    from core.pika_config import get_pika_config

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
        raise RuntimeError(
            f"API provider requires {env_var} environment variable to be set. "
            "Get an API key from your provider (e.g. https://build.nvidia.com/explore/discover)"
        )

    url = agent.get("api_url") or api_defaults.get(
        "url", "https://integrate.api.nvidia.com/v1/chat/completions"
    )
    model = agent.get("api_model") or api_defaults.get("model", "moonshotai/kimi-k2.5")
    return {"api_key": str(key).strip(), "url": str(url), "model": str(model)}


def invoke_agent_local(
    prompt_name: str,
    template_vars: dict[str, Any],
    *,
    schema_path: Path | None,
    config: dict[str, Any],
    ctx: RuntimeContext,
    retry_instruction: str | None = None,
) -> dict[str, Any]:
    """Invoke agent via local CLI (e.g. Codex). Renders prompt, runs exec, returns parsed JSON."""
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
    output_path = run_dir / "local_output.json"

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
            "provider": "local",
        },
    )

    local_cmd = get_local_command(config)
    stream_output = True
    agent = config.get("agent")
    if isinstance(agent, dict) and "stream_output" in agent:
        stream_output = bool(agent.get("stream_output", True))
    from core.pika_config import get_pika_config

    local_timeout = get_pika_config().get("local", {}).get("exec_timeout_sec", 600)
    reasoning_effort = get_reasoning_effort(config, prompt_name)
    try:
        result = run_local_exec(
            prompt=prompt_text,
            output_schema_path=schema_path_resolved,
            workspace=project_root,
            output_path=output_path,
            command=local_cmd,
            timeout=local_timeout,
            stream_output=stream_output,
            reasoning_effort=reasoning_effort,
        )
        log_lifecycle_event(
            "agent_invoke_local_complete",
            command=ctx.command,
            run_id=ctx.run_id,
            extra={
                "prompt_name": prompt_name,
                "output_path": str(output_path),
            },
        )
        return result
    except subprocess.CalledProcessError as exc:
        log_lifecycle_event(
            "agent_invoke_local_failed",
            command=ctx.command,
            run_id=ctx.run_id,
            extra={
                "prompt_name": prompt_name,
                "output_path": str(output_path),
                "exit_code": exc.returncode,
                "error": exc.stderr or exc.stdout or "no output",
            },
        )
        raise RuntimeError(
            f"Local CLI exec failed (exit {exc.returncode}): {exc.stderr or exc.stdout or 'no output'}"
        ) from exc


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

    result = run_api_invoke(
        prompt=prompt_text,
        api_key=api_cfg["api_key"],
        url=api_cfg["url"],
        model=api_cfg["model"],
        command=ctx.command,
        stream=stream_output,
        stream_output=stream_output,
        output_path=output_path,
    )

    log_lifecycle_event(
        "agent_invoke_api_complete",
        command=ctx.command,
        run_id=ctx.run_id,
        extra={
            "prompt_name": prompt_name,
            "output_path": str(output_path),
        },
    )
    try:
        sys.stderr.write("[PIKA] Agent complete.\n")
        sys.stderr.flush()
    except OSError:
        pass
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
        except ValueError as exc:
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
    import re

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
        from core.pika_config import get_pika_config

        stub_path = get_pika_config().get("stub", {}).get(
            "plan_proposed_sads", "out/agent_artifacts/stub/plan_proposed_sads.csv"
        )
        base["proposed_sads_outline_path"] = stub_path
    elif ctx.command == "map":
        base["mappings"] = _stub_map_mappings_from_csv(
            template_vars.get("design_spec_rows_csv") or ""
        )
    elif ctx.command == "implement":
        if prompt_name == "implement_anchor_planner":
            return {
                "module_tag": "STUB",
                "planned_anchors": [],
                "provided_intents": [],
                "required_intents": [],
            }
        if prompt_name == "implement_anchor_linker":
            return {
                "contracts": [],
                "bindings": [],
                "integration_actions": [],
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
