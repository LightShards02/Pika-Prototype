"""PIKA CLI: contract-first, schema-driven agentic workflow per PROJECT_CONTEXT."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

import click
import typer

from core.command_router import dispatch
from core.context import RuntimeContext
from core.config_loader import load_and_validate_config
from core.errors import (
    ConfigNotFoundError,
    ConfigParseError,
    ConfigSchemaValidationError,
    PromptFileNotFoundError,
    PromptNotFoundError,
    PromptParseError,
    PromptValidationError,
)
from core.logger import RUN_LOGGER_NAME, init_run_logger
from core.time_utils import generate_run_id
from core.lifecycle import (
    find_most_recent_blocked_run_id,
    resolve_agent_runs_dir_for_command,
)
from core.pika_paths import get_config_schema_path
from core.resolution import (
    build_resolved_decisions_context,
    load_resolution_file,
    validate_resolutions,
)
from core.prompt_registry import PromptRegistry
from core.pika_config import get_pika_config
from core.safety import validate_command_preconditions

# Workspace root: the project PIKA is used to build (config, outputs, inputs). Required.
# When --config not provided, look under project root. Candidates from pika config.

SummaryContext = dict[str, Any]


def _resolve_workspace_root(workspace_root: str | None) -> Path:
    """Resolve workspace root (the project PIKA is used to build).

    Required: must be provided. The workspace root contains the project's config,
    outputs, and inputs.
    """
    if not workspace_root or not str(workspace_root).strip():
        raise ValueError(
            "Workspace root is required. Pass --project-root PATH (directory containing "
            "project config and outputs)."
        )
    root = Path(workspace_root).resolve()
    if not root.exists():
        raise ValueError(f"Workspace root does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"Workspace root is not a directory: {root}")
    return root


def _default_config_path(workspace_root: Path) -> Path | None:
    """Return default config path from candidates under workspace root."""
    candidates = [
        Path(c) for c in get_pika_config().get("config_candidates", [])
    ] or [Path("config.yaml"), Path("config/config.yaml"), Path("config/config.example.yaml")]
    for candidate in candidates:
        resolved = (workspace_root / candidate).resolve()
        if resolved.exists():
            return resolved
    return None


def _resolve_config_path(config: str | None, workspace_root: Path) -> Path:
    """Resolve config file path. Config lives under workspace root (project-variable)."""
    if config:
        candidate = Path(config)
        if not candidate.is_absolute():
            candidate = workspace_root / candidate
        return candidate.resolve()
    selected = _default_config_path(workspace_root)
    if selected is None:
        raise ValueError(
            "Config path is required. Pass --config PATH or create "
            f"{workspace_root / 'config.yaml'} or "
            f"{workspace_root / 'config/config.yaml'} or "
            f"{workspace_root / 'config/config.example.yaml'} under the project root."
        )
    return selected


def _collect_referenced_paths(config: dict[str, Any]) -> list[str]:
    """Collect referenced file paths from config.

    Prompts, schemas, and csv_contracts are now resolved from pika.yaml.
    This function returns workspace-level referenced paths (currently none).
    """
    return []


def _validate_referenced_files_exist(
    config: dict[str, Any], *, source: str, workspace_root: Path
) -> None:
    """Validate all referenced files exist.

    Prompts, schemas, and csv_contracts are now resolved from pika.yaml
    and validated there. No workspace-level file references remain.
    """



def _emit_summary(
    command_name: str,
    config_path: Path,
    runtime_ctx: SummaryContext,
    status: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit JSON summary to stdout."""
    payload = {
        "command": command_name,
        "config_path": str(config_path),
        "workspace_root": runtime_ctx["workspace_root"],
        "run_id": runtime_ctx.get("run_id"),
        "dry_run": runtime_ctx["dry_run"],
        "verbose": runtime_ctx["verbose"],
        "command_only_validation": runtime_ctx["command_only_validation"],
        "status": status,
    }
    if extra:
        for key, value in extra.items():
            if key not in payload:
                payload[key] = value
    print(json.dumps(payload, separators=(",", ":"), sort_keys=False))


