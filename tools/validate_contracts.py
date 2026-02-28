#!/usr/bin/env python3
"""Strict contract validator for Pika repository artifacts.

This script performs local, deterministic checks only:
- JSON syntax checks
- YAML syntax checks
- Config schema validation
- Cross-file consistency checks between config, prompt contract, schemas, and docs

Output format:
- PASS/FAIL
- Check summary
- Full error list with file + path context (JSON pointer or YAML path)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - runtime dependency check
    yaml = None  # type: ignore

try:
    from jsonschema import Draft202012Validator  # type: ignore
except Exception:  # pragma: no cover - runtime dependency check
    Draft202012Validator = None  # type: ignore


DEFAULT_CONFIG_PATH = Path("config/config.example.yaml")
CONFIG_SCHEMA_PATH = Path("config/config.schema.json")
PROMPT_PATH = Path("prompts/PROMPT.yaml")
CSV_CONTRACTS_PATH = Path("docs/csv_contracts.md")


@dataclass
class ContractError:
    """Represents contract error."""
    check: str
    file: str
    path: str
    message: str


@dataclass
class CheckResult:
    """Represents check result."""
    name: str
    passed: bool
    errors_added: int
    details: str


def _escape_json_pointer_token(token: str) -> str:
    """Return escape json pointer token."""
    return token.replace("~", "~0").replace("/", "~1")


def to_json_pointer(path_parts: Sequence[Any]) -> str:
    """Return to json pointer."""
    if not path_parts:
        return "/"
    tokens = [_escape_json_pointer_token(str(part)) for part in path_parts]
    return "/" + "/".join(tokens)


def to_yaml_path(path_parts: Sequence[Any]) -> str:
    """Return to yaml path."""
    if not path_parts:
        return "/"
    segments: list[str] = []
    for part in path_parts:
        if isinstance(part, int):
            if segments:
                segments[-1] = f"{segments[-1]}[{part}]"
            else:
                segments.append(f"[{part}]")
        else:
            segments.append(str(part))
    return ".".join(segments)


class ContractValidator:
    """Represents contract validator."""
    def __init__(self, repo_root: Path, config_path: Path | None = None) -> None:
        """Initialize contract validator."""
        self.repo_root = repo_root
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self.errors: list[ContractError] = []
        self.summary: list[CheckResult] = []

    def _record_error(self, check: str, file: Path, path: str, message: str) -> None:
        """Return record error."""
        self.errors.append(
            ContractError(
                check=check,
                file=str(file.as_posix()),
                path=path,
                message=message,
            )
        )

    def _run_check(self, name: str, fn: Any) -> None:
        """Run check."""
        before = len(self.errors)
        try:
            details = fn() or ""
        except Exception as exc:  # pragma: no cover - defensive catch
            self._record_error(name, Path("."), "/", f"Unhandled exception: {exc}")
            details = "aborted due to exception"
        added = len(self.errors) - before
        self.summary.append(
            CheckResult(
                name=name,
                passed=(added == 0),
                errors_added=added,
                details=details,
            )
        )

    def _abs(self, rel: Path) -> Path:
        """Return abs."""
        return (self.repo_root / rel).resolve()

    def _load_json(self, check: str, rel_path: Path) -> Any | None:
        """Return load json."""
        path = self._abs(rel_path)
        if not path.exists():
            self._record_error(check, rel_path, "/", "File does not exist")
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            pointer = to_json_pointer([exc.lineno - 1, exc.colno - 1])
            self._record_error(check, rel_path, pointer, f"Invalid JSON: {exc.msg}")
            return None

    def _load_yaml(self, check: str, rel_path: Path) -> Any | None:
        """Return load yaml."""
        if yaml is None:
            self._record_error(
                check,
                rel_path,
                "/",
                "Missing dependency: PyYAML is required to parse YAML files",
            )
            return None
        path = self._abs(rel_path)
        if not path.exists():
            self._record_error(check, rel_path, "/", "File does not exist")
            return None
        try:
            return yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - parser type varies
            self._record_error(check, rel_path, "/", f"Invalid YAML: {exc}")
            return None

    def validate(self) -> int:
        """Return validate."""
        self._run_check("required_files_exist", self._check_required_files_exist)
        self._run_check("json_syntax", self._check_json_syntax)
        self._run_check("yaml_syntax", self._check_yaml_syntax)
        self._run_check("config_schema_validation", self._check_config_schema_validation)
        self._run_check("config_cross_references", self._check_config_cross_references)
        self._run_check("prompt_contract", self._check_prompt_contract)
        self._run_check("agent_schema_contract", self._check_agent_schema_contract)
        self._run_check("csv_contract_doc", self._check_csv_contract_doc)
        self._print_report()
        return 0 if not self.errors else 1

    def _check_required_files_exist(self) -> str:
        """Check required files exist."""
        required = [
            self.config_path,
            CONFIG_SCHEMA_PATH,
            PROMPT_PATH,
            CSV_CONTRACTS_PATH,
            Path("schemas/agent_outputs/index_output.schema.json"),
            Path("schemas/agent_outputs/implement_output.schema.json"),
            Path("schemas/agent_outputs/issue_map_output.schema.json"),
            Path("schemas/agent_outputs/issue_resolve_output.schema.json"),
        ]
        for rel in required:
            if not self._abs(rel).exists():
                self._record_error("required_files_exist", rel, "/", "Missing required file")
        return f"required file presence for {len(required)} contract files"

    def _check_json_syntax(self) -> str:
        """Check json syntax."""
        json_files = [
            CONFIG_SCHEMA_PATH,
            Path("schemas/agent_outputs/index_output.schema.json"),
            Path("schemas/agent_outputs/implement_output.schema.json"),
            Path("schemas/agent_outputs/issue_map_output.schema.json"),
            Path("schemas/agent_outputs/issue_resolve_output.schema.json"),
        ]
        loaded = 0
        for rel in json_files:
            if self._load_json("json_syntax", rel) is not None:
                loaded += 1
        return f"JSON parse for {loaded}/{len(json_files)} files"

    def _check_yaml_syntax(self) -> str:
        """Check yaml syntax."""
        yaml_files = [self.config_path, PROMPT_PATH]
        loaded = 0
        for rel in yaml_files:
            if self._load_yaml("yaml_syntax", rel) is not None:
                loaded += 1
        return f"YAML parse for {loaded}/{len(yaml_files)} files"

    def _check_config_schema_validation(self) -> str:
        """Check config schema validation."""
        if Draft202012Validator is None:
            self._record_error(
                "config_schema_validation",
                CONFIG_SCHEMA_PATH,
                "/",
                "Missing dependency: jsonschema is required for schema validation",
            )
            return "schema validation skipped due to missing jsonschema dependency"

        schema = self._load_json("config_schema_validation", CONFIG_SCHEMA_PATH)
        config = self._load_yaml("config_schema_validation", self.config_path)
        if schema is None or config is None:
            return "schema validation skipped because config/schema could not be loaded"

        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(config), key=lambda e: list(e.path))
        for err in errors:
            cfg_path = to_yaml_path(list(err.path))
            schema_pointer = to_json_pointer(list(err.schema_path))
            self._record_error(
                "config_schema_validation",
                self.config_path,
                cfg_path,
                f"{err.message} (schema: {schema_pointer})",
            )
        return f"{self.config_path.as_posix()} validated against config/config.schema.json"

    def _check_config_cross_references(self) -> str:
        """Check config cross references."""
        config = self._load_yaml("config_cross_references", self.config_path)
        if not isinstance(config, dict):
            return "cross-reference checks skipped because config is invalid"

        prompts_file = self._extract(config, ["prompts", "prompt_file"])
        if isinstance(prompts_file, str):
            rel = Path(prompts_file)
            if not self._abs(rel).exists():
                self._record_error(
                    "config_cross_references",
                    self.config_path,
                    "prompts.prompt_file",
                    f"Referenced prompt file does not exist: {prompts_file}",
                )
        else:
            self._record_error(
                "config_cross_references",
                self.config_path,
                "prompts.prompt_file",
                "Missing or invalid prompts.prompt_file",
            )

        schema_map = self._extract(config, ["schemas"])
        if not isinstance(schema_map, dict):
            self._record_error(
                "config_cross_references",
                self.config_path,
                "schemas",
                "Missing or invalid schemas mapping",
            )
            return "checked config references to prompt and schema files"

        for key, rel_path in schema_map.items():
            ypath = f"schemas.{key}"
            if not isinstance(rel_path, str):
                self._record_error(
                    "config_cross_references",
                    self.config_path,
                    ypath,
                    "Schema path must be a string",
                )
                continue
            rel = Path(rel_path)
            if not self._abs(rel).exists():
                self._record_error(
                    "config_cross_references",
                    self.config_path,
                    ypath,
                    f"Referenced schema file does not exist: {rel_path}",
                )
        return "checked config references to prompt and schema files"

    def _check_prompt_contract(self) -> str:
        """Check prompt contract."""
        prompt = self._load_yaml("prompt_contract", PROMPT_PATH)
        config = self._load_yaml("prompt_contract", self.config_path)
        if not isinstance(prompt, dict):
            return "prompt checks skipped because prompts/PROMPT.yaml is invalid"

        version = prompt.get("version")
        if not isinstance(version, int) or version < 1:
            self._record_error(
                "prompt_contract",
                PROMPT_PATH,
                "version",
                "version must be an integer >= 1",
            )

        prompts = prompt.get("prompts")
        if not isinstance(prompts, dict) or not prompts:
            self._record_error(
                "prompt_contract",
                PROMPT_PATH,
                "prompts",
                "prompts must be a non-empty mapping",
            )
            return "checked prompt structure, template variables, and placeholders"

        schema_paths_from_config: set[str] = set()
        if isinstance(config, dict):
            schemas = config.get("schemas", {})
            if isinstance(schemas, dict):
                schema_paths_from_config = {
                    value for value in schemas.values() if isinstance(value, str)
                }

        for prompt_name, definition in prompts.items():
            base = f"prompts.{prompt_name}"
            if not isinstance(definition, dict):
                self._record_error(
                    "prompt_contract",
                    PROMPT_PATH,
                    base,
                    "Prompt definition must be an object",
                )
                continue

            for key in ["description", "output_schema_file", "template_variables", "system", "user"]:
                if key not in definition:
                    self._record_error(
                        "prompt_contract",
                        PROMPT_PATH,
                        f"{base}.{key}",
                        "Missing required prompt key",
                    )

            output_schema_file = definition.get("output_schema_file")
            if isinstance(output_schema_file, str):
                if not self._abs(Path(output_schema_file)).exists():
                    self._record_error(
                        "prompt_contract",
                        PROMPT_PATH,
                        f"{base}.output_schema_file",
                        f"Referenced schema file does not exist: {output_schema_file}",
                    )
                if schema_paths_from_config and output_schema_file not in schema_paths_from_config:
                    self._record_error(
                        "prompt_contract",
                        PROMPT_PATH,
                        f"{base}.output_schema_file",
                        "Schema path is not listed in config.schemas",
                    )
            else:
                self._record_error(
                    "prompt_contract",
                    PROMPT_PATH,
                    f"{base}.output_schema_file",
                    "output_schema_file must be a string",
                )

            template_vars = definition.get("template_variables")
            var_names: list[str] = []
            if not isinstance(template_vars, list):
                self._record_error(
                    "prompt_contract",
                    PROMPT_PATH,
                    f"{base}.template_variables",
                    "template_variables must be a list",
                )
                continue

            for i, var in enumerate(template_vars):
                vbase = f"{base}.template_variables[{i}]"
                if not isinstance(var, dict):
                    self._record_error(
                        "prompt_contract",
                        PROMPT_PATH,
                        vbase,
                        "Each template variable must be an object",
                    )
                    continue
                for key in ["name", "required", "description"]:
                    if key not in var:
                        self._record_error(
                            "prompt_contract",
                            PROMPT_PATH,
                            f"{vbase}.{key}",
                            "Missing required template variable key",
                        )
                name = var.get("name")
                required = var.get("required")
                if isinstance(name, str):
                    if name in var_names:
                        self._record_error(
                            "prompt_contract",
                            PROMPT_PATH,
                            f"{vbase}.name",
                            f"Duplicate template variable name: {name}",
                        )
                    var_names.append(name)
                else:
                    self._record_error(
                        "prompt_contract",
                        PROMPT_PATH,
                        f"{vbase}.name",
                        "name must be a string",
                    )
                if not isinstance(required, bool):
                    self._record_error(
                        "prompt_contract",
                        PROMPT_PATH,
                        f"{vbase}.required",
                        "required must be a boolean",
                    )

            if "output_schema_file" not in var_names:
                self._record_error(
                    "prompt_contract",
                    PROMPT_PATH,
                    f"{base}.template_variables",
                    "template_variables must include output_schema_file",
                )
            else:
                for i, var in enumerate(template_vars):
                    if (
                        isinstance(var, dict)
                        and var.get("name") == "output_schema_file"
                        and var.get("required") is not True
                    ):
                        self._record_error(
                            "prompt_contract",
                            PROMPT_PATH,
                            f"{base}.template_variables[{i}].required",
                            "output_schema_file template variable must have required=true",
                        )

            placeholder_names = set()
            for key in ("system", "user"):
                value = definition.get(key, "")
                if not isinstance(value, str):
                    self._record_error(
                        "prompt_contract",
                        PROMPT_PATH,
                        f"{base}.{key}",
                        f"{key} must be a string",
                    )
                    continue
                placeholder_names.update(re.findall(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}", value))

            unknown = sorted(name for name in placeholder_names if name not in var_names)
            for name in unknown:
                self._record_error(
                    "prompt_contract",
                    PROMPT_PATH,
                    base,
                    f"Placeholder {{{{{name}}}}} is not declared in template_variables",
                )

        return "checked prompt structure, template variables, and placeholders"

    def _check_agent_schema_contract(self) -> str:
        """Check agent schema contract. Supports both flat and oneOf schemas."""
        config = self._load_yaml("agent_schema_contract", self.config_path)
        if not isinstance(config, dict):
            return "agent schema checks skipped because config is invalid"
        schema_map = self._extract(config, ["schemas"])
        if not isinstance(schema_map, dict):
            self._record_error(
                "agent_schema_contract",
                self.config_path,
                "schemas",
                "config.schemas must be an object",
            )
            return "checked agent schema invariants"

        loaded = 0
        for key, rel in schema_map.items():
            if not isinstance(rel, str):
                self._record_error(
                    "agent_schema_contract",
                    self.config_path,
                    f"schemas.{key}",
                    "Schema reference must be a string",
                )
                continue
            rel_path = Path(rel)
            schema = self._load_json("agent_schema_contract", rel_path)
            if not isinstance(schema, dict):
                continue
            loaded += 1
            self._check_agent_schema_invariants(schema, rel_path)
        return (
            f"checked top-level created_at, manual_resolution_items, and run_summary "
            f"invariants in {loaded} schema files"
        )

    def _check_agent_schema_invariants(self, schema: dict, rel_path: Path) -> None:
        """Check created_at, manual_resolution_items, run_summary invariants. Handles oneOf."""
        variants: list[dict] = []
        if "oneOf" in schema:
            one_of = schema.get("oneOf")
            if isinstance(one_of, list):
                variants = [v for v in one_of if isinstance(v, dict)]
        if not variants:
            variants = [schema]

        for idx, variant in enumerate(variants):
            prefix = f"/oneOf[{idx}]" if "oneOf" in schema else ""
            required = variant.get("required")
            if not isinstance(required, list):
                self._record_error(
                    "agent_schema_contract",
                    rel_path,
                    f"{prefix}/required",
                    "Required must be an array",
                )
            elif "created_at" not in required:
                self._record_error(
                    "agent_schema_contract",
                    rel_path,
                    f"{prefix}/required",
                    "Missing required field: created_at",
                )

            props = variant.get("properties", {})
            created_at_root = props.get("created_at")
            if isinstance(created_at_root, dict):
                if created_at_root.get("type") != "string":
                    self._record_error(
                        "agent_schema_contract",
                        rel_path,
                        f"{prefix}/properties/created_at/type",
                        'created_at.type must be "string"',
                    )
                if created_at_root.get("format") != "date-time":
                    self._record_error(
                        "agent_schema_contract",
                        rel_path,
                        f"{prefix}/properties/created_at/format",
                        'created_at.format must be "date-time"',
                    )

            manual_items = props.get("manual_resolution_items")
            if isinstance(manual_items, dict) and "items" in manual_items:
                items_schema = manual_items["items"]
                if "$ref" in items_schema:
                    ref_name = items_schema["$ref"].split("/")[-1]
                    defs = schema.get("$defs", {})
                    manual_def = defs.get(ref_name)
                    if isinstance(manual_def, dict):
                        manual_req = manual_def.get("required", [])
                        for field in ("command", "entity_type", "entity_id", "reason", "details", "created_at"):
                            if field not in manual_req:
                                self._record_error(
                                    "agent_schema_contract",
                                    rel_path,
                                    f"/$defs/{ref_name}/required",
                                    f"Missing required manual resolution field: {field}",
                                )
                elif isinstance(items_schema, dict):
                    manual_req = items_schema.get("required", [])
                    for field in ("command", "entity_type", "entity_id", "reason", "details", "created_at"):
                        if field not in manual_req:
                            self._record_error(
                                "agent_schema_contract",
                                rel_path,
                                f"{prefix}/manual_resolution_items/items/required",
                                f"Missing required manual resolution field: {field}",
                            )

            run_summary = props.get("run_summary")
            run_req: list = []
            if isinstance(run_summary, dict):
                if "$ref" in run_summary:
                    ref_name = run_summary["$ref"].split("/")[-1]
                    defs = schema.get("$defs", {})
                    run_def = defs.get(ref_name)
                    run_req = run_def.get("required", []) if isinstance(run_def, dict) else []
                else:
                    run_req = run_summary.get("required", [])
            if run_req:
                for field in ("command", "status", "summary", "blocking_items", "storage_file"):
                    if field not in run_req:
                        self._record_error(
                            "agent_schema_contract",
                            rel_path,
                            f"{prefix}/run_summary/required",
                            f"Missing run_summary required field: {field}",
                        )

    def _check_csv_contract_doc(self) -> str:
        """Check csv contract doc."""
        config = self._load_yaml("csv_contract_doc", self.config_path)
        if not isinstance(config, dict):
            return "CSV doc checks skipped because config is invalid"
        path = self._abs(CSV_CONTRACTS_PATH)
        if not path.exists():
            self._record_error("csv_contract_doc", CSV_CONTRACTS_PATH, "/", "File does not exist")
            return "csv contract markdown checks skipped"
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()

        design_columns = self._parse_markdown_table_columns(lines, "Design Spec Table Contract")
        issue_columns = self._parse_markdown_table_columns(lines, "Issue Tracking Table Contract")

        expected_design = self._extract(config, ["csv_contracts", "design_spec", "add_if_missing"])
        expected_issue = self._extract(config, ["csv_contracts", "issue_tracking", "add_if_missing"])
        if isinstance(expected_design, list):
            for col in expected_design:
                if isinstance(col, str) and col not in design_columns:
                    self._record_error(
                        "csv_contract_doc",
                        CSV_CONTRACTS_PATH,
                        "section:Design Spec Table Contract",
                        f"Column from config is missing in design table: {col}",
                    )
        else:
            self._record_error(
                "csv_contract_doc",
                self.config_path,
                "csv_contracts.design_spec.add_if_missing",
                "Expected list of columns",
            )

        if isinstance(expected_issue, list):
            for col in expected_issue:
                if isinstance(col, str) and col not in issue_columns:
                    self._record_error(
                        "csv_contract_doc",
                        CSV_CONTRACTS_PATH,
                        "section:Issue Tracking Table Contract",
                        f"Column from config is missing in issue table: {col}",
                    )
        else:
            self._record_error(
                "csv_contract_doc",
                self.config_path,
                "csv_contracts.issue_tracking.add_if_missing",
                "Expected list of columns",
            )

        if "created_at" not in text:
            self._record_error(
                "csv_contract_doc",
                CSV_CONTRACTS_PATH,
                "section:Centralized Manual Resolution File",
                "Manual resolution contract must include created_at",
            )

        author_section = self._extract_markdown_section(lines, "author Column Rules")
        if not author_section:
            self._record_error(
                "csv_contract_doc",
                CSV_CONTRACTS_PATH,
                "section:author Column Rules",
                "Missing author column rules section",
            )
        else:
            section_text = "\n".join(author_section).lower()
            if "source" not in section_text:
                self._record_error(
                    "csv_contract_doc",
                    CSV_CONTRACTS_PATH,
                    "section:author Column Rules",
                    "Author rules must mention source default",
                )
            if "agent" not in section_text:
                self._record_error(
                    "csv_contract_doc",
                    CSV_CONTRACTS_PATH,
                    "section:author Column Rules",
                    "Author rules must mention agent-updated behavior",
                )

        return "checked csv_contracts.md tables and required sections"

    @staticmethod
    def _extract(container: Any, path: Sequence[Any]) -> Any | None:
        """Return extract."""
        cur = container
        for part in path:
            if isinstance(part, int):
                if not isinstance(cur, list) or part >= len(cur):
                    return None
                cur = cur[part]
            else:
                if not isinstance(cur, dict) or part not in cur:
                    return None
                cur = cur[part]
        return cur

    @staticmethod
    def _json_path_get(container: Any, path: Sequence[str]) -> Any | None:
        """Return json path get."""
        cur = container
        for part in path:
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        return cur

    @staticmethod
    def _extract_markdown_section(lines: list[str], heading: str) -> list[str]:
        """Extract markdown section."""
        start = None
        heading_pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$")
        for idx, line in enumerate(lines):
            if heading_pattern.match(line.strip()):
                start = idx + 1
                break
        if start is None:
            return []
        end = len(lines)
        for idx in range(start, len(lines)):
            if lines[idx].startswith("## "):
                end = idx
                break
        return lines[start:end]

    def _parse_markdown_table_columns(self, lines: list[str], section_heading: str) -> set[str]:
        """Parse markdown table columns."""
        section = self._extract_markdown_section(lines, section_heading)
        columns: set[str] = set()
        for line in section:
            stripped = line.strip()
            if not stripped.startswith("|"):
                continue
            cells = [cell.strip() for cell in stripped.split("|")[1:-1]]
            if not cells:
                continue
            first = cells[0]
            if first.lower() in {"column", "---"}:
                continue
            if set(first) == {"-"}:
                continue
            columns.add(first)
        return columns

    def _print_report(self) -> None:
        """Return print report."""
        overall = "PASS" if not self.errors else "FAIL"
        print(overall)
        print()
        print("Check Summary:")
        for result in self.summary:
            status = "PASS" if result.passed else "FAIL"
            print(f"- [{status}] {result.name}: {result.details}")
        print()
        if self.errors:
            print(f"Errors ({len(self.errors)}):")
            for idx, error in enumerate(self.errors, start=1):
                print(
                    f"{idx}. [{error.check}] {error.file} @ {error.path}: {error.message}"
                )
        else:
            print("Errors (0): none")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    """Parse args."""
    parser = argparse.ArgumentParser(description="Validate Pika contract files.")
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Path to repository root (default: current directory)",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Config file path relative to repo root (default: config/config.example.yaml)",
    )
    return parser.parse_args(list(argv))


def main(argv: Iterable[str]) -> int:
    """Run the main entry point."""
    args = parse_args(argv)
    validator = ContractValidator(
        repo_root=Path(args.repo_root).resolve(),
        config_path=Path(args.config),
    )
    return validator.validate()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
