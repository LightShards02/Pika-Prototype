from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.command_router import RuntimeContext


RUN_LOGGER_NAME = "agent_cli.run"
_DEFAULT_LOG_DIR = Path("out/logs")


class _RunContextFilter(logging.Filter):
    #  This filter is not used for filtering records, but for enriching them with the run context.
    """Internal helper class for run context filter."""
    def __init__(self, *, ctx: RuntimeContext) -> None:
        """Initialize run context filter."""
        super().__init__()
        self._defaults = {
            "command": ctx.command,
            "run_id": ctx.run_id,
            "config_path": ctx.config_path,
            "dry_run": ctx.dry_run,
            "command_only_validation": ctx.command_only_validation,
        }

    def filter(self, record: logging.LogRecord) -> bool:
        """Return filter."""
        for key, value in self._defaults.items():
            if not hasattr(record, key):
                setattr(record, key, value)
        if not hasattr(record, "event"):
            setattr(record, "event", "log")
        return True


class _JsonLinesFormatter(logging.Formatter):
    """Internal helper class for json lines formatter."""
    def format(self, record: logging.LogRecord) -> str:
        """Return format."""
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "event": getattr(record, "event", "log"),
            "command": getattr(record, "command", None),
            "run_id": getattr(record, "run_id", None),
            "config_path": getattr(record, "config_path", None),
            "dry_run": getattr(record, "dry_run", None),
            "command_only_validation": getattr(record, "command_only_validation", None),
        }

        status = getattr(record, "status", None)
        if status is not None:
            payload["status"] = status

        error = getattr(record, "error", None)
        if error is not None:
            payload["error"] = error

        return json.dumps(payload, separators=(",", ":"), sort_keys=False)


class _StructuredTextFormatter(logging.Formatter):
    """Internal helper class for structured text formatter."""
    def format(self, record: logging.LogRecord) -> str:
        """Return format."""
        parts = [
            f"timestamp={datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec='milliseconds')}",
            f"level={record.levelname}",
            f"event={getattr(record, 'event', 'log')}",
            f"command={getattr(record, 'command', '')}",
            f"run_id={getattr(record, 'run_id', '')}",
            f"config_path={getattr(record, 'config_path', '')}",
            f"dry_run={getattr(record, 'dry_run', '')}",
            f"command_only_validation={getattr(record, 'command_only_validation', '')}",
        ]
        status = getattr(record, "status", None)
        if status is not None:
            parts.append(f"status={status}")
        error = getattr(record, "error", None)
        if error is not None:
            parts.append(f"error={error}")
        return " ".join(parts)


def _resolve_log_dir(project_root: Path, config: dict[str, Any]) -> Path:
    """Resolve log dir."""
    logging_section = config.get("logging")
    if isinstance(logging_section, dict):
        log_dir = logging_section.get("log_dir")
        if isinstance(log_dir, str) and log_dir.strip():
            candidate = Path(log_dir)
            return candidate.resolve() if candidate.is_absolute() else (project_root / candidate).resolve()

    return (project_root / _DEFAULT_LOG_DIR).resolve()


def _resolve_log_level(config: dict[str, Any], *, verbose: bool) -> int:
    """Resolve log level."""
    logging_section = config.get("logging")
    if not isinstance(logging_section, dict):
        return logging.INFO

    level_key = "verbose_level" if verbose else "level"
    level_name = logging_section.get(level_key)
    if verbose and not isinstance(level_name, str):
        level_name = logging_section.get("level")
    if not isinstance(level_name, str):
        return logging.INFO

    normalized = level_name.upper()
    resolved = getattr(logging, normalized, None)
    return resolved if isinstance(resolved, int) else logging.INFO


def _resolve_json_mode(config: dict[str, Any]) -> bool:
    """Resolve json mode."""
    logging_section = config.get("logging")
    if not isinstance(logging_section, dict):
        return True
    json_enabled = logging_section.get("json")
    return bool(json_enabled) if isinstance(json_enabled, bool) else True


def init_run_logger(*, project_root: Path, config: dict, ctx: RuntimeContext) -> Path:
    """Return init run logger."""
    if not ctx.run_id:
        raise ValueError("RuntimeContext.run_id must be set for run logging.")

    log_dir = _resolve_log_dir(project_root.resolve(), config)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"Failed to create log directory '{log_dir}': {exc}"
        ) from exc

    log_file = (log_dir / f"{ctx.command}_{ctx.run_id}.log").resolve()
    level = _resolve_log_level(config, verbose=ctx.verbose)
    json_mode = _resolve_json_mode(config)

    run_logger = logging.getLogger(RUN_LOGGER_NAME)
    run_logger.setLevel(level)
    run_logger.propagate = False

    for handler in list(run_logger.handlers):
        run_logger.removeHandler(handler)
        handler.close()

    try:
        file_handler = logging.FileHandler(log_file, mode="x", encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Failed to create log file '{log_file}': {exc}") from exc

    file_handler.setLevel(level)
    file_handler.setFormatter(_JsonLinesFormatter() if json_mode else _StructuredTextFormatter())
    file_handler.addFilter(_RunContextFilter(ctx=ctx))
    run_logger.addHandler(file_handler)

    return log_file
