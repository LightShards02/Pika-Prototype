"""Interactive manual resolution handler for blocked runs."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from core.resolution import (
    RESOLUTION_SOURCE_AGENT,
    clear_resolution_item,
    load_resolution_file,
    update_resolution_item,
    validate_resolutions,
)

OPTION_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _is_edit_spec_item(item: dict[str, Any]) -> bool:
    """Return True when the item is resolved by spec edit acknowledgement."""
    resolution_mode = str(item.get("resolution_mode", "")).strip().lower()
    if resolution_mode == "edit_spec":
        return True
    if item.get("source") == RESOLUTION_SOURCE_AGENT:
        return False
    options = [o for o in (item.get("options") or []) if isinstance(o, dict)]
    return len(options) == 0


def _find_run_dir(project_root: Path, run_id: str, config: dict[str, Any]) -> Path | None:
    """Find run directory for run_id by searching implement, plan, map, resolve_plan."""
    from core.lifecycle import resolve_agent_runs_dir_for_command

    for cmd in ("implement", "plan", "map", "resolve_plan"):
        run_dir = resolve_agent_runs_dir_for_command(config, project_root, cmd, run_id)
        if not run_dir.exists():
            continue
        manual = run_dir / "manual_resolution"
        if not manual.exists():
            continue
        if (manual / "resolutions.yaml").exists():
            return run_dir
        for stage_file in manual.glob("*.json"):
            return run_dir
    return None


def _format_item_display(
    item: dict[str, Any],
    index: int,
    total: int,
) -> str:
    """Format a single resolution item for terminal display."""
    lines: list[str] = []
    title = item.get("title", "Untitled")
    question = item.get("question", "")
    blocking_reason = item.get("blocking_reason", "")
    options = item.get("options") or []
    hints = item.get("spec_amendment_hints") or []
    source = item.get("source", RESOLUTION_SOURCE_AGENT)

    lines.append("")
    lines.append("=" * 60)
    lines.append(f"  Item {index + 1}/{total}: {title}")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"  Question: {question}")
    lines.append("")
    if blocking_reason:
        lines.append(f"  Blocking reason: {blocking_reason}")
        lines.append("")

    if hints:
        lines.append("  Spec amendment hints:")
        for h in hints:
            spec_id = h.get("spec_id", "")
            suggestion = h.get("suggestion", "")
            confidence = h.get("confidence", 0)
            lines.append(f"    - [{spec_id}] (confidence: {confidence}) {suggestion}")
        lines.append("")

    lines.append("  Options:")
    if options:
        for i, opt in enumerate(options):
            if isinstance(opt, dict):
                letter = OPTION_LETTERS[i] if i < len(OPTION_LETTERS) else str(i + 1)
                label = opt.get("label", "")
                effect = opt.get("effect", "")
                lines.append(f"    {letter}. {label}")
                if effect:
                    lines.append(f"       Effect: {effect}")
    else:
        lines.append("    (no selectable options)")
    lines.append("")

    prompt_parts: list[str] = []
    if options:
        prompt_parts.append(
            f"Type A-{OPTION_LETTERS[len(options)-1]}"
            if len(options) <= 26
            else "Type option letter"
        )
    if source == RESOLUTION_SOURCE_AGENT:
        prompt_parts.append("OTHER (free text)")
    if _is_edit_spec_item(item):
        prompt_parts.append("DONE (spec edited)")
    prompt_parts.append("Z (go back)")
    prompt_parts.append("Q (quit)")
    lines.append("  " + " | ".join(prompt_parts) + ": ")
    return "\n".join(lines)


def _parse_input(
    raw: str,
    item: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Parse user input into chosen_option_id or free_text.

    Returns (chosen_option_id, free_text). One will be set, the other None.
    """
    raw = raw.strip().upper()
    if not raw:
        return None, None
    if raw == "Z":
        return "Z", None
    if raw == "Q":
        return "QUIT", None
    if raw == "OTHER":
        return "OTHER", None
    if raw in {"DONE", "D"} and _is_edit_spec_item(item):
        return "DONE", None

    options = item.get("options") or []
    for i, opt in enumerate(options):
        if isinstance(opt, dict):
            letter = OPTION_LETTERS[i] if i < len(OPTION_LETTERS) else str(i + 1)
            if raw == letter:
                return str(opt.get("option_id", "")), None
    return None, None


