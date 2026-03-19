from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path

from core.context import RuntimeContext
from core.logger import (
    RUN_LOGGER_NAME,
    _get_event_keys,
    init_run_logger,
)


class EventKeysTests(unittest.TestCase):
    """Test event-specific key mapping prevents key leakage."""

    def test_format_result_has_format_keys_only(self) -> None:
        """format_result event allows only format-specific keys."""
        keys = _get_event_keys("format_result")
        self.assertIn("source_path", keys)
        self.assertIn("input_rows", keys)
        self.assertNotIn("prompt_name", keys)
        self.assertNotIn("schema_path", keys)

    def test_agent_events_have_agent_keys_only(self) -> None:
        """agent_invoke_local allows only agent keys, not format keys."""
        keys = _get_event_keys("agent_invoke_local")
        self.assertIn("prompt_name", keys)
        self.assertIn("output_path", keys)
        self.assertNotIn("source_path", keys)
        self.assertNotIn("ids_assigned", keys)

    def test_unknown_event_uses_default_keys(self) -> None:
        """Unknown event falls back to status and error only."""
        keys = _get_event_keys("custom_event_xyz")
        self.assertEqual(keys, ("status", "error"))


class RunLoggerTests(unittest.TestCase):
    """Test cases for run logger."""
    def tearDown(self) -> None:
        """Return tear down."""
        logger = logging.getLogger(RUN_LOGGER_NAME)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    def _make_ctx(
        self,
        *,
        root: Path,
        run_id: str = "run123",
        resume_run_id: str | None = None,
    ) -> RuntimeContext:
        """Create ctx."""
        return RuntimeContext(
            command="format",
            dry_run=True,
            verbose=False,
            command_only_validation=False,
            run_id=run_id,
            project_root=str(root),
            config_path=str(root / "config" / "config.example.yaml"),
            resume_run_id=resume_run_id,
        )

    def test_init_run_logger_uses_logging_log_dir(self) -> None:
        """Test that init run logger uses logging log dir."""
        root = Path(tempfile.mkdtemp(prefix="run-logger-"))
        configured_log_dir = root / "custom-logs"
        ctx = self._make_ctx(root=root)
        config = {"logging": {"log_dir": str(configured_log_dir)}}

        created_path = init_run_logger(project_root=root, config=config, ctx=ctx)
        logger = logging.getLogger(RUN_LOGGER_NAME)
        logger.info("command_start", extra={"event": "command_start"})

        self.assertEqual(created_path, configured_log_dir / "format_run123.log")
        self.assertTrue(created_path.exists())

        lines = [l for l in created_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        meta = json.loads(lines[0])
        self.assertIn("$meta", meta)
        self.assertEqual(meta["$meta"]["command"], "format")
        self.assertEqual(meta["$meta"]["run_id"], "run123")
        self.assertEqual(meta["$meta"]["dry_run"], True)
        self.assertEqual(meta["$meta"]["command_only_validation"], False)

        event_entry = json.loads(lines[1])
        self.assertEqual(event_entry["event"], "command_start")
        self.assertEqual(event_entry["level"], "INFO")
        self.assertNotIn("command", event_entry)
        self.assertNotIn("run_id", event_entry)

    def test_init_run_logger_raises_clear_error_for_invalid_log_dir(self) -> None:
        """Test that init run logger raises clear error for invalid log dir."""
        root = Path(tempfile.mkdtemp(prefix="run-logger-fail-"))
        bad_path = root / "bad-target"
        bad_path.write_text("not a directory\n", encoding="utf-8")
        ctx = self._make_ctx(root=root, run_id="run456")
        config = {"logging": {"log_dir": str(bad_path / "nested")}}

        with self.assertRaises(RuntimeError) as exc_ctx:
            init_run_logger(project_root=root, config=config, ctx=ctx)
        self.assertIn("Failed to create log directory", str(exc_ctx.exception))

    def test_init_run_logger_uses_verbose_level_when_verbose_flag_true(self) -> None:
        """Test that init run logger uses verbose level when verbose flag true."""
        root = Path(tempfile.mkdtemp(prefix="run-logger-verbose-"))
        ctx = RuntimeContext(
            command="format",
            dry_run=True,
            verbose=True,
            command_only_validation=False,
            run_id="run789",
            project_root=str(root),
            config_path=str(root / "config" / "config.example.yaml"),
        )
        config = {
            "logging": {
                "level": "ERROR",
                "verbose_level": "DEBUG",
                "log_dir": str(root / "logs"),
            }
        }

        _ = init_run_logger(project_root=root, config=config, ctx=ctx)
        logger = logging.getLogger(RUN_LOGGER_NAME)
        logger.debug("command_start", extra={"event": "command_start"})

        log_file = root / "logs" / "format_run789.log"
        self.assertTrue(log_file.exists())
        lines = [l for l in log_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertGreaterEqual(len(lines), 2)
        first_event = json.loads(lines[1])  # Line 0 is $meta header
        self.assertEqual(first_event["level"], "DEBUG")

    def test_init_run_logger_appends_existing_log_on_resume(self) -> None:
        """Resume path appends to an existing run log instead of failing."""
        root = Path(tempfile.mkdtemp(prefix="run-logger-resume-"))
        logs_dir = root / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        existing = logs_dir / "format_run123.log"
        existing.write_text(
            (
                '{"$meta":{"command":"format","run_id":"run123"}}\n'
                '{"timestamp":"2026-03-05T23:00:00 UTC-8","level":"INFO","event":"command_start"}\n'
            ),
            encoding="utf-8",
        )

        ctx = self._make_ctx(root=root, run_id="run123", resume_run_id="run123")
        config = {"logging": {"log_dir": str(logs_dir)}}

        created_path = init_run_logger(project_root=root, config=config, ctx=ctx)
        logger = logging.getLogger(RUN_LOGGER_NAME)
        logger.info("command_end", extra={"event": "command_end", "status": "completed"})

        self.assertEqual(created_path, existing)
        lines = [l for l in existing.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertGreaterEqual(len(lines), 3)
        self.assertEqual(sum(1 for l in lines if l.startswith('{"$meta":')), 1)
        last = json.loads(lines[-1])
        self.assertEqual(last.get("event"), "command_end")
        self.assertEqual(last.get("status"), "completed")

    def test_init_run_logger_non_resume_existing_file_still_fails(self) -> None:
        """Non-resume path still uses exclusive create for collision safety."""
        root = Path(tempfile.mkdtemp(prefix="run-logger-collision-"))
        logs_dir = root / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        existing = logs_dir / "format_run123.log"
        existing.write_text("existing\n", encoding="utf-8")

        ctx = self._make_ctx(root=root, run_id="run123")
        config = {"logging": {"log_dir": str(logs_dir)}}

        with self.assertRaises(RuntimeError) as exc_ctx:
            init_run_logger(project_root=root, config=config, ctx=ctx)
        self.assertIn("Failed to create log file", str(exc_ctx.exception))


if __name__ == "__main__":
    unittest.main()
