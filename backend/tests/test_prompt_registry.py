from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.errors import PromptNotFoundError, PromptParseError, PromptValidationError
from core.prompt_registry import PromptRegistry


class PromptRegistryTests(unittest.TestCase):
    """Test cases for prompt registry."""
    def _make_root(self) -> Path:
        """Create root."""
        root = Path(tempfile.mkdtemp(prefix="prompt-registry-test-"))
        (root / "config").mkdir(parents=True, exist_ok=True)
        (root / "prompts").mkdir(parents=True, exist_ok=True)
        (root / "schemas" / "agent_outputs").mkdir(parents=True, exist_ok=True)
        return root

    def _write_schema(self, root: Path, name: str = "test.schema.json") -> Path:
        """Write schema."""
        schema_path = root / "schemas" / "agent_outputs" / name
        schema_path.write_text("{}\n", encoding="utf-8")
        return schema_path

    def test_from_config_loads_prompt_and_lookups(self) -> None:
        """Test that from config loads prompt and lookups."""
        root = self._make_root()
        schema_path = self._write_schema(root)
        prompt_file = root / "prompts" / "PROMPT.yaml"
        prompt_file.write_text(
            f"""
prompts:
  map_spec_to_code:
    version: "1.0"
    system: "system text"
    user: "user text"
    output_schema_file: {schema_path.as_posix()}
    template_variables:
      - name: project_context
        required: true
        description: context
""".strip()
            + "\n",
            encoding="utf-8",
        )

        config = {"prompts": {"prompt_file": str(prompt_file)}}
        registry = PromptRegistry.from_config(config)

        self.assertEqual(registry.list_prompts(), ["map_spec_to_code"])
        spec = registry.get("map_spec_to_code")
        self.assertEqual(spec.name, "map_spec_to_code")
        self.assertEqual(spec.version, "1.0")
        self.assertEqual(spec.system_prompt, "system text")
        self.assertEqual(spec.user_prompt, "user text")
        self.assertEqual(
            spec.output_schema_file, schema_path.as_posix()
        )
        self.assertEqual(
            spec.template_variables,
            {"project_context": {"required": True, "description": "context"}},
        )
        self.assertEqual(
            registry.get_template_variables("map_spec_to_code"),
            {"project_context": {"required": True, "description": "context"}},
        )
        self.assertEqual(
            registry.get_schema_path("map_spec_to_code"),
            schema_path.resolve(),
        )

    def test_legacy_prompt_shape_is_normalized(self) -> None:
        """Test that legacy prompt shape is normalized."""
        root = self._make_root()
        schema_path = self._write_schema(root)
        prompt_file = root / "prompts" / "PROMPT.yaml"
        prompt_file.write_text(
            f"""
version: 1
prompts:
  map_issues_to_specs:
    system: "sys block"
    user: "user block"
    output_schema_file: {schema_path.as_posix()}
""".strip()
            + "\n",
            encoding="utf-8",
        )

        registry = PromptRegistry(prompt_file=prompt_file)
        spec = registry.get("map_issues_to_specs")

        self.assertEqual(spec.version, "1")
        self.assertEqual(spec.system_prompt, "sys block")
        self.assertEqual(spec.user_prompt, "user block")

    def test_missing_required_field_raises_validation_error(self) -> None:
        """Test that missing required field raises validation error."""
        root = self._make_root()
        schema_path = self._write_schema(root)
        prompt_file = root / "prompts" / "PROMPT.yaml"
        prompt_file.write_text(
            f"""
prompts:
  implement_from_specs:
    version: "1"
    user: "user text"
    output_schema_file: {schema_path.as_posix()}
""".strip()
            + "\n",
            encoding="utf-8",
        )

        with self.assertRaises(PromptValidationError) as ctx:
            PromptRegistry(prompt_file=prompt_file)

        self.assertIn("implement_from_specs", str(ctx.exception))
        self.assertIn("system", str(ctx.exception))

    def test_missing_schema_file_raises_validation_error(self) -> None:
        """Test that missing schema file raises validation error."""
        root = self._make_root()
        prompt_file = root / "prompts" / "PROMPT.yaml"
        missing_schema = root / "schemas" / "agent_outputs" / "missing.schema.json"
        prompt_file.write_text(
            f"""
prompts:
  resolve_issues_with_diffs:
    version: "2"
    system: "plan changes"
    user: "apply changes"
    output_schema_file: {missing_schema.as_posix()}
""".strip()
            + "\n",
            encoding="utf-8",
        )

        with self.assertRaises(PromptValidationError) as ctx:
            PromptRegistry(prompt_file=prompt_file)

        self.assertIn("resolve_issues_with_diffs", str(ctx.exception))
        self.assertIn("output_schema_file", str(ctx.exception))

    def test_invalid_yaml_raises_parse_error(self) -> None:
        """Test that invalid yaml raises parse error."""
        root = self._make_root()
        prompt_file = root / "prompts" / "PROMPT.yaml"
        prompt_file.write_text("prompts: [invalid\n", encoding="utf-8")

        with self.assertRaises(PromptParseError):
            PromptRegistry(prompt_file=prompt_file)

    def test_get_unknown_prompt_raises_not_found(self) -> None:
        """Test that get unknown prompt raises not found."""
        root = self._make_root()
        schema_path = self._write_schema(root)
        prompt_file = root / "prompts" / "PROMPT.yaml"
        prompt_file.write_text(
            f"""
prompts:
  index_spec_to_code:
    version: "1"
    system: "json"
    user: "json"
    output_schema_file: {schema_path.as_posix()}
""".strip()
            + "\n",
            encoding="utf-8",
        )

        registry = PromptRegistry(prompt_file=prompt_file)
        with self.assertRaises(PromptNotFoundError):
            registry.get("does_not_exist")


if __name__ == "__main__":
    unittest.main()