def _execute_command(
    command_name: str,
    *,
    config: str | None,
    project_root: str | None,
    dry_run: bool,
    verbose: bool,
    command_only_validation: bool,
    input_overrides: dict[str, str] | None = None,
    resume_run_id: str | None = None,
    auto_resume: bool = False,
) -> None:
    """Execute command with config load, validation, and dispatch."""
    resolved_workspace_root = _resolve_workspace_root(project_root)
    runtime_ctx: SummaryContext = {
        "run_id": None,
        "dry_run": dry_run,
        "verbose": verbose,
        "command_only_validation": command_only_validation,
        "workspace_root": str(resolved_workspace_root),
    }
    summary_config_path = Path("<missing-config>")
    run_logger: logging.Logger | None = None

    try:
        summary_config_path = (
            (resolved_workspace_root / config).resolve()
            if config
            else (_default_config_path(resolved_workspace_root) or Path("<missing-config>"))
        )
        config_path = _resolve_config_path(config, resolved_workspace_root)
        schema_path = get_config_schema_path()  # PIKA-internal, always from PIKA root
        summary_config_path = config_path
        config_data = load_and_validate_config(config_path, schema_path=schema_path)

        if command_only_validation:
            prompt_registry = PromptRegistry.from_config(config_data)
            for prompt_name in prompt_registry.list_prompts():
                _ = prompt_registry.get_schema_path(prompt_name)
            _validate_referenced_files_exist(
                config_data,
                source=str(config_path),
                workspace_root=resolved_workspace_root,
            )
            _emit_summary(command_name, config_path, runtime_ctx, "validated_only")
            return

        overrides = input_overrides or {}

        if auto_resume and not resume_run_id:
            auto_run_id = find_most_recent_blocked_run_id(
                config_data, resolved_workspace_root, command_name
            )
            if auto_run_id:
                typer.secho(
                    f"Auto-resuming most recent blocked run: {auto_run_id}",
                    fg=typer.colors.CYAN,
                    err=True,
                )
                resume_run_id = auto_run_id
            else:
                raise ValueError(
                    f"--resume specified but no blocked run found for command '{command_name}'."
                )

        run_id = resume_run_id or generate_run_id()
        resolved_decisions: str | None = None
        if resume_run_id:
            if command_name in ("implement", "plan", "map", "resolve_plan", "refine"):
                run_dir = resolve_agent_runs_dir_for_command(
                    config_data, Path(resolved_workspace_root), command_name, resume_run_id
                )
                if not run_dir.exists():
                    raise ValueError(
                        f"Cannot resume: run_id '{resume_run_id}' not found for command '{command_name}' "
                        f"at {run_dir}"
                    )

                run_meta_path = run_dir / "run_meta.json"
                if not run_meta_path.exists():
                    raise ValueError(
                        f"Cannot resume: missing run_meta.json for run_id '{resume_run_id}' at {run_meta_path}"
                    )
                try:
                    run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
                except Exception as exc:
                    raise ValueError(
                        f"Cannot resume: invalid run_meta.json for run_id '{resume_run_id}' ({exc})"
                    ) from exc
                blocked_stage = str(run_meta.get("blocked_at_stage", "")).strip()
                if not blocked_stage:
                    raise ValueError(
                        f"Cannot resume: run_id '{resume_run_id}' is not marked as blocked "
                        "(missing blocked_at_stage in run_meta.json)."
                    )

                data = load_resolution_file(run_dir)
                if not data:
                    raise ValueError(
                        f"Cannot resume: missing or unreadable manual_resolution/resolutions.yaml for "
                        f"run_id '{resume_run_id}'."
                    )
                valid, errors = validate_resolutions(data)
                if not valid:
                    preview = "; ".join(errors[:3]) if errors else "unresolved items"
                    raise ValueError(
                        f"Cannot resume: resolutions.yaml is not fully resolved for run_id '{resume_run_id}': {preview}"
                    )
                edit_count = 0
                for item in data.get("items", []):
                    if not isinstance(item, dict):
                        continue
                    if item.get("source") != "validation":
                        continue
                    if not (item.get("manual_edit_text") or "").strip():
                        continue
                    edit_count += 1
                if edit_count > 0:
                    typer.secho(
                        "WARNING: "
                        f"{edit_count} item(s) have manual spec edits. "
                        "Resume will re-validate and may block again if edits are insufficient.",
                        fg=typer.colors.YELLOW,
                        err=True,
                    )
                raw = build_resolved_decisions_context(data)
                resolved_decisions = (
                    "## Resolved Decisions\n\n"
                    "The following ambiguities were previously flagged and resolved by the user. "
                    "Honor these as hard constraints. Do NOT re-emit them as manual_resolution_items.\n\n"
                    f"{raw}"
                ) if raw else ""

        preflight_ctx = RuntimeContext(
            command=command_name,
            dry_run=dry_run,
            verbose=verbose,
            command_only_validation=command_only_validation,
            run_id=run_id,
            project_root=str(resolved_workspace_root),  # workspace root = project being built
            config_path=str(config_path),
            input_overrides=overrides,
            resume_run_id=resume_run_id,
            resolved_decisions=resolved_decisions,
        )
        validate_command_preconditions(command_name, config_data, preflight_ctx)

        runtime_ctx["run_id"] = run_id
        router_ctx = RuntimeContext(
            command=command_name,
            dry_run=dry_run,
            verbose=verbose,
            command_only_validation=command_only_validation,
            run_id=run_id,
            project_root=str(resolved_workspace_root),  # workspace root = project being built
            config_path=str(config_path),
            input_overrides=overrides,
            resume_run_id=resume_run_id,
            resolved_decisions=resolved_decisions,
        )
        _ = init_run_logger(
            project_root=resolved_workspace_root, config=config_data, ctx=router_ctx
        )
        run_logger = logging.getLogger(RUN_LOGGER_NAME)
        run_event_level = run_logger.getEffectiveLevel()
        run_logger.log(run_event_level, "command_start", extra={"event": "command_start"})
        dispatch_result = dispatch(command_name, config_data, router_ctx)
        status = dispatch_result.get("status", "initialized")
        run_logger.log(
            run_event_level,
            "command_end",
            extra={"event": "command_end", "status": status},
        )
        _emit_summary(command_name, config_path, runtime_ctx, status, extra=dispatch_result)
    except Exception as exc:
        if run_logger is not None:
            run_logger.log(
                run_logger.getEffectiveLevel(),
                "command_end",
                extra={
                    "event": "command_end",
                    "status": "failed",
                    "error": str(exc),
                },
            )
        _emit_summary(command_name, summary_config_path, runtime_ctx, "failed")
        raise


