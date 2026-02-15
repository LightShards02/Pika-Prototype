from __future__ import annotations

import unittest

from core.command_router import RuntimeContext, dispatch


class CommandRouterTests(unittest.TestCase):
    """Test cases for command router."""
    def _make_ctx(self, command: str) -> RuntimeContext:
        """Create ctx."""
        return RuntimeContext(
            command=command,
            dry_run=True,
            verbose=False,
            command_only_validation=False,
            run_id="run-123",
            project_root="/tmp/project",
            config_path="/tmp/project/config.yaml",
        )

    def test_dispatch_load_returns_initialized(self) -> None:
        """Test that dispatch load returns initialized."""
        result = dispatch("load", {}, self._make_ctx("load"))
        self.assertEqual(
            result,
            {
                "command": "load",
                "status": "initialized",
                "dry_run": True,
                "run_id": "run-123",
            },
        )

    def test_dispatch_unknown_raises_value_error(self) -> None:
        """Test that dispatch unknown raises value error."""
        with self.assertRaises(ValueError) as ctx:
            dispatch("unknown", {}, self._make_ctx("unknown"))
        self.assertEqual(str(ctx.exception), "Unknown command: unknown")


if __name__ == "__main__":
    unittest.main()
