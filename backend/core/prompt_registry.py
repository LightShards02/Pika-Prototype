from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from core.errors import (
    PromptFileNotFoundError,
    PromptNotFoundError,
    PromptParseError,
    PromptValidationError,
)
from core.pika_paths import resolve_path_from_pika_root, resolve_prompts_path


@dataclass(frozen=True)
class PromptSpec:
    """Normalized prompt definition used by runtime callers."""

    name: str
    version: str
    system_prompt: str
    user_prompt: str
    output_schema_file: str
    template_variables: dict[str, dict[str, Any]]


class PromptRegistry:
    """Loads and validates prompt specs from the central PROMPT file.

    Prompt file and schema paths are resolved from PIKA root only.
    Only template variables vary per project; the prompt template is project-independent.
    """

    def __init__(self, prompt_file: str | Path) -> None:
        """Initialize prompt registry. prompt_file is resolved from PIKA root."""
        self._prompt_file = resolve_prompts_path(str(prompt_file))
        self._specs: dict[str, PromptSpec] = {}
        self._schema_paths: dict[str, Path] = {}
        self._load()

    @classmethod
    def from_config(cls, config: dict) -> "PromptRegistry":
        """Return from config. prompts.prompt_file is resolved from PIKA root."""
        prompts_section = config.get("prompts")
        if not isinstance(prompts_section, dict):
            raise PromptValidationError(
                "Config field prompts must be an object with prompts.prompt_file."
            )

        prompt_file = prompts_section.get("prompt_file")
        if not isinstance(prompt_file, str) or not prompt_file.strip():
            raise PromptValidationError(
                "Config field prompts.prompt_file must be a non-empty string."
            )

        return cls(prompt_file=prompt_file)

    def list_prompts(self) -> list[str]:
        """List prompts."""
        return sorted(self._specs)

    def get(self, name: str) -> PromptSpec:
        """Return get."""
        spec = self._specs.get(name)
        if spec is None:
            raise PromptNotFoundError(f"Prompt not found: {name}")
        return spec

    def get_version(self, name: str) -> str:
        """Get version."""
        return self.get(name).version

    def get_system_prompt(self, name: str) -> str:
        """Get system prompt."""
        return self.get(name).system_prompt

    def get_user_prompt(self, name: str) -> str:
        """Get user prompt."""
        return self.get(name).user_prompt

    def get_template_variables(self, name: str) -> dict[str, dict[str, Any]]:
        """Get template variables."""
        return dict(self.get(name).template_variables)

    def get_schema_path(self, name: str) -> Path:
        """Get schema path."""
        spec = self.get(name)
        return self._schema_paths[spec.name]

    def _load(self) -> None:
        """Return load."""
        if not self._prompt_file.exists() or not self._prompt_file.is_file():
            raise PromptFileNotFoundError(
                f"Prompt file not found: {self._prompt_file}"
            )

        try:
            loaded = yaml.safe_load(self._prompt_file.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise PromptParseError(
                f"Invalid YAML in prompt file {self._prompt_file}: {exc}"
            ) from exc
        except OSError as exc:
            raise PromptParseError(
                f"Unable to read prompt file {self._prompt_file}: {exc}"
            ) from exc

        if loaded is None:
            raise PromptValidationError(f"Prompt file is empty: {self._prompt_file}")
        if not isinstance(loaded, dict):
            raise PromptValidationError(
                f"Prompt file root must be an object: {self._prompt_file}"
            )

        prompt_nodes = loaded.get("prompts", loaded)
        if not isinstance(prompt_nodes, dict):
            raise PromptValidationError(
                f"Prompt collection must be an object in file: {self._prompt_file}"
            )

        top_level_version = loaded.get("version")

        specs: dict[str, PromptSpec] = {}
        schema_paths: dict[str, Path] = {}

        for prompt_name, prompt_node in prompt_nodes.items():
            if not isinstance(prompt_name, str) or not prompt_name.strip():
                raise PromptValidationError(
                    "Prompt name must be a non-empty string in prompt file "
                    f"{self._prompt_file}."
                )

            if not isinstance(prompt_node, dict):
                raise PromptValidationError(
                    f"Prompt '{prompt_name}' must be an object in {self._prompt_file}."
                )

            version = self._read_version(prompt_name, prompt_node, top_level_version)
            system_prompt = self._read_required_string(
                prompt_name, prompt_node, "system"
            )
            user_prompt = self._read_required_string(prompt_name, prompt_node, "user")
            output_schema_file = self._read_required_string(
                prompt_name, prompt_node, "output_schema_file"
            )
            template_variables = self._read_template_variables(
                prompt_name, prompt_node
            )

            schema_path = self._resolve_schema_path(output_schema_file)
            if not schema_path.exists() or not schema_path.is_file():
                raise PromptValidationError(
                    f"Prompt '{prompt_name}' has invalid field 'output_schema_file': "
                    f"file not found at {schema_path}"
                )

            spec = PromptSpec(
                name=prompt_name,
                version=version,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                output_schema_file=output_schema_file,
                template_variables=template_variables,
            )
            specs[prompt_name] = spec
            schema_paths[prompt_name] = schema_path

        if not specs:
            raise PromptValidationError(
                f"No prompt entries found in prompt file: {self._prompt_file}"
            )

        self._specs = specs
        self._schema_paths = schema_paths

    def _read_version(
        self, prompt_name: str, prompt_node: dict[str, Any], top_level_version: Any
    ) -> str:
        """Read version."""
        value = prompt_node.get("version", top_level_version)
        if isinstance(value, str) and value.strip():
            return value

        # Backward-compatible normalization for existing prompt files that
        # store a numeric top-level version only.
        if isinstance(value, (int, float)):
            rendered = str(value).strip()
            if rendered:
                return rendered

        raise PromptValidationError(
            f"Prompt '{prompt_name}' has missing/invalid field 'version' in "
            f"{self._prompt_file}."
        )

    def _read_required_string(
        self, prompt_name: str, prompt_node: dict[str, Any], field_name: str
    ) -> str:
        """Read required string."""
        value = prompt_node.get(field_name)
        if isinstance(value, str) and value.strip():
            return value
        raise PromptValidationError(
            f"Prompt '{prompt_name}' has missing/invalid field '{field_name}' in "
            f"{self._prompt_file}."
        )

    def _read_template_variables(
        self, prompt_name: str, prompt_node: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        """Read template variables."""
        raw_items = prompt_node.get("template_variables", [])
        if raw_items is None:
            return {}
        if not isinstance(raw_items, list):
            raise PromptValidationError(
                f"Prompt '{prompt_name}' has missing/invalid field "
                f"'template_variables' in {self._prompt_file}."
            )

        normalized: dict[str, dict[str, Any]] = {}
        for index, item in enumerate(raw_items):
            if not isinstance(item, dict):
                raise PromptValidationError(
                    f"Prompt '{prompt_name}' has invalid template_variables[{index}] "
                    f"in {self._prompt_file}."
                )

            variable_name = item.get("name")
            if not isinstance(variable_name, str) or not variable_name.strip():
                raise PromptValidationError(
                    f"Prompt '{prompt_name}' has invalid template_variables[{index}] "
                    f"field 'name' in {self._prompt_file}."
                )
            if variable_name in normalized:
                raise PromptValidationError(
                    f"Prompt '{prompt_name}' has duplicate template variable name "
                    f"'{variable_name}' in {self._prompt_file}."
                )

            variable_payload = {k: v for k, v in item.items() if k != "name"}
            normalized[variable_name] = variable_payload

        return normalized

    def _resolve_schema_path(self, path_value: str | Path) -> Path:
        """Resolve schema path from PIKA root (project-independent)."""
        return resolve_path_from_pika_root(path_value)
