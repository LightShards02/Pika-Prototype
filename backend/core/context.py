"""Runtime context for PIKA command execution."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RuntimeContext:
    """Runtime context for command execution.

    project_root: Workspace root — the project PIKA is used to build. Contains
        the project's config, outputs (out/), inputs (SRS, SADS, etc.). All
        project-variable paths in config are relative to this.
    """

    command: str
    dry_run: bool
    verbose: bool
    command_only_validation: bool
    run_id: str
    project_root: str  # Workspace root: the project being built
    config_path: str
    input_overrides: dict[str, str] = field(default_factory=dict)
    resume_run_id: str | None = None  # When set, use this run_id and load resolutions
    resolved_decisions: str | None = None  # Injected into agent prompts on resume
    phase_only: str | None = None  # "load_validate_only" | "decomposition_only" | "agents_only"
