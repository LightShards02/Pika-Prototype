"""Tests for core.pika_config."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.pika_config import (
    _validate_required_config,
    get_pika_config,
    load_pika_config,
    reset_pika_config_cache,
)


class PikaConfigTests(unittest.TestCase):
    """Tests for PIKA config loader."""

    def tearDown(self) -> None:
        """Reset cache between tests."""
        reset_pika_config_cache()

    def test_load_returns_dict(self) -> None:
        """load_pika_config returns a dict."""
        cfg = load_pika_config()
        self.assertIsInstance(cfg, dict)

    def test_has_version(self) -> None:
        """Config has version field."""
        cfg = get_pika_config()
        self.assertIn("version", cfg)
        self.assertIsInstance(cfg["version"], str)
        self.assertTrue(cfg["version"].strip())

    def test_has_paths_section(self) -> None:
        """Config has paths section with expected keys."""
        cfg = get_pika_config()
        paths = cfg.get("paths", {})
        self.assertIn("config_schema", paths)
        self.assertIn("prompts_file", paths)
        self.assertIn("csv_contracts", paths)

    def test_has_local_section(self) -> None:
        """Config has local section."""
        cfg = get_pika_config()
        local = cfg.get("local", {})
        self.assertIn("heartbeat_interval_sec", local)
        self.assertIn("exec_timeout_sec", local)
        self.assertIn("model", local)
        default_model = local["model"]["default"]
        self.assertIn("name", default_model)
        self.assertTrue(str(default_model["name"]).strip())

    def test_local_command_optional_in_validation(self) -> None:
        """local.command may be omitted; PIKA config validation still passes."""
        cfg = copy.deepcopy(get_pika_config())
        local = cfg.get("local")
        self.assertIsInstance(local, dict)
        local.pop("command", None)
        _validate_required_config(cfg)

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


class LocalModelProfileValidationTests(unittest.TestCase):
    """Tests for local model profile validation, including base_url."""

    def tearDown(self) -> None:
        """Reset cache between tests."""
        reset_pika_config_cache()

    def test_base_url_accepted_when_valid(self) -> None:
        """base_url is accepted when it's a valid URL string."""
        from core.pika_config import _validate_local_model_profile

        missing: list[str] = []
        profile = {
            "name": "gpt-4o",
            "base_url": "https://api.example.com/v1",
        }
        _validate_local_model_profile(profile, "local.model.default", missing, require_name=True)
        self.assertEqual(missing, [])

    def test_base_url_optional(self) -> None:
        """base_url is optional and can be omitted."""
        from core.pika_config import _validate_local_model_profile

        missing: list[str] = []
        profile = {
            "name": "gpt-4o",
        }
        _validate_local_model_profile(profile, "local.model.default", missing, require_name=True)
        self.assertEqual(missing, [])

    def test_base_url_can_be_null(self) -> None:
        """base_url can be explicitly set to null."""
        from core.pika_config import _validate_local_model_profile

        missing: list[str] = []
        profile = {
            "name": "gpt-4o",
            "base_url": None,
        }
        _validate_local_model_profile(profile, "local.model.default", missing, require_name=True)
        self.assertEqual(missing, [])

    def test_base_url_rejected_when_empty_string(self) -> None:
        """base_url is rejected when it's an empty string."""
        from core.pika_config import _validate_local_model_profile

        missing: list[str] = []
        profile = {
            "name": "gpt-4o",
            "base_url": "",
        }
        _validate_local_model_profile(profile, "local.model.default", missing, require_name=True)
        self.assertIn("local.model.default.base_url", missing)


if __name__ == "__main__":
    unittest.main()
