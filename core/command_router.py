from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class RuntimeContext:
    """Represents runtime context."""
    command: str
    dry_run: bool
    verbose: bool
    command_only_validation: bool
    run_id: str
    project_root: str
    config_path: str


Handler = Callable[[dict[str, Any], RuntimeContext], dict[str, Any]]


def dispatch(command: str, config: dict, ctx: RuntimeContext) -> dict:
    """Return dispatch."""
    handlers: dict[str, Handler] = {
        "load": _run_load,
        "index": _run_index,
        "implement": _run_implement,
        "issue": _run_issue,
    }
    handler = handlers.get(command)
    if handler is None:
        raise ValueError(f"Unknown command: {command}")
    return handler(config, ctx)


def _run_load(config: dict, ctx: RuntimeContext) -> dict:
    """Run load."""
    _ = config
    return _initialized_result("load", ctx)


def _run_index(config: dict, ctx: RuntimeContext) -> dict:
    """Run index."""
    _ = config
    return _initialized_result("index", ctx)


def _run_implement(config: dict, ctx: RuntimeContext) -> dict:
    """Run implement."""
    _ = config
    return _initialized_result("implement", ctx)


def _run_issue(config: dict, ctx: RuntimeContext) -> dict:
    """Run issue."""
    _ = config
    return _initialized_result("issue", ctx)


def _initialized_result(command: str, ctx: RuntimeContext) -> dict[str, Any]:
    """Return initialized result."""
    return {
        "command": command,
        "status": "initialized",
        "dry_run": ctx.dry_run,
        "run_id": ctx.run_id,
    }
