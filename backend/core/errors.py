from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class PikaError(Exception):
    """Base error for all Pika domain errors."""

    def __init__(self, message: str) -> None:
        """Initialize Pika error."""
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------------------
# Config / Prompt / Safety  (retrofitted to also inherit PikaError)
# ---------------------------------------------------------------------------

class ConfigNotFoundError(PikaError, FileNotFoundError):
    """Raised when a config or schema file path does not exist."""

    def __init__(self, message: str) -> None:
        """Initialize config not found error."""
        super().__init__(message)


class ConfigParseError(PikaError, ValueError):
    """Raised when config YAML cannot be parsed into a valid mapping."""

    def __init__(self, message: str) -> None:
        """Initialize config parse error."""
        super().__init__(message)


class ConfigSchemaValidationError(PikaError, ValueError):
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


class PromptFileNotFoundError(PikaError, FileNotFoundError):
    """Raised when a prompt file path does not exist."""

    def __init__(self, message: str) -> None:
        """Initialize prompt file not found error."""
        super().__init__(message)


class PromptParseError(PikaError, ValueError):
    """Raised when prompt YAML cannot be parsed into a valid mapping."""

    def __init__(self, message: str) -> None:
        """Initialize prompt parse error."""
        super().__init__(message)


class PromptValidationError(PikaError, ValueError):
    """Raised when prompt content is missing required fields or types."""

    def __init__(self, message: str) -> None:
        """Initialize prompt validation error."""
        super().__init__(message)


class PromptNotFoundError(PikaError, KeyError):
    """Raised when a prompt key cannot be found in the registry."""

    def __init__(self, message: str) -> None:
        """Initialize prompt not found error."""
        super().__init__(message)


class SafetyPreconditionError(PikaError, ValueError):
    """Raised when deterministic preflight safety checks fail."""

    def __init__(self, message: str) -> None:
        """Initialize safety precondition error."""
        super().__init__(message)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class AgentInvocationError(PikaError):
    """Agent call failed (timeout, API error, subprocess crash)."""

    def __init__(self, message: str) -> None:
        """Initialize agent invocation error."""
        super().__init__(message)


class AgentSchemaError(PikaError):
    """Agent output failed schema validation after all retries."""

    def __init__(self, message: str) -> None:
        """Initialize agent schema error."""
        super().__init__(message)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class WorksetValidationError(PikaError):
    """CSV/workset schema or column validation failed."""

    def __init__(self, message: str) -> None:
        """Initialize workset validation error."""
        super().__init__(message)


class PlanValidationError(PikaError):
    """Unified plan structural validation failed (non-retryable)."""

    def __init__(self, message: str) -> None:
        """Initialize plan validation error."""
        super().__init__(message)


class BatchValidationError(PikaError):
    """Batch plan, brief scope, or dependency edge validation failed."""

    def __init__(self, message: str) -> None:
        """Initialize batch validation error."""
        super().__init__(message)


# ---------------------------------------------------------------------------
# Patch / Verification
# ---------------------------------------------------------------------------

class PatchError(PikaError):
    """Patch constraint, normalization, apply, or conformance failure."""

    def __init__(self, message: str) -> None:
        """Initialize patch error."""
        super().__init__(message)


class VerificationError(PikaError):
    """Post-patch verification command exited non-zero."""

    def __init__(self, message: str) -> None:
        """Initialize verification error."""
        super().__init__(message)


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------

class ResumeError(PikaError):
    """Resume precondition not met (missing run, unresolved state, etc.)."""

    def __init__(self, message: str) -> None:
        """Initialize resume error."""
        super().__init__(message)
