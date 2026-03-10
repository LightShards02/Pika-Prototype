"""Command router: dispatches PIKA commands to handlers per PROJECT_CONTEXT.

Router responsibilities:
1. command → handler mapping
2. shared error handling
3. consistent structured logging events
4. consistent exit codes (via result status)
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from core.context import RuntimeContext
from core.lifecycle import get_run_logger, log_lifecycle_event

RUN_LOGGER_NAME = "agent_cli.run"

# Exit code constants for consistent CLI behavior
EXIT_SUCCESS = 0
EXIT_CONFIG_ERROR = 1
EXIT_SAFETY_ERROR = 2
EXIT_HANDLER_ERROR = 3
EXIT_BLOCKED = 4
EXIT_SKIPPED = 5
EXIT_PARTIAL = 6  # Some subunits/items succeeded, others failed


Handler = Callable[[dict[str, Any], RuntimeContext], dict[str, Any]]


def _get_handlers() -> dict[str, Handler]:
    """Return command → handler mapping."""
    from handlers.plan import run_plan
    from handlers.format import run_format
    from handlers.review import run_review
    from handlers.map import run_map
    from handlers.implement import run_implement
    from handlers.resolve_plan import run_resolve_plan
    from handlers.resolve import run_resolve

    return {
        "plan": run_plan,
        "format": run_format,
        "review": run_review,
        "map": run_map,
        "implement": run_implement,
        "resolve_plan": run_resolve_plan,
        "resolve": run_resolve,
    }


def dispatch(command: str, config: dict[str, Any], ctx: RuntimeContext) -> dict[str, Any]:
    """Dispatch command to handler with shared error handling and logging.

    Returns result dict with at least: command, status.
    Status values: completed, blocked, skipped, failed, initialized.
    """
    handlers = _get_handlers()
    handler = handlers.get(command)
    if handler is None:
        raise ValueError(f"Unknown command: {command}")

    log_lifecycle_event("router_dispatch", command=command, run_id=ctx.run_id)

    try:
        result = handler(config, ctx)
        status = result.get("status", "completed")
        log_lifecycle_event(
            "router_complete",
            command=command,
            run_id=ctx.run_id,
            extra={"status": status},
        )
        return result
    except Exception as exc:
        logger = get_run_logger()
        logger.exception("Handler failed: %s", exc)
        log_lifecycle_event(
            "router_error",
            command=command,
            run_id=ctx.run_id,
            extra={"error": str(exc), "status": "failed"},
        )
        raise


def status_to_exit_code(status: str) -> int:
    """Map result status to exit code for CLI."""
    if status in ("completed", "initialized", "validated_only"):
        return EXIT_SUCCESS
    if status == "blocked":
        return EXIT_BLOCKED
    if status == "skipped":
        return EXIT_SKIPPED
    if status == "failed":
        return EXIT_HANDLER_ERROR
    if status == "partial":
        return EXIT_PARTIAL
    return EXIT_SUCCESS
