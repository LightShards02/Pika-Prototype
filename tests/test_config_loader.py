from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from core.config_loader import load_and_validate_config
from core.errors import ConfigSchemaValidationError


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "config" / "config.schema.json"
EXAMPLE_CONFIG_PATH = REPO_ROOT / "config" / "config.example.yaml"


class ConfigLoaderImplementPolicyTests(unittest.TestCase):
    """Validation tests for implement disallowed role->kind link policy."""

    def _write_temp_config(self, content: str) -> Path:
        """Write config content to temp file and return path."""
        temp_dir = Path(tempfile.mkdtemp(prefix="config-loader-policy-"))
        config_path = temp_dir / "config.yaml"
        config_path.write_text(content, encoding="utf-8")
        return config_path

    def test_valid_disallowed_policy_passes_schema_validation(self) -> None:
        """Valid role/kind policy should pass schema validation."""
        config = yaml.safe_load(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"))
        config["commands"]["implement"]["disallowed_link_kinds_by_required_role"] = {
            "frontend": ["external_api", "file_format"],
            "domain": ["external_api"],
        }
        path = self._write_temp_config(yaml.safe_dump(config, sort_keys=False))
        loaded = load_and_validate_config(path, SCHEMA_PATH)
        self.assertIn("disallowed_link_kinds_by_required_role", loaded["commands"]["implement"])

    def test_unknown_role_fails_schema_validation(self) -> None:
        """Unknown role key should fail schema validation."""
        config = yaml.safe_load(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"))
        config["commands"]["implement"]["disallowed_link_kinds_by_required_role"] = {
            "frontendx": ["external_api"],
        }
        path = self._write_temp_config(yaml.safe_dump(config, sort_keys=False))
        with self.assertRaises(ConfigSchemaValidationError):
            load_and_validate_config(path, SCHEMA_PATH)

    def test_unknown_kind_fails_schema_validation(self) -> None:
        """Unknown contract kind should fail schema validation."""
        config = yaml.safe_load(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"))
        config["commands"]["implement"]["disallowed_link_kinds_by_required_role"] = {
            "frontend": ["not_a_kind"],
        }
        path = self._write_temp_config(yaml.safe_dump(config, sort_keys=False))
        with self.assertRaises(ConfigSchemaValidationError):
            load_and_validate_config(path, SCHEMA_PATH)


if __name__ == "__main__":
    unittest.main()
