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
NUTRITION_CONFIG_PATH = REPO_ROOT.parent / "dataset" / "nutrition" / "config.yaml"


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

    def test_nutrition_workspace_config_passes_schema_validation(self) -> None:
        """Dataset nutrition config should remain schema-valid for implement debug workflows."""
        loaded = load_and_validate_config(NUTRITION_CONFIG_PATH, SCHEMA_PATH)
        self.assertIn("commands", loaded)

    def test_local_agent_profile_override_passes_schema_validation(self) -> None:
        """Nested agent.{agent_name} local-model overrides should validate."""
        config = yaml.safe_load(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"))
        config["agent"]["default"] = {
            "name": "gpt-5.3-codex",
            "reasoning_effort": "medium",
        }
        config["agent"]["implement_from_specs"] = {
            "name": "gpt-5.3-codex-spark",
            "temperature": 0.4,
            "top_p": 0.9,
            "web_search": False,
        }
        path = self._write_temp_config(yaml.safe_dump(config, sort_keys=False))
        loaded = load_and_validate_config(path, SCHEMA_PATH)
        self.assertEqual(loaded["agent"]["implement_from_specs"]["name"], "gpt-5.3-codex-spark")

    def test_local_agent_profile_null_reasoning_effort_passes_schema_validation(self) -> None:
        """reasoning_effort: null is valid for Loca sampling (temperature/top_p)."""
        config = yaml.safe_load(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"))
        config["agent"]["spec_editor"] = {
            "reasoning_effort": None,
            "temperature": 0.5,
            "top_p": 0.5,
        }
        path = self._write_temp_config(yaml.safe_dump(config, sort_keys=False))
        loaded = load_and_validate_config(path, SCHEMA_PATH)
        self.assertIsNone(loaded["agent"]["spec_editor"]["reasoning_effort"])

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

    def test_step_scoped_field_match_score_threshold_accepts_normalized_number(self) -> None:
        """Step-scoped contract threshold in [0,1] should pass schema validation."""
        config = yaml.safe_load(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"))
        config["commands"]["implement"]["contract_field_consistency_validation"] = {
            "enabled": True,
            "field_match_score_threshold": 0.72,
        }
        path = self._write_temp_config(yaml.safe_dump(config, sort_keys=False))
        loaded = load_and_validate_config(path, SCHEMA_PATH)
        self.assertEqual(
            loaded["commands"]["implement"]["contract_field_consistency_validation"][
                "field_match_score_threshold"
            ],
            0.72,
        )

    def test_step_toggle_rejects_non_boolean_enabled(self) -> None:
        """Step toggle enabled must be boolean."""
        config = yaml.safe_load(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"))
        config["commands"]["implement"]["patch_apply_gate"] = {"enabled": "yes"}
        path = self._write_temp_config(yaml.safe_dump(config, sort_keys=False))
        with self.assertRaises(ConfigSchemaValidationError):
            load_and_validate_config(path, SCHEMA_PATH)



if __name__ == "__main__":
    unittest.main()
