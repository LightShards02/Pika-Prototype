"""Workspace API request/response models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WorkspaceCreateRequest(BaseModel):
    path: str = Field(
        ...,
        description=(
            "Workspace root path. Must be a relative path; it is resolved under "
            "the API server's workspace base directory ($PIKA_WORKSPACE_BASE_DIR "
            "or <repo_root>/backend/workspaces by default). Absolute paths "
            "are rejected."
        ),
    )
    create: bool = Field(
        default=False,
        description=(
            "If true, the API will mkdir the resolved workspace subdir when it "
            "does not yet exist and seed a minimal valid config/config.yaml from "
            "the bundled default template. The seeding step is idempotent: an "
            "existing config file is never overwritten. Absolute-path and "
            "traversal checks still apply. Defaults to false to preserve the "
            "legacy registration semantics."
        ),
    )


class WorkspaceResponse(BaseModel):
    id: str
    path: str
    exists: bool
    config_resolved: bool
