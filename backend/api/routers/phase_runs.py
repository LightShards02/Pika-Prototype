"""Phase-run lookup endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from api.deps import get_phase_run_registry
from api.errors import http_error
from api.phase_runs import PhaseRunRegistry
from api.schemas.common import PhaseRunState
from api.schemas.phases import PhaseRunResponse

router = APIRouter(prefix="/v1/phase-runs", tags=["phase-runs"])


@router.get("/{phase_run_id}", response_model=PhaseRunResponse)
def get_phase_run(
    phase_run_id: str,
    run_registry: PhaseRunRegistry = Depends(get_phase_run_registry),
) -> PhaseRunResponse:
    record = run_registry.get(phase_run_id)
    if record is None:
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "phase_run_not_found",
            f"phase_run {phase_run_id!r} not found",
        )
    return PhaseRunResponse(
        phase_run_id=record["phase_run_id"],
        phase=record["phase"],
        workspace_id=record["workspace_id"],
        chain_id=record.get("chain_id"),
        status=PhaseRunState(record["status"]),
        started_at=record["started_at"],
        ended_at=record.get("ended_at"),
        blocked_at=record.get("blocked_at"),
        inputs=record.get("inputs") or {},
        artifacts_index=record.get("artifacts_index") or {},
        summary=record.get("summary") or {},
        error=record.get("error"),
    )