app = typer.Typer(
    help="PIKA: contract-first, schema-driven agentic workflow CLI.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def _root_callback(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-V", help="Show version and exit."),
) -> None:
    """Root callback: handle --version before dispatching to subcommands."""
    if version:
        v = get_pika_config().get("version", "0.0.0")
        typer.echo(v)
        raise typer.Exit(0)


@app.command("login")
def login_command() -> None:
    """Authenticate with OpenAI Codex via OAuth (for local provider with openai-codex sub-provider)."""
    try:
        from loca.auth import run_login_flow
        run_login_flow()
        typer.secho("Login successful.", fg=typer.colors.GREEN)
    except Exception as exc:  # noqa: BLE001
        typer.secho(f"Login failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc


agent_app = typer.Typer(
    help="Agent workflow commands (plan, format, review, map, implement, resolve_plan).",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(agent_app, name="agent")


@agent_app.command("plan")
def agent_plan_command(
    config: str | None = typer.Option(None, "--config", help="Path to config YAML."),
    project_root: str = typer.Option(..., "--project-root", help="Workspace root (required): directory containing project config and outputs."),
    srs: str | None = typer.Option(None, "--srs", help="Path to SRS file. Relative to project root or absolute."),
    codebase_dir: str | None = typer.Option(None, "--codebase-dir", help="Path to codebase/source directory. Absolute or relative to project root."),
    project_context: str | None = typer.Option(None, "--project-context", help="Path to project context file (e.g. PROJECT_CONTEXT.md). Absolute or relative to project root."),
    resume: str | None = typer.Option(None, "--resume", help="Resume a blocked run by run ID (after resolving manual items)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without side effects."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose logs."),
    command_only_validation: bool = typer.Option(
        False, "--command-only-validation", help="Validate only; skip execution."
    ),
) -> None:
    """Project Designer (Phase 0.a): produce project plan and/or design outline from SRS."""
    overrides = {}
    if srs:
        overrides["srs_path"] = srs
    if codebase_dir:
        overrides["codebase_dir"] = codebase_dir
    if project_context:
        overrides["project_context_path"] = project_context
    _execute_command(
        "plan",
        config=config,
        project_root=project_root,
        dry_run=dry_run,
        verbose=verbose,
        command_only_validation=command_only_validation,
        input_overrides=overrides if overrides else None,
        resume_run_id=resume,
    )


@agent_app.command("format")
def agent_format_command(
    config: str | None = typer.Option(None, "--config", help="Path to config YAML."),
    project_root: str = typer.Option(..., "--project-root", help="Workspace root (required): directory containing project config and outputs."),
    design_spec: str | None = typer.Option(None, "--design-spec", help="Path to Raw SADS or design spec (CSV/XLSX). Relative to project root or absolute."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without side effects."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose logs."),
    command_only_validation: bool = typer.Option(
        False, "--command-only-validation", help="Validate only; skip execution."
    ),
) -> None:
    """SADS Formatter (Phase 0.b): normalize Raw SADS into Draft Formatted SADS (deterministic, no LLM)."""
    overrides = None
    if design_spec:
        overrides = {"design_spec_path": design_spec}
    _execute_command(
        "format",
        config=config,
        project_root=project_root,
        dry_run=dry_run,
        verbose=verbose,
        command_only_validation=command_only_validation,
        input_overrides=overrides,
    )


@agent_app.command("review")
def agent_review_command(
    config: str | None = typer.Option(None, "--config", help="Path to config YAML."),
    project_root: str = typer.Option(..., "--project-root", help="Workspace root (required): directory containing project config and outputs."),
    design_spec: str | None = typer.Option(None, "--design-spec", help="Path to Draft Formatted SADS. Relative to project root or absolute."),
    srs: str | None = typer.Option(None, "--srs", help="Path to SRS file. Relative to project root or absolute."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without side effects."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose logs."),
    command_only_validation: bool = typer.Option(
        False, "--command-only-validation", help="Validate only; skip execution."
    ),
) -> None:
    """Design Reviewer: review Draft Formatted SADS for gaps, contradictions, ambiguities."""
    overrides = {}
    if design_spec:
        overrides["design_spec_path"] = design_spec
    if srs:
        overrides["srs_path"] = srs
    _execute_command(
        "review",
        config=config,
        project_root=project_root,
        dry_run=dry_run,
        verbose=verbose,
        command_only_validation=command_only_validation,
        input_overrides=overrides if overrides else None,
    )


@agent_app.command("map")
def agent_map_command(
    config: str | None = typer.Option(None, "--config", help="Path to config YAML."),
    project_root: str = typer.Option(..., "--project-root", help="Workspace root (required): directory containing project config and outputs."),
    design_spec: str | None = typer.Option(None, "--design-spec", help="Path to Formatted SADS. Relative to project root or absolute."),
    codebase_dir: str | None = typer.Option(None, "--codebase-dir", help="Path to codebase/source directory. Absolute or relative to project root."),
    project_context: str | None = typer.Option(None, "--project-context", help="Path to project context file (e.g. PROJECT_CONTEXT.md). Absolute or relative to project root."),
    extra_prompt: str | None = typer.Option(
        None,
        "--extra-prompt",
        help="Path to extra prompt .md file. Fallback: project root / inputs.extra_prompt_filename when configured. When both omitted, no extra section.",
    ),
    force_remap: bool = typer.Option(False, "--force-remap", help="Re-map all specs including already mapped."),
    max_acceptance_chars: int | None = typer.Option(None, "--max-acceptance-chars", help="Truncate acceptance_criteria to N chars (0 = unlimited). Overrides config."),
    apply_existing_outputs: str | None = typer.Option(
        None, "--apply-existing-outputs",
        help="Path to directory of map output JSON files. Skips agent invocation; merges and applies downstream processing.",
    ),
    resume: str | None = typer.Option(None, "--resume", help="Resume a blocked run by run ID (after resolving manual items)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without side effects."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose logs."),
    command_only_validation: bool = typer.Option(
        False, "--command-only-validation", help="Validate only; skip execution."
    ),
) -> None:
    """SADS Mapper (Phase 2): produce traceability mappings from spec to code symbols."""
    overrides = {}
    if design_spec:
        overrides["design_spec_path"] = design_spec
    if codebase_dir:
        overrides["codebase_dir"] = codebase_dir
    if project_context:
        overrides["project_context_path"] = project_context
    if extra_prompt:
        overrides["extra_prompt_path"] = extra_prompt
    if force_remap:
        overrides["force_remap"] = "true"
    if max_acceptance_chars is not None:
        overrides["max_acceptance_chars"] = str(max_acceptance_chars)
    if apply_existing_outputs:
        overrides["apply_existing_outputs"] = apply_existing_outputs
    _execute_command(
        "map",
        config=config,
        project_root=project_root,
        dry_run=dry_run,
        verbose=verbose,
        command_only_validation=command_only_validation,
        input_overrides=overrides if overrides else None,
        resume_run_id=resume,
    )


@agent_app.command("implement")
def agent_implement_command(
    config: str | None = typer.Option(None, "--config", help="Path to config YAML."),
    project_root: str = typer.Option(..., "--project-root", help="Workspace root (required): directory containing project config and outputs."),
    design_spec: str | None = typer.Option(None, "--design-spec", help="Path to Formatted SADS. Relative to project root or absolute."),
    codebase_dir: str | None = typer.Option(None, "--codebase-dir", help="Path to codebase/source directory. Absolute or relative to project root."),
    project_context: str | None = typer.Option(None, "--project-context", help="Path to project context file (e.g. PROJECT_CONTEXT.md). Absolute or relative to project root."),
    resume: bool = typer.Option(False, "--resume", help="Resume the most recent blocked run. Use --run to specify a run ID."),
    run: str | None = typer.Option(None, "--run", help="Specific run ID to resume (requires --resume)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without side effects."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose logs."),
    command_only_validation: bool = typer.Option(
        False, "--command-only-validation", help="Validate only; skip execution."
    ),
) -> None:
    """Implementer (Phase 1): implement Formatted SADS by producing diffs with spec_id traceability."""
    if run and not resume:
        raise typer.BadParameter("--run requires --resume to be set.", param_hint="'--run'")
    overrides = {}
    if design_spec:
        overrides["design_spec_path"] = design_spec
    if codebase_dir:
        overrides["codebase_dir"] = codebase_dir
    if project_context:
        overrides["project_context_path"] = project_context
    _execute_command(
        "implement",
        config=config,
        project_root=project_root,
        dry_run=dry_run,
        verbose=verbose,
        command_only_validation=command_only_validation,
        input_overrides=overrides if overrides else None,
        resume_run_id=run if resume else None,
        auto_resume=resume and not run,
    )


@agent_app.command("resolve")
def agent_resolve_command(
    run: str | None = typer.Option(None, "--run", help="Run ID to resolve. Omit to auto-resolve the most recent blocked run."),
    config: str | None = typer.Option(None, "--config", help="Path to config YAML."),
    project_root: str = typer.Option(..., "--project-root", help="Workspace root (required)."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose logs."),
    apply_only: bool = typer.Option(False, "--apply-only", help="Skip interactive TUI; validate and apply a pre-filled resolutions.yaml."),
    invoke_editor: bool = typer.Option(False, "--invoke-editor", help="Invoke spec_editor agent for a single item and return editor_output JSON. Requires --run and --item-index."),
    item_index: int | None = typer.Option(None, "--item-index", help="Item index in resolutions.yaml to invoke the editor for (used with --invoke-editor)."),
    user_guide: str | None = typer.Option(None, "--user-guide", help="Optional free-text guidance for the spec_editor agent (used with --invoke-editor)."),
) -> None:
    """Interactive manual resolution for blocked runs. Presents items one by one until all are resolved."""
    if invoke_editor and item_index is None:
        raise typer.BadParameter("--invoke-editor requires --item-index.", param_hint="'--item-index'")
    overrides: dict[str, str] = {}
    if run:
        overrides["run_id"] = run
    if apply_only:
        overrides["apply_only"] = "true"
    if invoke_editor:
        overrides["invoke_editor"] = "true"
        overrides["item_index"] = str(item_index)
        if user_guide:
            overrides["user_guide"] = user_guide
    _execute_command(
        "resolve",
        config=config,
        project_root=project_root,
        dry_run=False,
        verbose=verbose,
        command_only_validation=False,
        input_overrides=overrides if overrides else None,
    )


@agent_app.command("refine")
def agent_refine_command(
    config: str | None = typer.Option(None, "--config", help="Path to config YAML."),
    project_root: str = typer.Option(..., "--project-root", help="Workspace root (required): directory containing project config and outputs."),
    design_spec: str | None = typer.Option(None, "--design-spec", help="Path to design spec (SADS CSV). Relative to project root or absolute."),
    resume: bool = typer.Option(False, "--resume", help="Resume the most recent blocked run. Use --run to specify a run ID."),
    run: str | None = typer.Option(None, "--run", help="Specific run ID to resume (requires --resume)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without side effects."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose logs."),
    command_only_validation: bool = typer.Option(
        False, "--command-only-validation", help="Validate only; skip execution."
    ),
) -> None:
    """Spec quality review: ambiguity detection, testability audit, and refinement suggestions."""
    if run and not resume:
        raise typer.BadParameter("--run requires --resume to be set.", param_hint="'--run'")
    overrides = {}
    if design_spec:
        overrides["design_spec_path"] = design_spec
    _execute_command(
        "refine",
        config=config,
        project_root=project_root,
        dry_run=dry_run,
        verbose=verbose,
        command_only_validation=command_only_validation,
        input_overrides=overrides if overrides else None,
        resume_run_id=run if resume else None,
        auto_resume=resume and not run,
    )


@agent_app.command("resolve_plan")
def agent_resolve_plan_command(
    config: str | None = typer.Option(None, "--config", help="Path to config YAML."),
    project_root: str = typer.Option(..., "--project-root", help="Workspace root (required): directory containing project config and outputs."),
    issue_tracking: str | None = typer.Option(None, "--issue-tracking", help="Path to Implementation Issue Tracker. Relative to project root or absolute."),
    design_spec: str | None = typer.Option(None, "--design-spec", help="Path to Formatted SADS. Relative to project root or absolute."),
    resume: str | None = typer.Option(None, "--resume", help="Resume a blocked run by run ID (after resolving manual items)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without side effects."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose logs."),
    command_only_validation: bool = typer.Option(
        False, "--command-only-validation", help="Validate only; skip execution."
    ),
) -> None:
    """Resolution Organizer (Phase 2/4): produce issue-to-spec mapping, prioritization, and resolution plans."""
    overrides = {}
    if issue_tracking:
        overrides["issue_tracking_path"] = issue_tracking
    if design_spec:
        overrides["design_spec_path"] = design_spec
    _execute_command(
        "resolve_plan",
        config=config,
        project_root=project_root,
        dry_run=dry_run,
        verbose=verbose,
        command_only_validation=command_only_validation,
        input_overrides=overrides if overrides else None,
        resume_run_id=resume,
    )


def main() -> int:
    """Run the main entry point."""
    try:
        app(standalone_mode=False)
        return 0
    except (
        ConfigNotFoundError,
        ConfigParseError,
        ConfigSchemaValidationError,
        PromptFileNotFoundError,
        PromptParseError,
        PromptValidationError,
        PromptNotFoundError,
        ValueError,
        FileNotFoundError,
        RuntimeError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except click.ClickException as exc:
        print(f"ERROR: {exc.format_message()}", file=sys.stderr)
        return exc.exit_code
    except click.Abort:
        print("ERROR: Aborted.", file=sys.stderr)
        return 1
    except typer.Exit as exc:
        return exc.exit_code
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
