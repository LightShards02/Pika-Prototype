from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from core.errors import (
    ConfigNotFoundError,
    ConfigParseError,
    ConfigSchemaValidationError,
)

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


def _to_dot_path(parts: Iterable[Any]) -> str:
    """Return to dot path."""
    tokens: list[str] = []
    for part in parts:
        if isinstance(part, int):
            if tokens:
                tokens[-1] = f"{tokens[-1]}[{part}]"
            else:
                tokens.append(f"[{part}]")
        else:
            tokens.append(str(part))
    return ".".join(tokens) if tokens else "/"


def _to_json_pointer(parts: Iterable[Any]) -> str:
    """Return to json pointer."""
    tokens = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(tokens) if tokens else "/"


def _small_value(value: Any, *, limit: int = 120) -> str:
    """Return small value."""
    rendered = repr(value)
    if len(rendered) <= limit:
        return rendered
    return rendered[: limit - 3] + "..."


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    """Read yaml mapping."""
    if yaml is None:
        raise ConfigParseError(
            "Missing dependency 'pyyaml'. Install it with: pip install pyyaml"
        )

    if not path.exists() or not path.is_file():
        raise ConfigNotFoundError(f"Config file not found: {path}")

    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigParseError(f"Invalid YAML in config file {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigParseError(f"Unable to read config file {path}: {exc}") from exc

    if loaded is None:
        raise ConfigParseError(f"Config file is empty: {path}")
    if not isinstance(loaded, dict):
        raise ConfigParseError(f"Config root must be a mapping/object: {path}")
    return loaded


def _read_schema(path: Path) -> dict[str, Any]:
    """Read schema."""
    if not path.exists() or not path.is_file():
        raise ConfigNotFoundError(f"Config schema file not found: {path}")
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigSchemaValidationError(
            f"Invalid JSON in schema file {path}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise ConfigSchemaValidationError(
            f"Unable to read schema file {path}: {exc}"
        ) from exc

    if not isinstance(loaded, dict):
        raise ConfigSchemaValidationError(
            f"Schema root must be an object: {path}"
        )
    return loaded


def _validate_with_jsonschema(
    config: dict[str, Any], schema: dict[str, Any], *, schema_path: Path
) -> None:
    """Validate with jsonschema."""
    if Draft202012Validator is None:
        raise ConfigSchemaValidationError(
            "Missing dependency 'jsonschema'. Install it with: pip install jsonschema"
        )

    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ConfigSchemaValidationError(
            f"Invalid config schema in {schema_path}: {exc.message}"
        ) from exc

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(config), key=lambda err: list(err.path))
    if not errors:
        return

    first = errors[0]
    field_path = _to_dot_path(first.path)
    json_pointer = _to_json_pointer(first.path)
    message = f"Config schema validation failed at {field_path}: {first.message}"

    instance_value = first.instance
    if isinstance(instance_value, (str, int, float, bool, type(None), list, dict)):
        rendered = _small_value(instance_value)
        if len(rendered) <= 120:
            message += f" (value={rendered})"

    if len(errors) > 1:
        message += f" [{len(errors)} errors total]"

    raise ConfigSchemaValidationError(
        message,
        field_path=field_path,
        json_pointer=json_pointer,
        invalid_value=instance_value,
    )


def load_and_validate_config(
    config_path: str | Path, schema_path: str | Path = "config/config.schema.json"
) -> dict[str, Any]:
    """Return load and validate config."""
    config_path_obj = Path(config_path).resolve()
    schema_path_obj = Path(schema_path).resolve()

    config = _read_yaml_mapping(config_path_obj)
    schema = _read_schema(schema_path_obj)
    _validate_with_jsonschema(config, schema, schema_path=schema_path_obj)
    return config
