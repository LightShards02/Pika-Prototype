"""Phase / phase-run API models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from api.schemas.common import PhaseRunState


class PhaseInputModel(BaseModel):
    name: str
    kind: str
    required: bool
    description: str = ""
    ref_phase: str | None = None


class PhaseOutputModel(BaseModel):
    name: str
    path: str
    scope: str
    schema_ref: str | None = None


class PhaseContractModel(BaseModel):
    name: str
    command: str
    inputs: list[PhaseInputModel]
    outputs: list[PhaseOutputModel]
    recommended_prerequisites: list[str] = Field(default_factory=list)
    can_block: bool = False
    destructive: bool = False
    description: str = ""
    async_execution: bool = False


class PhaseRunCreateRequest(BaseModel):
    workspace_id: str
    chain_id: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)


class PhaseRunResponse(BaseModel):
    phase_run_id: str
    phase: str
    workspace_id: str
    chain_id: str | None = None
    status: PhaseRunState
    started_at: str
    ended_at: str | None = None
    blocked_at: str | None = None
    inputs: dict[str, Any]
    artifacts_index: dict[str, str] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
    events_url: str | None = None
