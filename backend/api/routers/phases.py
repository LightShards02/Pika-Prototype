"""Phase catalog + phase-run creation endpoints."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, status

from api.deps import (
    get_phase_registry_dep,
    get_phase_run_registry,
    get_workspace_store,
    load_workspace_config,
)
from api.errors import http_error
from api.jobs import generate_phase_run_id, phase_run_dir_for
from api.phase_registry import (
    PhaseBlocked,
    PhaseCompleted,
    PhaseContract,
    PhaseFailed,
    PhaseRegistry,
)
from api.phase_runs import PhaseRunRegistry
from api.schemas.common import PhaseRunState
from api.schemas.phases import (
    PhaseContractModel,
    PhaseInputModel,
    PhaseOutputModel,
    PhaseRunCreateRequest,
    PhaseRunResponse,
)
from api.workspaces import WorkspaceStore
from core.context import RuntimeContext
from core.logger import init_run_logger
from core.time_utils import format_timestamp_local_minutes

router = APIRouter(prefix="/v1/phases", tags=["phases"])


def _contract_to_model(contract: PhaseContract) -> PhaseContractModel:
    return PhaseContractModel(
        name=contract.name,
        command=contract.command,
        inputs=[
            PhaseInputModel(
                name=i.name,
                kind=i.kind,
                required=i.required,
                description=i.description,
                ref_phase=i.ref_phase,
            )
            for i in contract.inputs
        ],
        outputs=[
            PhaseOutputModel(
                name=o.name,
                path=o.path,
                scope=o.scope,
                schema_ref=o.schema_ref,
            )
            for o in contract.outputs
        ],
        recommended_prerequisites=list(contract.recommended_prerequisites),
        can_block=contract.can_block,
        destructive=contract.destructive,
        description=contract.description,
    )


@router.get("", response_model=list[PhaseContractModel])
def list_phases(
    registry: PhaseRegistry = Depends(get_phase_registry_dep),
) -> list[PhaseContractModel]:
    return [_contract_to_model(c) for c in sorted(registry.all_contracts(), key=lambda c: c.name)]


@router.get("/{phase_name}", response_model=PhaseContractModel)
def get_phase(
    phase_name: str,
    registry: PhaseRegistry = Depends(get_phase_registry_dep),
) -> PhaseContractModel:
    contract = registry.contract(phase_name)
    if contract is None:
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "phase_not_found",
            f"phase {phase_name!r} is not registered",
        )
    return _contract_to_model(contract)


def _resolve_workspace_relative_path(workspace_root: Path, raw: str) -> Path:
    """Resolve a workspace-relative or absolute path under the workspace root.

    Rejects paths that escape the workspace root.
    """
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = (workspace_root / candidate).resolve()
    else:
        candidate = candidate.resolve()
    workspace_root_resolved = workspace_root.resolve()
    try:
        candidate.relative_to(workspace_root_resolved)
    except ValueError as exc:
        raise ValueError(
            f"input path {raw!r} resolves outside workspace root {workspace_root_resolved}"
        ) from exc
    return candidate


def _resolve_inputs(
    contract: PhaseContract,
    workspace_root: Path,
    raw_inputs: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Validate inputs against contract, resolve paths. Returns (resolved, errors)."""
    resolved: dict[str, Any] = {}
    errors: list[str] = []
    for spec in contract.inputs:
        if spec.name not in raw_inputs or raw_inputs[spec.name] is None:
            if spec.required:
                errors.append(f"missing required input: {spec.name}")
            continue
        value = raw_inputs[spec.name]
        if spec.kind in ("path", "workspace_relative_path"):
            if not isinstance(value, str) or not value.strip():
                errors.append(f"input {spec.name} must be a non-empty string")
                continue
            try:
                resolved[spec.name] = _resolve_workspace_relative_path(workspace_root, value.strip())
            except ValueError as exc:
                errors.append(str(exc))
        else:
            resolved[spec.name] = value
    return resolved, errors


def _build_runtime_context(
    *,
    command: str,
    phase_run_id: str,
    workspace_root: Path,
    config_path: Path,
    overrides: dict[str, str],
) -> RuntimeContext:
    return RuntimeContext(
        command=command,
        dry_run=False,
        verbose=False,
        command_only_validation=False,
        run_id=phase_run_id,
        project_root=str(workspace_root),
        config_path=str(config_path),
        input_overrides=overrides,
    )


def _write_run_meta(meta_path: Path, payload: dict[str, Any]) -> None:
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


