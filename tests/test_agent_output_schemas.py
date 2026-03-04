"""Compatibility checks for agent output schemas used by prompts."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "schemas" / "agent_outputs"
PROMPT_FILE = REPO_ROOT / "prompts" / "PROMPT.yaml"


class AgentOutputSchemaCompatibilityTests(unittest.TestCase):
    """Ensure output schemas remain compatible with Codex structured outputs."""

    def test_all_agent_output_schemas_have_object_root_type(self) -> None:
        """Every schema under schemas/agent_outputs must be a root object schema."""
        self.assertTrue(SCHEMA_DIR.exists(), f"Missing schema directory: {SCHEMA_DIR}")
        schema_files = sorted(SCHEMA_DIR.glob("*.json"))
        self.assertTrue(schema_files, f"No schema files found in {SCHEMA_DIR}")

        for schema_path in schema_files:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            self.assertEqual(
                schema.get("type"),
                "object",
                f"{schema_path.as_posix()} must declare top-level type=object",
            )

    def test_prompt_referenced_schemas_have_object_root_type(self) -> None:
        """Every output_schema_file referenced by prompts must be a root object schema."""
        prompt_doc = yaml.safe_load(PROMPT_FILE.read_text(encoding="utf-8"))
        prompts = prompt_doc.get("prompts", {}) if isinstance(prompt_doc, dict) else {}
        self.assertTrue(prompts, "No prompts found in prompts/PROMPT.yaml")

        for prompt_name, prompt_def in prompts.items():
            self.assertIsInstance(prompt_def, dict, f"Prompt {prompt_name} must be an object")
            schema_rel = prompt_def.get("output_schema_file")
            self.assertIsInstance(
                schema_rel,
                str,
                f"Prompt {prompt_name} must define output_schema_file as string",
            )
            schema_path = (REPO_ROOT / schema_rel).resolve()
            self.assertTrue(
                schema_path.exists(),
                f"Prompt {prompt_name} references missing schema: {schema_path}",
            )
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            self.assertEqual(
                schema.get("type"),
                "object",
                f"Prompt {prompt_name} schema {schema_path.as_posix()} must declare top-level type=object",
            )


if __name__ == "__main__":
    unittest.main()
