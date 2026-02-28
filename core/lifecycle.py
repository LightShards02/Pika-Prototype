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


def resolve_output_schema_path(
    config: dict[str, Any], workspace_root: Path, schema_key: str
) -> Path | None:
    """Resolve output schema path from config. Tries workspace first, then PIKA root."""
    schemas = config.get("schemas", {})
    if not isinstance(schemas, dict) or schema_key not in schemas:
        return None
    path_val = schemas[schema_key]
    if not isinstance(path_val, str) or not path_val.strip():
        return None
    return resolve_schema_path(path_val, schema_key, workspace_root)


def _get_project_context_filename(config: dict[str, Any]) -> str:
    """Return project context filename from config (required in inputs)."""
    inputs = config.get("inputs")
    if isinstance(inputs, dict):
        val = inputs.get("project_context_filename")
        if isinstance(val, str) and val.strip():
            return val.strip()
    raise ValueError("inputs.project_context_filename is required in config")


def _get_extra_prompt_filename(config: dict[str, Any]) -> str | None:
    """Return extra prompt filename from config. None when not configured."""
    inputs = config.get("inputs")
    if isinstance(inputs, dict):
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
    filename = _get_extra_prompt_filename(config)
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


def resolve_input_path(
    config: dict[str, Any],
    project_root: Path,
    key: str,
    *,
    overrides: dict[str, str] | None = None,
) -> Path | None:
    """Resolve an input path from CLI overrides or config inputs section.

    Args:
        config: Full PIKA config.
        project_root: Project root path.
        key: Input key (e.g. raw_sads_path, design_spec_path, srs_path, issue_tracking_path).
        overrides: Optional dict of key -> path from CLI args. Takes precedence over config.

    Returns:
        Resolved Path or None if not configured.
    """
    if overrides:
        value = overrides.get(key)
        if isinstance(value, str) and value.strip():
            candidate = Path(value)
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / value).resolve()
    inputs = config.get("inputs")
    if not isinstance(inputs, dict):
        return None
    value = inputs.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate.resolve()
    return (project_root / value).resolve()


def resolve_codebase_dir_path(
    config: dict[str, Any],
    project_root: Path,
    ctx: RuntimeContext,
) -> Path:
    """Resolve codebase directory path. Defaults to project_root when not provided.

    Uses --codebase-dir or inputs.codebase_dir if set and the path exists;
    otherwise returns project_root.
    """
    codebase_path = resolve_input_path(
        config, project_root, "codebase_dir", overrides=ctx.input_overrides
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
        config, project_root, "project_context_path", overrides=ctx.input_overrides
    )
    if context_path is not None and context_path.exists() and context_path.is_file():
        return context_path
    filename = _get_project_context_filename(config)
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

    filename = _get_project_context_filename(config)
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
) -> Path | None:
    """Resolve an output path from config outputs section."""
    outputs = config.get("outputs")
    if not isinstance(outputs, dict):
        return None
    spec = outputs.get(output_key)
    if not isinstance(spec, dict):
        return None
    path_value = spec.get("path")
    if not isinstance(path_value, str) or not path_value.strip():
        return None
    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate.resolve()
    return (project_root / path_value).resolve()


def resolve_intermediate_map_dir(config: dict[str, Any], project_root: Path) -> Path:
    """Resolve directory for per-subunit map outputs.

    Uses outputs.intermediate_map_dir if configured; otherwise falls back to
    pika_config default_outputs.intermediate_map_dir (out/intermediate/map).
    """
    from core.pika_config import get_pika_config

    resolved = resolve_output_path(config, project_root, "intermediate_map_dir")
    if resolved is not None:
        return resolved
    default = get_pika_config().get("default_outputs", {}).get(
        "intermediate_map_dir", "out/intermediate/map"
    )
    return (project_root / default).resolve()


def resolve_agent_input_codebase_content_dir(
    config: dict[str, Any], project_root: Path
) -> Path:
    """Resolve directory for writing codebase_content before each agent invocation.

    Uses outputs.agent_input_codebase_content_dir if configured; otherwise falls
    back to pika_config default_outputs.agent_input_codebase_content_dir
    (out/agent_input/codebase_content).
    """
    from core.pika_config import get_pika_config

    resolved = resolve_output_path(config, project_root, "agent_input_codebase_content_dir")
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
    return {k: v for k, v in output.items() if k in root_props}


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
    instead of current time (e.g. for last_indexed_at = agent invocation time).
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

    artifacts_dir = resolve_output_path(config, project_root, "agent_artifacts_dir")
    run_dir = (artifacts_dir / ctx.run_id) if (artifacts_dir and ctx.run_id) else artifacts_dir
    if not run_dir:
        run_dir = project_root / "out" / "agent_artifacts" / (ctx.run_id or "run")
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
    try:
        result = run_local_exec(
            prompt=prompt_text,
            output_schema_path=schema_path_resolved,
            workspace=project_root,
            output_path=output_path,
            command=local_cmd,
            timeout=local_timeout,
            stream_output=stream_output,
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

    artifacts_dir = resolve_output_path(config, project_root, "agent_artifacts_dir")
    run_dir = (artifacts_dir / ctx.run_id) if (artifacts_dir and ctx.run_id) else artifacts_dir
    if not run_dir:
        run_dir = project_root / "out" / "agent_artifacts" / (ctx.run_id or "run")
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
    out_dir = resolve_agent_input_codebase_content_dir(config, project_root)
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
    _ = prompt_name
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
        base["diffs"] = []  # Each diff has path, action, diff_path, spec_ids
        base["unclarities"] = []
    elif ctx.command == "resolve_plan":
        base["mappings"] = {"IS01": {"spec_ids": [], "notes": "Stub"}}
    return base
