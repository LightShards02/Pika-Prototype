from __future__ import annotations

import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any

import click
import typer

from core.command_router import RuntimeContext, dispatch
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
from core.prompt_registry import PromptRegistry
from core.safety import validate_command_preconditions


PROJECT_ROOT = Path(__file__).resolve().parent

CONFIG_CANDIDATES = [
    Path("config/config.yaml"),
    Path("config/config.example.yaml"),
]

CSV_CONTRACT_PATH_KEYS = {
    "contract_file",
    "contract_path",
    "contracts_file",
    "contracts_path",
    "file_path",
}

SummaryContext = dict[str, Any]


def _resolve_project_root(project_root: str | None) -> Path:
    """Resolve project root."""
    root = Path(project_root).resolve() if project_root else PROJECT_ROOT
    if not root.exists():
        raise ValueError(f"Project root does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"Project root is not a directory: {root}")
    return root


def _default_config_path(project_root: Path) -> Path | None:
    """Return default config path."""
    for candidate in CONFIG_CANDIDATES:
        resolved = (project_root / candidate).resolve()
        if resolved.exists():
            return resolved
    return None


def _resolve_config_path(config: str | None, project_root: Path) -> Path:
    """Resolve config path."""
    if config:
        candidate = Path(config)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        return candidate.resolve()
    selected = _default_config_path(project_root)
    if selected is None:
        raise ValueError(
            "Config path is required. Pass --config PATH or create "
            f"{project_root / 'config/config.yaml'} or "
            f"{project_root / 'config/config.example.yaml'}."
        )
    return selected


def _resolve_schema_path(project_root: Path) -> Path:
    """Resolve config schema path."""
    return (project_root / "config/config.schema.json").resolve()


def _collect_csv_contract_paths(node: Any) -> list[str]:
    """Collect csv contract paths."""
    paths: list[str] = []
    stack: list[Any] = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, value in current.items():
                if key in CSV_CONTRACT_PATH_KEYS and isinstance(value, str):
                    paths.append(value)
                elif isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(current, list):
            stack.extend(current)
    return paths


def _collect_referenced_paths(config: dict[str, Any]) -> list[str]:
    """Collect referenced paths."""
    paths: list[str] = []

    prompts_section = config.get("prompts")
    if isinstance(prompts_section, dict):
        prompt_file = prompts_section.get("prompt_file")
        if isinstance(prompt_file, str):
            paths.append(prompt_file)

    schemas_section = config.get("schemas")
    if isinstance(schemas_section, dict):
        for value in schemas_section.values():
            if isinstance(value, str):
                paths.append(value)

    csv_contracts = config.get("csv_contracts")
    if isinstance(csv_contracts, dict):
        paths.extend(_collect_csv_contract_paths(csv_contracts))

    return paths


def _validate_referenced_files_exist(
    config: dict[str, Any], *, source: str, project_root: Path
) -> None:
    """Validate referenced files exist."""
    for path_value in _collect_referenced_paths(config):
        candidate = Path(path_value)
        resolved = (
            candidate.resolve()
            if candidate.is_absolute()
            else (project_root / candidate).resolve()
        )
        if not resolved.exists():
            raise FileNotFoundError(
                f"Referenced file not found in {source}: {path_value} "
                f"(resolved: {resolved})"
            )
        if not resolved.is_file():
            raise ValueError(
                f"Referenced path is not a file in {source}: {path_value} "
                f"(resolved: {resolved})"
            )


def _emit_summary(
    command_name: str, config_path: Path, runtime_ctx: SummaryContext, status: str
) -> None:
    """Return emit summary."""
    payload = {
        "command": command_name,
        "config_path": str(config_path),
        "project_root": runtime_ctx["project_root"],
        "run_id": runtime_ctx.get("run_id"),
        "dry_run": runtime_ctx["dry_run"],
        "verbose": runtime_ctx["verbose"],
        "command_only_validation": runtime_ctx["command_only_validation"],
        "status": status,
    }
    print(json.dumps(payload, separators=(",", ":"), sort_keys=False))


def _execute_command(
    command_name: str,
    *,
    config: str | None,
    project_root: str | None,
    dry_run: bool,
    verbose: bool,
    command_only_validation: bool,
) -> None:
    """Return execute command."""
    runtime_ctx: SummaryContext = {
        "run_id": None,
        "dry_run": dry_run,
        "verbose": verbose,
        "command_only_validation": command_only_validation,
        "project_root": str(Path(project_root).resolve()) if project_root else str(PROJECT_ROOT),
    }
    summary_config_path = Path("<missing-config>")
    run_logger: logging.Logger | None = None

    try:
        resolved_project_root = _resolve_project_root(project_root)
        runtime_ctx["project_root"] = str(resolved_project_root)
        summary_config_path = (
            (resolved_project_root / config).resolve()
            if config
            else (_default_config_path(resolved_project_root) or Path("<missing-config>"))
        )
        config_path = _resolve_config_path(config, resolved_project_root)
        schema_path = _resolve_schema_path(resolved_project_root)
        summary_config_path = config_path
        config_data = load_and_validate_config(config_path, schema_path=schema_path)

        if command_only_validation:
            prompt_registry = PromptRegistry.from_config(
                config_data, project_root=resolved_project_root
            )
            for prompt_name in prompt_registry.list_prompts():
                _ = prompt_registry.get_schema_path(prompt_name)
            _validate_referenced_files_exist(
                config_data,
                source=str(config_path),
                project_root=resolved_project_root,
            )
            _emit_summary(command_name, config_path, runtime_ctx, "validated_only")
            return

        preflight_ctx = RuntimeContext(
            command=command_name,
            dry_run=dry_run,
            verbose=verbose,
            command_only_validation=command_only_validation,
            run_id="",
            project_root=str(resolved_project_root),
            config_path=str(config_path),
        )
        validate_command_preconditions(command_name, config_data, preflight_ctx)

        run_id = uuid.uuid4().hex
        runtime_ctx["run_id"] = run_id
        router_ctx = RuntimeContext(
            command=command_name,
            dry_run=dry_run,
            verbose=verbose,
            command_only_validation=command_only_validation,
            run_id=run_id,
            project_root=str(resolved_project_root),
            config_path=str(config_path),
        )
        _ = init_run_logger(
            project_root=resolved_project_root, config=config_data, ctx=router_ctx
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
        _emit_summary(command_name, config_path, runtime_ctx, status)
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
    help="Agentic workflow CLI.",
    no_args_is_help=True,
    add_completion=False,
)
agent_app = typer.Typer(
    help="Agent workflow commands.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(agent_app, name="agent")


@agent_app.command("load")
def agent_load_command(
    config: str | None = typer.Option(
        None,
        "--config",
        help=(
            "Path to config YAML. Defaults to config/config.yaml, then "
            "config/config.example.yaml."
        ),
    ),
    project_root: str | None = typer.Option(
        None,
        "--project-root",
        help=(
            "Project root used to resolve config defaults, schema, and all runtime "
            "validations. Defaults to the CLI repository root."
        ),
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without side effects."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose logs."),
    command_only_validation: bool = typer.Option(
        False,
        "--command-only-validation",
        help=(
            "Load config, validate config schema, and validate referenced files only; "
            "skip command execution."
        ),
    ),
) -> None:
    """Handle the agent load command command."""
    _execute_command(
        "load",
        config=config,
        project_root=project_root,
        dry_run=dry_run,
        verbose=verbose,
        command_only_validation=command_only_validation,
    )


@agent_app.command("index")
def agent_index_command(
    config: str | None = typer.Option(
        None,
        "--config",
        help=(
            "Path to config YAML. Defaults to config/config.yaml, then "
            "config/config.example.yaml."
        ),
    ),
    project_root: str | None = typer.Option(
        None,
        "--project-root",
        help=(
            "Project root used to resolve config defaults, schema, and all runtime "
            "validations. Defaults to the CLI repository root."
        ),
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without side effects."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose logs."),
    command_only_validation: bool = typer.Option(
        False,
        "--command-only-validation",
        help=(
            "Load config, validate config schema, and validate referenced files only; "
            "skip command execution."
        ),
    ),
) -> None:
    """Handle the agent index command command."""
    _execute_command(
        "index",
        config=config,
        project_root=project_root,
        dry_run=dry_run,
        verbose=verbose,
        command_only_validation=command_only_validation,
    )


@agent_app.command("implement")
def agent_implement_command(
    config: str | None = typer.Option(
        None,
        "--config",
        help=(
            "Path to config YAML. Defaults to config/config.yaml, then "
            "config/config.example.yaml."
        ),
    ),
    project_root: str | None = typer.Option(
        None,
        "--project-root",
        help=(
            "Project root used to resolve config defaults, schema, and all runtime "
            "validations. Defaults to the CLI repository root."
        ),
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without side effects."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose logs."),
    command_only_validation: bool = typer.Option(
        False,
        "--command-only-validation",
        help=(
            "Load config, validate config schema, and validate referenced files only; "
            "skip command execution."
        ),
    ),
) -> None:
    """Handle the agent implement command command."""
    _execute_command(
        "implement",
        config=config,
        project_root=project_root,
        dry_run=dry_run,
        verbose=verbose,
        command_only_validation=command_only_validation,
    )


@agent_app.command("issue")
def agent_issue_command(
    config: str | None = typer.Option(
        None,
        "--config",
        help=(
            "Path to config YAML. Defaults to config/config.yaml, then "
            "config/config.example.yaml."
        ),
    ),
    project_root: str | None = typer.Option(
        None,
        "--project-root",
        help=(
            "Project root used to resolve config defaults, schema, and all runtime "
            "validations. Defaults to the CLI repository root."
        ),
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without side effects."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose logs."),
    command_only_validation: bool = typer.Option(
        False,
        "--command-only-validation",
        help=(
            "Load config, validate config schema, and validate referenced files only; "
            "skip command execution."
        ),
    ),
) -> None:
    """Handle the agent issue command command."""
    _execute_command(
        "issue",
        config=config,
        project_root=project_root,
        dry_run=dry_run,
        verbose=verbose,
        command_only_validation=command_only_validation,
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
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