@router.post(
    "/{phase_name}/runs",
    response_model=PhaseRunResponse,
    status_code=status.HTTP_200_OK,
)
def create_phase_run(
    phase_name: str,
    payload: PhaseRunCreateRequest,
    registry: PhaseRegistry = Depends(get_phase_registry_dep),
    run_registry: PhaseRunRegistry = Depends(get_phase_run_registry),
    workspace_store: WorkspaceStore = Depends(get_workspace_store),
) -> PhaseRunResponse:
    entry = registry.get(phase_name)
    if entry is None:
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "phase_not_found",
            f"phase {phase_name!r} is not registered",
        )
    contract, runner = entry

    workspace = workspace_store.get(payload.workspace_id)
    if workspace is None:
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "workspace_not_found",
            f"workspace {payload.workspace_id!r} not found",
        )
    workspace_root = Path(workspace.path)

    resolved_inputs, errors = _resolve_inputs(contract, workspace_root, payload.inputs)
    has_traversal = any("outside workspace root" in e for e in errors)
    if errors:
        if has_traversal:
            raise http_error(
                status.HTTP_400_BAD_REQUEST,
                "input_outside_workspace",
                errors[0],
                details={"errors": errors},
            )
        raise http_error(
            422,
            "inputs_invalid",
            "; ".join(errors),
            details={"errors": errors},
        )

    config = load_workspace_config(workspace_root)
    if config is None:
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "workspace_config_missing",
            f"no config file found under {workspace_root}",
        )

    phase_run_id = generate_phase_run_id()
    phase_run_dir = phase_run_dir_for(config, workspace_root, phase_name, phase_run_id)
    phase_run_dir.mkdir(parents=True, exist_ok=True)

    overrides: dict[str, str] = {}
    if "design_spec_path" in resolved_inputs:
        overrides["design_spec_path"] = str(resolved_inputs["design_spec_path"])
    ctx = _build_runtime_context(
        command=contract.command,
        phase_run_id=phase_run_id,
        workspace_root=workspace_root,
        config_path=workspace_root / "config.yaml",
        overrides=overrides,
    )

    init_run_logger(project_root=workspace_root, config=config, ctx=ctx)

    started_at = format_timestamp_local_minutes()
    inputs_record = {k: str(v) if isinstance(v, Path) else v for k, v in resolved_inputs.items()}

    running_meta = {
        "phase": phase_name,
        "phase_run_id": phase_run_id,
        "workspace_id": payload.workspace_id,
        "chain_id": payload.chain_id,
        "status": PhaseRunState.running.value,
        "started_at": started_at,
        "ended_at": None,
        "blocked_at": None,
        "inputs": inputs_record,
        "artifacts_index": {},
        "summary": {},
        "error": None,
    }
    _write_run_meta(phase_run_dir / "run_meta.json", running_meta)
    run_registry.put(running_meta)

    try:
        result = runner(config, ctx, phase_run_dir, resolved_inputs)
    except Exception as exc:  # noqa: BLE001
        ended_at = format_timestamp_local_minutes()
        meta = {
            "phase": phase_name,
            "phase_run_id": phase_run_id,
            "workspace_id": payload.workspace_id,
            "chain_id": payload.chain_id,
            "status": PhaseRunState.failed.value,
            "started_at": started_at,
            "ended_at": ended_at,
            "blocked_at": None,
            "inputs": inputs_record,
            "artifacts_index": {},
            "summary": {},
            "error": {"code": "runner_exception", "message": str(exc)},
        }
        _write_run_meta(phase_run_dir / "run_meta.json", meta)
        run_registry.put(meta)
        raise http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "runner_exception",
            str(exc),
        ) from exc

    ended_at = format_timestamp_local_minutes()
    if isinstance(result, PhaseCompleted):
        meta = {
            "phase": phase_name,
            "phase_run_id": phase_run_id,
            "workspace_id": payload.workspace_id,
            "chain_id": payload.chain_id,
            "status": PhaseRunState.completed.value,
            "started_at": started_at,
            "ended_at": ended_at,
            "blocked_at": None,
            "inputs": inputs_record,
            "artifacts_index": result.artifacts_index,
            "summary": result.summary,
            "error": None,
        }
    elif isinstance(result, PhaseBlocked):
        meta = {
            "phase": phase_name,
            "phase_run_id": phase_run_id,
            "workspace_id": payload.workspace_id,
            "chain_id": payload.chain_id,
            "status": PhaseRunState.blocked.value,
            "started_at": started_at,
            "ended_at": None,
            "blocked_at": ended_at,
            "inputs": inputs_record,
            "artifacts_index": {},
            "summary": {
                "manual_dir": str(result.manual_dir),
                "item_count": result.item_count,
                "blocking_reason": result.blocking_reason,
            },
            "error": None,
        }
    else:
        failure: PhaseFailed = result
        meta = {
            "phase": phase_name,
            "phase_run_id": phase_run_id,
            "workspace_id": payload.workspace_id,
            "chain_id": payload.chain_id,
            "status": PhaseRunState.failed.value,
            "started_at": started_at,
            "ended_at": ended_at,
            "blocked_at": None,
            "inputs": inputs_record,
            "artifacts_index": failure.recoverable_artifacts,
            "summary": {},
            "error": {"code": failure.error_code, "message": failure.message},
        }

    _write_run_meta(phase_run_dir / "run_meta.json", meta)
    run_registry.put(meta)

    if isinstance(result, PhaseFailed):
        raise http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            result.error_code,
            result.message,
            details={"phase_run_id": phase_run_id},
        )

    return PhaseRunResponse(
        phase_run_id=phase_run_id,
        phase=phase_name,
        workspace_id=payload.workspace_id,
        chain_id=payload.chain_id,
        status=PhaseRunState(meta["status"]),
        started_at=started_at,
        ended_at=meta.get("ended_at"),
        blocked_at=meta.get("blocked_at"),
        inputs=inputs_record,
        artifacts_index=meta.get("artifacts_index") or {},
        summary=meta.get("summary") or {},
        error=meta.get("error"),
    )
