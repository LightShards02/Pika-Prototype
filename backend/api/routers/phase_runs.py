"""Phase-run endpoints: lookup, SSE events, manual resolution flow, cancel, raw replicas."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from api.adapters.stderr_capture import install_stderr_capture
from api.deps import (
    get_event_bus,
    get_phase_registry_dep,
    get_phase_run_registry,
    get_workspace_lock_manager,
    get_workspace_store,
    load_workspace_config,
)
from api.errors import http_error
from api.events import PhaseRunEventBus
from api.jobs import phase_run_dir_for
from api.phase_registry import PhaseRegistry
from api.phase_runs import PhaseRunRegistry
from api.schemas.common import PhaseRunState
from api.schemas.phases import PhaseRunResponse
from api.workspace_lock import WorkspaceLockManager
from api.workspaces import WorkspaceStore
from core.context import RuntimeContext
from core.resolution import load_resolution_file, validate_resolutions
from core.time_utils import format_timestamp_local_minutes

router = APIRouter(prefix="/v1/phase-runs", tags=["phase-runs"])


_TERMINAL_STATES = {
    PhaseRunState.completed.value,
    PhaseRunState.blocked.value,
    PhaseRunState.failed.value,
}


def _events_url(phase_run_id: str) -> str:
    return f"/v1/phase-runs/{phase_run_id}/events"


def _terminal_event_payload(meta: dict[str, Any], phase_run_id: str) -> dict[str, Any]:
    """Return the SSE payload shape for a terminal event.

    completed/blocked -> full PhaseRunResponse body.
    failed -> ErrorBody {code, message, details?} from meta.error.
    """
    status_val = meta.get("status")
    if status_val == "failed":
        error = meta.get("error") or {}
        body: dict[str, Any] = {
            "code": error.get("code", "unknown"),
            "message": error.get("message", ""),
        }
        details = error.get("details")
        if details is not None:
            body["details"] = details
        body["phase_run_id"] = phase_run_id
        return body
    return _response_from_meta(meta, _events_url(phase_run_id)).model_dump()


def _response_from_meta(meta: dict[str, Any], events_url: str | None) -> PhaseRunResponse:
    return PhaseRunResponse(
        phase_run_id=meta["phase_run_id"],
        phase=meta["phase"],
        workspace_id=meta["workspace_id"],
        chain_id=meta.get("chain_id"),
        status=PhaseRunState(meta["status"]),
        started_at=meta["started_at"],
        ended_at=meta.get("ended_at"),
        blocked_at=meta.get("blocked_at"),
        inputs=meta.get("inputs") or {},
        artifacts_index=meta.get("artifacts_index") or {},
        summary=meta.get("summary") or {},
        error=meta.get("error"),
        events_url=events_url,
    )


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
    return _response_from_meta(record, _events_url(phase_run_id))


def _phase_run_dir_from_meta(
    meta: dict[str, Any],
    workspace_store: WorkspaceStore,
) -> Path | None:
    workspace = workspace_store.get(meta["workspace_id"])
    if workspace is None:
        return None
    workspace_root = Path(workspace.path)
    config = load_workspace_config(workspace_root)
    if config is None:
        return None
    return phase_run_dir_for(config, workspace_root, meta["phase"], meta["phase_run_id"])


def _load_stage_file(manual_dir: Path) -> tuple[str, dict[str, Any] | None]:
    """Return (stage_name, stage_payload) by reading the most recent <stage>.json file."""
    candidates = list(manual_dir.glob("*.json"))
    if not candidates:
        return ("", None)
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    stage_file = candidates[0]
    try:
        return (stage_file.stem, json.loads(stage_file.read_text(encoding="utf-8")))
    except Exception:
        return (stage_file.stem, None)


@router.get("/{phase_run_id}/resolutions")
def get_resolutions(
    phase_run_id: str,
    run_registry: PhaseRunRegistry = Depends(get_phase_run_registry),
    workspace_store: WorkspaceStore = Depends(get_workspace_store),
) -> dict[str, Any]:
    meta = run_registry.get(phase_run_id)
    if meta is None:
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "phase_run_not_found",
            f"phase_run {phase_run_id!r} not found",
        )
    if meta["status"] != PhaseRunState.blocked.value:
        raise http_error(
            status.HTTP_409_CONFLICT,
            "run_not_blocked",
            f"phase_run {phase_run_id!r} is not in blocked state (status={meta['status']!r})",
        )

    phase_run_dir = _phase_run_dir_from_meta(meta, workspace_store)
    if phase_run_dir is None:
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "phase_run_dir_not_found",
            f"workspace or config for phase_run {phase_run_id!r} could not be resolved",
        )

    manual_dir = phase_run_dir / "manual_resolution"
    stage_name, stage_payload = _load_stage_file(manual_dir)
    resolutions = load_resolution_file(phase_run_dir) or {}
    items = resolutions.get("items") or []
    appendix_recommendations: list[Any] = []
    if isinstance(stage_payload, dict):
        recs = stage_payload.get("appendix_recommendations")
        if isinstance(recs, list):
            appendix_recommendations = recs

    return {
        "phase_run_id": phase_run_id,
        "stage": stage_name,
        "command": resolutions.get("command", meta["phase"].split(".", 1)[0]),
        "run_id": phase_run_id,
        "items": items,
        "appendix_recommendations": appendix_recommendations,
    }


class _ResolutionItemUpdate(BaseModel):
    item_id: str
    decision: dict[str, Any] = Field(default_factory=dict)
    manual_edit_text: str | None = None


class _ResolutionsUpdate(BaseModel):
    items: list[_ResolutionItemUpdate]


@router.put("/{phase_run_id}/resolutions")
def put_resolutions(
    phase_run_id: str,
    payload: _ResolutionsUpdate,
    run_registry: PhaseRunRegistry = Depends(get_phase_run_registry),
    workspace_store: WorkspaceStore = Depends(get_workspace_store),
) -> dict[str, Any]:
    meta = run_registry.get(phase_run_id)
    if meta is None:
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "phase_run_not_found",
            f"phase_run {phase_run_id!r} not found",
        )
    if meta["status"] != PhaseRunState.blocked.value:
        raise http_error(
            status.HTTP_409_CONFLICT,
            "run_not_blocked",
            f"phase_run {phase_run_id!r} is not in blocked state",
        )

    phase_run_dir = _phase_run_dir_from_meta(meta, workspace_store)
    if phase_run_dir is None:
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "phase_run_dir_not_found",
            f"workspace or config for phase_run {phase_run_id!r} could not be resolved",
        )
    resolutions_path = phase_run_dir / "manual_resolution" / "resolutions.yaml"
    if not resolutions_path.exists():
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "resolutions_not_found",
            f"resolutions.yaml not found under phase_run_dir for {phase_run_id!r}",
        )

    with open(resolutions_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    items = data.get("items") or []
    items_by_id: dict[str, dict[str, Any]] = {
        str(it.get("item_id")): it for it in items if isinstance(it, dict)
    }

    errors: list[dict[str, Any]] = []
    for update in payload.items:
        target = items_by_id.get(update.item_id)
        if target is None:
            errors.append({"item_id": update.item_id, "error": "unknown_item_id"})
            continue
        decision = update.decision or {}
        chosen = decision.get("chosen_option_id")
        free_text = decision.get("free_text")
        if chosen is not None:
            target["chosen_option_id"] = chosen
        if free_text is not None:
            target["free_text"] = free_text
        if "editor_output" in decision:
            target["editor_output"] = decision["editor_output"]
        if update.manual_edit_text is not None:
            target["manual_edit_text"] = update.manual_edit_text
            target.setdefault("manual_edit_spec_id", target.get("spec_id"))
            target.setdefault("manual_edit_field", target.get("field") or "requirement")

    if errors:
        raise http_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "items_invalid",
            "one or more items did not match the on-disk resolutions",
            details={"errors": errors},
        )

    with open(resolutions_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    valid, validation_errors = validate_resolutions(data)
    resolved_count = 0
    unresolved_count = 0
    for it in data.get("items") or []:
        if not isinstance(it, dict):
            continue
        chosen = it.get("chosen_option_id")
        free_text = (it.get("free_text") or "").strip() if isinstance(it.get("free_text"), str) else ""
        manual_text = (it.get("manual_edit_text") or "").strip() if isinstance(it.get("manual_edit_text"), str) else ""
        if chosen or free_text or manual_text:
            resolved_count += 1
        else:
            unresolved_count += 1

    response: dict[str, Any] = {
        "valid": valid,
        "resolved_count": resolved_count,
        "unresolved_count": unresolved_count,
    }
    if not valid:
        response["errors"] = validation_errors
    return response


def _build_runtime_context_for_resume(
    *,
    command: str,
    phase_run_id: str,
    workspace_root: Path,
    inputs: dict[str, Any],
) -> RuntimeContext:
    overrides: dict[str, str] = {}
    if "design_spec_path" in inputs and inputs["design_spec_path"]:
        overrides["design_spec_path"] = str(inputs["design_spec_path"])
    return RuntimeContext(
        command=command,
        dry_run=False,
        verbose=False,
        command_only_validation=False,
        run_id=phase_run_id,
        project_root=str(workspace_root),
        config_path=str(workspace_root / "config.yaml"),
        input_overrides=overrides,
    )


async def _run_resume_phase(
    *,
    phase_run_id: str,
    meta: dict[str, Any],
    workspace_store: WorkspaceStore,
    registry: PhaseRegistry,
    run_registry: PhaseRunRegistry,
    event_bus: PhaseRunEventBus,
    lock_manager: WorkspaceLockManager,
) -> None:
    from api.routers.phases import (
        _build_terminal_meta,
        _persist_runner_exception,
        _persist_terminal_result,
        _response_from_meta as _resp_from_meta,
    )

    workspace = workspace_store.get(meta["workspace_id"])
    if workspace is None:
        return
    workspace_root = Path(workspace.path)
    config = load_workspace_config(workspace_root)
    if config is None:
        return

    entry = registry.get(meta["phase"])
    if entry is None:
        return
    contract, runner = entry
    phase_run_dir = phase_run_dir_for(config, workspace_root, meta["phase"], phase_run_id)

    ctx = _build_runtime_context_for_resume(
        command=contract.command,
        phase_run_id=phase_run_id,
        workspace_root=workspace_root,
        inputs=meta.get("inputs") or {},
    )

    resolved_inputs: dict[str, Any] = {}
    for spec in contract.inputs:
        raw = (meta.get("inputs") or {}).get(spec.name)
        if raw is None:
            continue
        if spec.kind in ("path", "workspace_relative_path"):
            resolved_inputs[spec.name] = Path(raw)
        else:
            resolved_inputs[spec.name] = raw

    lock = lock_manager.get(meta["workspace_id"])
    async with lock:
        def _invoke() -> Any:
            with install_stderr_capture(phase_run_id, event_bus):
                return runner(config, ctx, phase_run_dir, resolved_inputs)

        try:
            result = await asyncio.to_thread(_invoke)
        except BaseException as exc:
            failed_meta = _persist_runner_exception(
                phase_name=meta["phase"],
                phase_run_id=phase_run_id,
                workspace_id=meta["workspace_id"],
                chain_id=meta.get("chain_id"),
                started_at=meta["started_at"],
                inputs_record=meta.get("inputs") or {},
                phase_run_dir=phase_run_dir,
                run_registry=run_registry,
                exc=exc,
            )
            event_bus.publish(phase_run_id, {"event": "failed", "data": _terminal_event_payload(failed_meta, phase_run_id)})
            event_bus.close(phase_run_id)
            run_registry.clear_future(phase_run_id)
            return

        terminal_meta = _build_terminal_meta(
            phase_name=meta["phase"],
            phase_run_id=phase_run_id,
            workspace_id=meta["workspace_id"],
            chain_id=meta.get("chain_id"),
            started_at=meta["started_at"],
            inputs_record=meta.get("inputs") or {},
            result=result,
        )
        _persist_terminal_result(phase_run_dir=phase_run_dir, run_registry=run_registry, meta=terminal_meta)
        event_bus.publish(
            phase_run_id,
            {"event": terminal_meta["status"], "data": _terminal_event_payload(terminal_meta, phase_run_id)},
        )
        event_bus.close(phase_run_id)
        run_registry.clear_future(phase_run_id)


@router.post("/{phase_run_id}/resolve", response_model=PhaseRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def post_resolve(
    phase_run_id: str,
    request: Request,
    run_registry: PhaseRunRegistry = Depends(get_phase_run_registry),
    workspace_store: WorkspaceStore = Depends(get_workspace_store),
    registry: PhaseRegistry = Depends(get_phase_registry_dep),
    event_bus: PhaseRunEventBus = Depends(get_event_bus),
    lock_manager: WorkspaceLockManager = Depends(get_workspace_lock_manager),
) -> PhaseRunResponse:
    meta = run_registry.get(phase_run_id)
    if meta is None:
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "phase_run_not_found",
            f"phase_run {phase_run_id!r} not found",
        )
    if meta["status"] != PhaseRunState.blocked.value:
        raise http_error(
            status.HTTP_409_CONFLICT,
            "run_not_blocked",
            f"phase_run {phase_run_id!r} is not in blocked state",
        )

    phase_run_dir = _phase_run_dir_from_meta(meta, workspace_store)
    if phase_run_dir is None:
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "phase_run_dir_not_found",
            f"workspace or config for phase_run {phase_run_id!r} could not be resolved",
        )
    data = load_resolution_file(phase_run_dir) or {}
    valid, validation_errors = validate_resolutions(data)
    unresolved = sum(
        1
        for it in (data.get("items") or [])
        if isinstance(it, dict)
        and not (
            it.get("chosen_option_id")
            or (isinstance(it.get("free_text"), str) and it["free_text"].strip())
            or (isinstance(it.get("manual_edit_text"), str) and it["manual_edit_text"].strip())
        )
    )
    if not valid or unresolved > 0:
        raise http_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "resolutions_invalid",
            "resolutions have unresolved items or invalid decisions",
            details={"unresolved_count": unresolved, "errors": validation_errors},
        )

    running_meta = dict(meta)
    running_meta["status"] = PhaseRunState.running.value
    running_meta["ended_at"] = None
    running_meta["blocked_at"] = None
    running_meta["error"] = None
    from api.routers.phases import _write_run_meta as _wm
    _wm(phase_run_dir / "run_meta.json", running_meta)
    run_registry.put(running_meta)

    if event_bus.has(phase_run_id):
        event_bus.close(phase_run_id)
    event_bus.create(phase_run_id)

    task = asyncio.create_task(_run_resume_phase(
        phase_run_id=phase_run_id,
        meta=running_meta,
        workspace_store=workspace_store,
        registry=registry,
        run_registry=run_registry,
        event_bus=event_bus,
        lock_manager=lock_manager,
    ))
    run_registry.set_future(phase_run_id, task)

    return _response_from_meta(running_meta, _events_url(phase_run_id))


class _ItemEditRequest(BaseModel):
    user_guide: str | None = None


@router.post("/{phase_run_id}/resolutions/items/{item_index}/edit")
def post_item_edit(
    phase_run_id: str,
    item_index: int,
    payload: _ItemEditRequest,
    run_registry: PhaseRunRegistry = Depends(get_phase_run_registry),
    workspace_store: WorkspaceStore = Depends(get_workspace_store),
) -> dict[str, Any]:
    meta = run_registry.get(phase_run_id)
    if meta is None:
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "phase_run_not_found",
            f"phase_run {phase_run_id!r} not found",
        )
    if meta["status"] != PhaseRunState.blocked.value:
        raise http_error(
            status.HTTP_409_CONFLICT,
            "run_not_blocked",
            f"phase_run {phase_run_id!r} is not in blocked state",
        )
    phase_run_dir = _phase_run_dir_from_meta(meta, workspace_store)
    if phase_run_dir is None:
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "phase_run_dir_not_found",
            f"workspace or config for phase_run {phase_run_id!r} could not be resolved",
        )
    workspace = workspace_store.get(meta["workspace_id"])
    workspace_root = Path(workspace.path)
    config = load_workspace_config(workspace_root)
    if config is None:
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "workspace_config_missing",
            f"no config file found under {workspace_root}",
        )

    data = load_resolution_file(phase_run_dir) or {}
    items = data.get("items") or []
    if item_index < 0 or item_index >= len(items):
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "item_index_out_of_range",
            f"item_index {item_index} out of range (0..{len(items) - 1})",
        )
    item = items[item_index]
    if not isinstance(item, dict):
        raise http_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "item_invalid",
            f"item at index {item_index} is not a dict",
        )

    ctx = _build_runtime_context_for_resume(
        command=meta["phase"].split(".", 1)[0],
        phase_run_id=phase_run_id,
        workspace_root=workspace_root,
        inputs=meta.get("inputs") or {},
    )
    from handlers.resolve import invoke_spec_editor
    editor_output = invoke_spec_editor(item, config, ctx, phase_run_dir, user_guide=payload.user_guide)
    if editor_output is None:
        raise http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "spec_editor_failed",
            "spec_editor agent failed",
        )

    return {
        "phase_run_id": phase_run_id,
        "item_index": item_index,
        "editor_output": editor_output,
    }


@router.post("/{phase_run_id}/cancel")
def post_cancel(
    phase_run_id: str,
    run_registry: PhaseRunRegistry = Depends(get_phase_run_registry),
    event_bus: PhaseRunEventBus = Depends(get_event_bus),
) -> dict[str, Any]:
    meta = run_registry.get(phase_run_id)
    if meta is None:
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "phase_run_not_found",
            f"phase_run {phase_run_id!r} not found",
        )
    if meta["status"] in _TERMINAL_STATES:
        raise http_error(
            status.HTTP_409_CONFLICT,
            "run_not_cancellable",
            f"phase_run {phase_run_id!r} is in terminal state ({meta['status']!r})",
        )
    run_registry.mark_cancelled(phase_run_id)
    event_bus.publish(phase_run_id, {"event": "cancelled", "data": {"phase_run_id": phase_run_id}})
    return {"phase_run_id": phase_run_id, "status": "cancelling"}


@router.get("/{phase_run_id}/raw-replicas")
def get_raw_replicas(
    phase_run_id: str,
    run_registry: PhaseRunRegistry = Depends(get_phase_run_registry),
    workspace_store: WorkspaceStore = Depends(get_workspace_store),
) -> list[dict[str, Any]]:
    meta = run_registry.get(phase_run_id)
    if meta is None:
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "phase_run_not_found",
            f"phase_run {phase_run_id!r} not found",
        )
    if meta["phase"] != "refine.quality-audit":
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "raw_replicas_not_applicable",
            f"raw replicas only exist for refine.quality-audit (phase={meta['phase']!r})",
        )
    phase_run_dir = _phase_run_dir_from_meta(meta, workspace_store)
    if phase_run_dir is None:
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(phase_run_dir.glob("auditor_output_*.json")):
        try:
            idx_str = path.stem.removeprefix("auditor_output_")
            replica_index = int(idx_str)
        except ValueError:
            continue
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append({"replica_index": replica_index, "body": body})
    return out


_HEARTBEAT_INTERVAL_SECONDS = 30.0


@router.get("/{phase_run_id}/events")
async def get_events(
    phase_run_id: str,
    request: Request,
    run_registry: PhaseRunRegistry = Depends(get_phase_run_registry),
    event_bus: PhaseRunEventBus = Depends(get_event_bus),
) -> EventSourceResponse:
    meta = run_registry.get(phase_run_id)
    if meta is None:
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "phase_run_not_found",
            f"phase_run {phase_run_id!r} not found",
        )

    async def event_stream():
        if meta["status"] in _TERMINAL_STATES:
            yield {"event": meta["status"], "data": json.dumps(_terminal_event_payload(meta, phase_run_id))}
            return

        queue = event_bus.subscribe(phase_run_id)
        if queue is None:
            current = run_registry.get(phase_run_id)
            if current is not None:
                yield {"event": current["status"], "data": json.dumps(_terminal_event_payload(current, phase_run_id))}
            return

        try:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_INTERVAL_SECONDS)
                except asyncio.TimeoutError:
                    yield {"event": "heartbeat", "data": "{}"}
                    continue
                name = event.get("event", "progress")
                if name == "_close":
                    return
                data = event.get("data", {})
                yield {"event": name, "data": json.dumps(data)}
                if name in ("completed", "failed", "cancelled"):
                    return
        finally:
            pass

    return EventSourceResponse(event_stream())
