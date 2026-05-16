"""Workspace API request/response models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WorkspaceCreateRequest(BaseModel):
    path: str = Field(
        ...,
        description=(
            "Workspace root path. Must be a relative path; it is resolved under "
            "the API server's workspace base directory ($PIKA_WORKSPACE_BASE_DIR "
            "or <repo_root>/dataset/nutrition/backend by default). Absolute paths "
            "are rejected."
        ),
    )


class WorkspaceResponse(BaseModel):
    id: str
    path: str
    exists: bool
    config_resolved: bool