def run_resolve(config: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """Run interactive resolution loop for a blocked run.

    Presents items one by one. Does not exit until all items have valid answers.
    """
    project_root = Path(ctx.project_root)
    run_id = (ctx.input_overrides.get("run_id") or getattr(ctx, "run_id", None) or "").strip()
    if not run_id:
        return {
            "command": "resolve",
            "status": "failed",
            "reason": "run_id required (pass via --run or input_overrides)",
        }

    run_dir = _find_run_dir(project_root, run_id, config)
    if not run_dir:
        return {
            "command": "resolve",
            "status": "failed",
            "reason": f"No blocked run found for run_id={run_id}",
        }

    resolutions_path = run_dir / "manual_resolution" / "resolutions.yaml"
    if not resolutions_path.exists():
        import json

        from core.resolution import generate_resolution_template

        run_meta_path = run_dir / "run_meta.json"
        run_meta: dict[str, Any] = {}
        if run_meta_path.exists():
            try:
                run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        stage = run_meta.get("blocked_at_stage", "unknown")
        command = run_meta.get("command", "implement")
        stage_file = run_dir / "manual_resolution" / f"{stage}.json"
        if not stage_file.exists():
            stage_files = list((run_dir / "manual_resolution").glob("*.json"))
            stage_file = stage_files[0] if stage_files else None
        if stage_file and stage_file.exists():
            data = json.loads(stage_file.read_text(encoding="utf-8"))
            items = data.get("items", [])
            if items:
                source = "validation" if "contract_field" in stage else "agent"
                generate_resolution_template(
                    run_dir=run_dir,
                    stage=stage,
                    items=items,
                    command=command,
                    run_id=run_id,
                    source=source,
                )

    data = load_resolution_file(run_dir)
    if not data:
        return {
            "command": "resolve",
            "status": "failed",
            "reason": f"Could not load {resolutions_path}",
        }

    items = data.get("items") or []
    if not items:
        return {
            "command": "resolve",
            "status": "completed",
            "reason": "no_items",
        }

    resolved: list[int] = []
    current = 0

    while current < len(items):
        item = items[current]
        if not isinstance(item, dict):
            current += 1
            continue

        chosen = item.get("chosen_option_id")
        free_text = (item.get("free_text") or "").strip()
        acknowledged = bool(item.get("acknowledged"))
        is_resolved = current in resolved or bool(chosen or free_text or acknowledged)
        if is_resolved:
            current += 1
            continue

        sys.stdout.write(_format_item_display(item, current, len(items)))
        sys.stdout.flush()
        raw = sys.stdin.readline().strip()

        chosen_id, _ = _parse_input(raw, item)
        if chosen_id == "QUIT":
            return {
                "command": "resolve",
                "status": "quit",
                "run_id": run_id,
                "reason": "user quit interactive session",
            }
        if chosen_id == "Z":
            if current > 0:
                current -= 1
                if current in resolved:
                    resolved.remove(current)
                clear_resolution_item(resolutions_path, current)
                data = load_resolution_file(run_dir)
                if data:
                    items = data.get("items") or []
            continue
        if chosen_id == "DONE":
            update_resolution_item(resolutions_path, current, None, None, acknowledged=True)
            resolved.append(current)
            current += 1
            data = load_resolution_file(run_dir)
            if data:
                items = data.get("items") or []
            continue
        if chosen_id == "OTHER":
            if item.get("source") != RESOLUTION_SOURCE_AGENT:
                sys.stderr.write("  'other' only available for agent-originated items.\n")
                continue
            sys.stdout.write("  Enter free text: ")
            sys.stdout.flush()
            free_text = sys.stdin.readline().strip()
            if not free_text:
                sys.stderr.write("  Free text cannot be empty.\n")
                continue
            update_resolution_item(resolutions_path, current, None, free_text)
            resolved.append(current)
            current += 1
            data = load_resolution_file(run_dir)
            if data:
                items = data.get("items") or []
            continue
        if chosen_id:
            update_resolution_item(resolutions_path, current, chosen_id, None)
            resolved.append(current)
            current += 1
            data = load_resolution_file(run_dir)
            if data:
                items = data.get("items") or []
            continue

        sys.stderr.write("  Invalid input. Please try again.\n")

    data = load_resolution_file(run_dir)
    if not data:
        return {"command": "resolve", "status": "failed", "reason": "load_failed_after_loop"}

    valid, errors = validate_resolutions(data)
    if not valid:
        return {
            "command": "resolve",
            "status": "failed",
            "reason": "validation_failed",
            "errors": errors,
        }

    run_meta_path = run_dir / "run_meta.json"
    if run_meta_path.exists():
        import json
        run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
        run_meta["resolution_status"] = "resolved"
        run_meta_path.write_text(json.dumps(run_meta, indent=2), encoding="utf-8")

    return {
        "command": "resolve",
        "status": "completed",
        "run_id": run_id,
        "items_resolved": len(items),
    }
