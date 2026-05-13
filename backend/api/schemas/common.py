"""Common API schemas."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PhaseRunState(str, Enum):
    running = "running"
    completed = "completed"
    blocked = "blocked"
    failed = "failed"


class WorkspaceRef(BaseModel):
    id: str
    path: str


class PhaseRunRef(BaseModel):
    phase_run_id: str
    phase: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None
