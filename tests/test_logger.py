from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path

from core.command_router import RuntimeContext
from core.logger import RUN_LOGGER_NAME, init_run_logger


class RunLoggerTests(unittest.TestCase):
    """Test cases for run logger."""
    def tearDown(self) -> None:
        """Return tear down."""
        logger = logging.getLogger(RUN_LOGGER_NAME)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    def _make_ctx(self, *, root: Path, run_id: str = "run123") -> RuntimeContext:
        """Create ctx."""
        return RuntimeContext(
            command="load",
            dry_run=True,
            verbose=False,
            command_only_validation=False,
            run_id=run_id,
            project_root=str(root),
            config_path=str(root / "config" / "config.example.yaml"),
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

        self.assertEqual(created_path, configured_log_dir / "load_run123.log")
        self.assertTrue(created_path.exists())

        records = [
            json.loads(line)
            for line in created_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(records[0]["event"], "command_start")
        self.assertEqual(records[0]["command"], "load")
        self.assertEqual(records[0]["run_id"], "run123")
        self.assertEqual(records[0]["dry_run"], True)
        self.assertEqual(records[0]["command_only_validation"], False)

    def test_init_run_logger_raises_clear_error_for_invalid_log_dir(self) -> None:
        """Test that init run logger raises clear error for invalid log dir."""
        root = Path(tempfile.mkdtemp(prefix="run-logger-fail-"))
        bad_path = root / "bad-target"
        bad_path.write_text("not a directory\n", encoding="utf-8")
        ctx = self._make_ctx(root=root, run_id="run456")
        config = {"logging": {"log_dir": str(bad_path / "nested")}}

        with self.assertRaises(RuntimeError) as raised:
            init_run_logger(project_root=root, config=config, ctx=ctx)

        self.assertIn("Failed to create log directory", str(raised.exception))

    def test_init_run_logger_uses_verbose_level_when_verbose_flag_true(self) -> None:
        """Test that init run logger uses verbose level when verbose flag true."""
        root = Path(tempfile.mkdtemp(prefix="run-logger-verbose-"))
        ctx = RuntimeContext(
            command="load",
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

        log_file = root / "logs" / "load_run789.log"
        self.assertTrue(log_file.exists())
        first_entry = json.loads(log_file.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(first_entry["level"], "DEBUG")


if __name__ == "__main__":
    unittest.main()
