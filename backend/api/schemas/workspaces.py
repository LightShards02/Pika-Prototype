"""Workspace API request/response models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WorkspaceCreateRequest(BaseModel):
    path: str = Field(
        ...,
        description=(
            "Workspace root path. May be absolute or relative. Relative paths are "
            "resolved against the API server's current working directory (matching "
            "the CLI's --project-root semantics)."
        ),
    )


class WorkspaceResponse(BaseModel):
    id: str
    path: str
    exists: bool
    config_resolved: bool
