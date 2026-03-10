from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from core.time_utils import format_timestamp_local_minutes
from pathlib import Path
from typing import Any

from core.context import RuntimeContext


RUN_LOGGER_NAME = "agent_cli.run"

# Event-specific keys: only these extra keys are included per event type.
# Prevents unwanted keys from one event leaking into another.
# Unknown events use _DEFAULT_EVENT_KEYS (status, error only).
_EVENT_KEYS: dict[str, tuple[str, ...]] = {
    "command_start": (),
    "command_end": ("status", "error"),
    "router_dispatch": (),
    "router_complete": ("status",),
    "router_error": ("error", "status"),
    "lifecycle_load_inputs": (),
    "lifecycle_preprocess": (),
    "lifecycle_translate": (),
    "lifecycle_invoke_agent": (
        "prompt_name", "provider", "attempt", "max_attempts",
        "subunit", "row_count",
    ),
    "lifecycle_validate_output": (
        "prompt_name", "schema_path", "validation_result", "validation_error",
        "attempt", "max_attempts",
    ),
    "lifecycle_schema_validation_retry": ("attempt", "max_retries", "error"),
    "lifecycle_manual_resolution": (),
    "manual_resolution_item": ("index", "entity_type", "entity_id"),
    "agent_invoke_local": (
        "prompt_name", "prompt_preview", "output_path", "schema_path", "provider",
    ),
    "agent_invoke_local_complete": ("prompt_name", "output_path"),
    "agent_invoke_local_failed": (
        "prompt_name", "output_path", "exit_code", "error",
    ),
    "agent_token_usage": (
        "prompt_name", "input_tokens", "cached_input_tokens", "output_tokens",
    ),
    "agent_invoke_api": (
        "prompt_name", "prompt_preview", "output_path", "provider",
    ),
    "agent_invoke_api_complete": ("prompt_name", "output_path"),
    "format_result": (
        "source_path", "input_rows", "output_rows", "keyword_replacements",
        "columns_appended", "ids_assigned", "ids_preserved",
    ),
}
_DEFAULT_EVENT_KEYS: tuple[str, ...] = ("status", "error")


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


def _get_event_keys(event: str) -> tuple[str, ...]:
    """Return allowed extra keys for the given event. Unknown events use default set."""
    return _EVENT_KEYS.get(event, _DEFAULT_EVENT_KEYS)


def _add_event_specific_keys(payload: dict[str, Any], record: logging.LogRecord) -> None:
    """Add only event-allowed keys from record to payload. Prevents key leakage."""
    event = getattr(record, "event", "log")
    for key in _get_event_keys(event):
        val = getattr(record, key, None)
        if val is not None:
            payload[key] = str(val) if isinstance(val, Path) else val


class _JsonLinesFormatter(logging.Formatter):
    """Format each log entry as JSON with timestamp, level, event, and event keys only.

    Meta/context (command, run_id, etc.) is written once in the file header.
    """
    def format(self, record: logging.LogRecord) -> str:
        """Return format."""
        dt = datetime.fromtimestamp(record.created, tz=timezone.utc).astimezone()
        payload: dict[str, Any] = {
            "timestamp": format_timestamp_local_minutes(dt),
            "level": record.levelname,
            "event": getattr(record, "event", "log"),
        }
        _add_event_specific_keys(payload, record)
        return json.dumps(payload, separators=(",", ":"), sort_keys=False)


class _StructuredTextFormatter(logging.Formatter):
    """Format each log entry with timestamp, level, event, and event keys only.

    Meta/context (command, run_id, etc.) is written once in the file header.
    """
    def format(self, record: logging.LogRecord) -> str:
        """Return format."""
        dt = datetime.fromtimestamp(record.created, tz=timezone.utc).astimezone()
        parts = [
            f"timestamp={format_timestamp_local_minutes(dt)}",
            f"level={record.levelname}",
            f"event={getattr(record, 'event', 'log')}",
        ]
        event = getattr(record, "event", "log")
        for key in _get_event_keys(event):
            val = getattr(record, key, None)
            if val is not None:
                parts.append(f"{key}={val}")
        return " ".join(parts)


def _resolve_log_dir(project_root: Path, config: dict[str, Any]) -> Path:
    """Resolve log dir."""
    logging_section = config.get("logging")
    if isinstance(logging_section, dict):
        log_dir = logging_section.get("log_dir")
        if isinstance(log_dir, str) and log_dir.strip():
            candidate = Path(log_dir)
            return candidate.resolve() if candidate.is_absolute() else (project_root / candidate).resolve()

    from core.pika_config import get_pika_config

    log_dir_rel = get_pika_config().get("default_outputs", {}).get("log_dir", "out/logs")
    return (project_root / log_dir_rel).resolve()


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


def _build_meta_header(ctx: RuntimeContext) -> dict[str, Any]:
    """Build meta/context dict for log file header."""
    return {
        "command": ctx.command,
        "run_id": ctx.run_id,
        "config_path": ctx.config_path,
        "dry_run": ctx.dry_run,
        "command_only_validation": ctx.command_only_validation,
    }


class _RunLogFileHandler(logging.FileHandler):
    """File handler that writes meta header on first emit, then slim event entries."""

    def __init__(
        self,
        filename: str | Path,
        *,
        ctx: RuntimeContext,
        json_mode: bool,
        mode: str = "x",
        write_header: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(filename, mode=mode, encoding="utf-8", **kwargs)
        self._ctx = ctx
        self._json_mode = json_mode
        self._header_written = not write_header

    def emit(self, record: logging.LogRecord) -> None:
        """Write header on first emit, then format and write record."""
        if not self._header_written:
            self._write_header()
            self._header_written = True
        super().emit(record)

    def _write_header(self) -> None:
        """Write meta/context as first line of log file."""
        meta = _build_meta_header(self._ctx)
        header = {"$meta": meta}
        line = json.dumps(header, separators=(",", ":"), sort_keys=False) + "\n"
        try:
            self.stream.write(line)
            self.stream.flush()
        except OSError:
            pass  # Cannot log to same file; header write failure is fatal for this run


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
    resume_existing_log = bool(
        ctx.resume_run_id and ctx.resume_run_id == ctx.run_id and log_file.exists()
    )
    file_mode = "a" if resume_existing_log else "x"
    write_header = not (resume_existing_log and log_file.stat().st_size > 0)
    level = _resolve_log_level(config, verbose=ctx.verbose)
    json_mode = _resolve_json_mode(config)

    run_logger = logging.getLogger(RUN_LOGGER_NAME)
    run_logger.setLevel(level)
    run_logger.propagate = False

    for handler in list(run_logger.handlers):
        run_logger.removeHandler(handler)
        handler.close()

    try:
        file_handler = _RunLogFileHandler(
            log_file,
            ctx=ctx,
            json_mode=json_mode,
            mode=file_mode,
            write_header=write_header,
        )
    except OSError as exc:
        raise RuntimeError(f"Failed to create log file '{log_file}': {exc}") from exc

    file_handler.setLevel(level)
    file_handler.setFormatter(_JsonLinesFormatter() if json_mode else _StructuredTextFormatter())
    file_handler.addFilter(_RunContextFilter(ctx=ctx))
    run_logger.addHandler(file_handler)

    return log_file
