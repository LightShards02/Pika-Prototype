from __future__ import annotations

from typing import Any


class ConfigNotFoundError(FileNotFoundError):
    """Raised when a config or schema file path does not exist."""

    def __init__(self, message: str) -> None:
        """Initialize config not found error."""
        super().__init__(message)
        self.message = message


class ConfigParseError(ValueError):
    """Raised when config YAML cannot be parsed into a valid mapping."""

    def __init__(self, message: str) -> None:
        """Initialize config parse error."""
        super().__init__(message)
        self.message = message


class ConfigSchemaValidationError(ValueError):
    """Raised when config fails JSON Schema validation."""

    def __init__(
        self,
        message: str,
        *,
        field_path: str | None = None,
        json_pointer: str | None = None,
        invalid_value: Any | None = None,
    ) -> None:
        """Initialize config schema validation error."""
        self.field_path = field_path
        self.json_pointer = json_pointer
        self.invalid_value = invalid_value
        super().__init__(message)
        self.message = message


class PromptFileNotFoundError(FileNotFoundError):
    """Raised when a prompt file path does not exist."""

    def __init__(self, message: str) -> None:
        """Initialize prompt file not found error."""
        super().__init__(message)
        self.message = message


class PromptParseError(ValueError):
    """Raised when prompt YAML cannot be parsed into a valid mapping."""

    def __init__(self, message: str) -> None:
        """Initialize prompt parse error."""
        super().__init__(message)
        self.message = message


class PromptValidationError(ValueError):
    """Raised when prompt content is missing required fields or types."""

    def __init__(self, message: str) -> None:
        """Initialize prompt validation error."""
        super().__init__(message)
        self.message = message


class PromptNotFoundError(KeyError):
    """Raised when a prompt key cannot be found in the registry."""

    def __init__(self, message: str) -> None:
        """Initialize prompt not found error."""
        super().__init__(message)
        self.message = message


class SafetyPreconditionError(ValueError):
    """Raised when deterministic preflight safety checks fail."""

    def __init__(self, message: str) -> None:
        """Initialize safety precondition error."""
        super().__init__(message)
        self.message = message
