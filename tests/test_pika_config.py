"""Tests for core.pika_config."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.pika_config import get_pika_config, load_pika_config, reset_pika_config_cache


class PikaConfigTests(unittest.TestCase):
    """Tests for PIKA config loader."""

    def tearDown(self) -> None:
        """Reset cache between tests."""
        reset_pika_config_cache()

    def test_load_returns_dict(self) -> None:
        """load_pika_config returns a dict."""
        cfg = load_pika_config()
        self.assertIsInstance(cfg, dict)

    def test_has_paths_section(self) -> None:
        """Config has paths section with expected keys."""
        cfg = get_pika_config()
        paths = cfg.get("paths", {})
        self.assertIn("config_schema", paths)
        self.assertIn("prompts_file", paths)
        self.assertIn("csv_contracts", paths)

    def test_has_api_section(self) -> None:
        """Config has api section with url and model."""
        cfg = get_pika_config()
        api = cfg.get("api", {})
        self.assertIn("url", api)
        self.assertIn("model", api)
        self.assertIn("map", api)
        self.assertIn("default", api)

    def test_has_local_section(self) -> None:
        """Config has local section."""
        cfg = get_pika_config()
        local = cfg.get("local", {})
        self.assertIn("heartbeat_interval_sec", local)
        self.assertIn("exec_timeout_sec", local)

    def test_has_default_outputs(self) -> None:
        """Config has default_outputs for workspace fallbacks."""
        cfg = get_pika_config()
        outputs = cfg.get("default_outputs", {})
        self.assertIn("log_dir", outputs)
        self.assertIn("state_dir", outputs)
        self.assertIn("sads_id_mapping", outputs)
        self.assertIn("id_registry", outputs)

    def test_config_is_cached(self) -> None:
        """Same instance returned on repeated calls."""
        a = get_pika_config()
        b = get_pika_config()
        self.assertIs(a, b)

    def test_reset_clears_cache(self) -> None:
        """reset_pika_config_cache clears cache."""
        a = get_pika_config()
        reset_pika_config_cache()
        b = get_pika_config()
        self.assertIsNot(a, b)

    def test_load_raises_when_config_file_missing(self) -> None:
        """Missing config/pika.yaml is a hard requirement."""
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_path = Path(tmpdir) / "pika.yaml"
            with patch("core.pika_config._PIKA_CONFIG_PATH", missing_path):
                reset_pika_config_cache()
                with self.assertRaises(FileNotFoundError):
                    load_pika_config()

    def test_load_raises_when_required_fields_are_missing(self) -> None:
        """Required fields in pika.yaml must be present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            incomplete_path = Path(tmpdir) / "pika.yaml"
            incomplete_path.write_text("api: {}\n", encoding="utf-8")
            with patch("core.pika_config._PIKA_CONFIG_PATH", incomplete_path):
                reset_pika_config_cache()
                with self.assertRaises(ValueError):
                    load_pika_config()


if __name__ == "__main__":
    unittest.main()
