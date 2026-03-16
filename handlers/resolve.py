"""Interactive manual resolution handler for blocked runs."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from core.format_sads import load_sads_csv_or_xlsx, rows_to_csv
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

    for cmd in ("implement", "plan", "map", "resolve_plan", "refine"):
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


def _store_editor_output(
    resolutions_path: Path,
    item_index: int,
    editor_output: dict[str, Any],
) -> None:
    """Persist editor_output dict and set chosen_option_id='let_agent_edit' in resolutions.yaml."""
    import yaml

    with open(resolutions_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    items = data.get("items") or []
    if 0 <= item_index < len(items):
        item = items[item_index]
        if isinstance(item, dict):
            item["chosen_option_id"] = "let_agent_edit"
            item["free_text"] = None
            item["editor_output"] = editor_output
    with open(resolutions_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _invoke_spec_editor(
    item: dict[str, Any],
    config: dict[str, Any],
    ctx: Any,
    run_dir: Path,
) -> dict[str, Any] | None:
    """Invoke spec_editor agent for a let_agent_edit resolution.

    Determines edit mode from item options:
    - field mode: item has accept_suggestion option (ambiguity/testability items)
    - structural mode: item has only let_agent_edit/skip (decomposition items)

    Returns editor output dict or None on failure.
    """
    from core.lifecycle import invoke_agent_with_schema_retry, resolve_project_context_content

    project_root = Path(ctx.project_root)

    # Determine edit mode
    options = item.get("options") or []
    option_ids = {o.get("option_id") for o in options if isinstance(o, dict)}
    issue_kind = "field" if "accept_suggestion" in option_ids else "structural"

    schema_path = project_root / "schemas" / "agent_outputs" / "spec_editor_output.schema.json"

    try:
        context_text = resolve_project_context_content(config, project_root, ctx, project_root)
    except Exception:
        context_text = ""

    # Load input SADS CSV from run_meta
    run_meta_path = run_dir / "run_meta.json"
    input_csv_path_str = ""
    if run_meta_path.exists():
        try:
            run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
            input_csv_path_str = run_meta.get("input_design_spec_path", "")
        except Exception:
            pass

    full_spec_csv = ""
    current_text = ""
    if input_csv_path_str:
        csv_p = Path(input_csv_path_str)
        if csv_p.exists():
            try:
                h, r = load_sads_csv_or_xlsx(csv_p)
                full_spec_csv = rows_to_csv(h, r)
                if issue_kind == "field":
                    spec_id = item.get("spec_id", "")
                    field = item.get("field", "")
                    for row in r:
                        if row.get("spec_id", "").strip() == spec_id.strip():
                            for k, v in row.items():
                                if k.strip().lower() == field.strip().lower():
                                    current_text = str(v)
                                    break
                            break
            except Exception:
                pass

    # Build issue_description
    issue_parts: list[str] = []
    if item.get("untestable_reason"):
        issue_parts.append(str(item["untestable_reason"]))
    vague = item.get("vague_phrases")
    if isinstance(vague, list) and vague:
        issue_parts.append("Vague phrases: " + ", ".join(str(v) for v in vague))
    if not issue_parts and item.get("question"):
        issue_parts.append(str(item["question"]))
    if not issue_parts:
        issue_parts.append(item.get("title", ""))
    issue_description = " | ".join(issue_parts)

    spec_id = item.get("spec_id", "")
    field = item.get("field", "") if issue_kind == "field" else ""
    affected_spec_ids = spec_id if issue_kind == "structural" else ""

    from handlers.refine.config import _get_refine_cfg
    try:
        cfg = _get_refine_cfg(config)
        prompt_name = cfg["spec_editor_prompt_name"]
    except Exception:
        prompt_name = "spec_editor"

    template_vars: dict[str, Any] = {
        "output_schema_file": str(schema_path),
        "project_context": context_text,
        "issue_kind": issue_kind,
        "spec_id": spec_id,
        "field": field,
        "affected_spec_ids": affected_spec_ids,
        "current_text": current_text,
        "issue_description": issue_description,
        "suggested_improvement": item.get("suggested_improvement", ""),
        "full_spec_csv": full_spec_csv,
    }

    try:
        return invoke_agent_with_schema_retry(
            prompt_name=prompt_name,
            template_vars=template_vars,
            schema_path=schema_path if schema_path.exists() else None,
            config=config,
            ctx=ctx,
        )
    except Exception as exc:
        sys.stderr.write(f"  spec_editor failed: {exc}\n")
        return None


def _apply_field_edit(
    rows: list[dict[str, Any]],
    headers: list[str],
    spec_id: str,
    field_name: str,
    new_text: str,
) -> bool:
    """Apply a field-level edit to a matching row. Returns True if a row was updated."""
    for row in rows:
        if row.get("spec_id", "").strip() == spec_id.strip():
            for h in headers:
                if h.strip().lower() == field_name.strip().lower():
                    row[h] = new_text
                    return True
    return False


def _apply_structural_edits(
    rows: list[dict[str, Any]],
    headers: list[str],
    edits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply add/update/delete operations to a row list. Returns updated list."""
    result = list(rows)
    for edit in edits:
        action = edit.get("action", "")
        spec_id = edit.get("spec_id", "")
        row_data = edit.get("row_data") or {}

        if action == "delete":
            result = [r for r in result if r.get("spec_id", "").strip() != spec_id.strip()]
        elif action == "update":
            for row in result:
                if row.get("spec_id", "").strip() == spec_id.strip():
                    row.update(row_data)
                    row["spec_id"] = spec_id
                    break
        elif action == "add":
            new_row: dict[str, Any] = {h: "" for h in headers}
            new_row.update(row_data)
            new_row["spec_id"] = spec_id
            insert_idx = len(result)
            for i, r in enumerate(result):
                if r.get("spec_id", "").strip() == spec_id.strip():
                    insert_idx = i + 1
                    break
            result.insert(insert_idx, new_row)
    return result


def _apply_refine_resolutions(
    run_dir: Path,
    config: dict[str, Any],
    ctx: Any,
) -> tuple[int, str]:
    """Apply all resolutions to the input SADS CSV and write the refined output.

    Returns (changes_applied, output_csv_path).
    """
    from core.lifecycle import resolve_output_path

    project_root = Path(ctx.project_root)

    # Load run_meta
    run_meta_path = run_dir / "run_meta.json"
    run_meta: dict[str, Any] = {}
    if run_meta_path.exists():
        run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))

    input_csv_path_str = run_meta.get("input_design_spec_path", "")
    if not input_csv_path_str:
        raise ValueError("input_design_spec_path not found in run_meta.json")

    csv_p = Path(input_csv_path_str)
    if not csv_p.exists():
        raise ValueError(f"Input CSV not found: {csv_p}")

    headers, rows = load_sads_csv_or_xlsx(csv_p)

    # Load resolutions
    data = load_resolution_file(run_dir)
    if not data:
        raise ValueError("Could not load resolutions.yaml")

    items = data.get("items") or []
    changes = 0
    report_entries: list[dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        chosen_id = item.get("chosen_option_id", "")
        editor_output = item.get("editor_output")
        spec_id = item.get("spec_id", "")
        field = item.get("field", "")

        if chosen_id == "skip" or item.get("acknowledged"):
            report_entries.append({"spec_id": spec_id, "action": "skip"})
            continue

        if chosen_id == "accept_suggestion":
            new_text = item.get("suggested_improvement", "")
            if _apply_field_edit(rows, headers, spec_id, field, new_text):
                changes += 1
                report_entries.append({"spec_id": spec_id, "field": field, "action": "accept_suggestion"})

        elif chosen_id == "let_agent_edit" and isinstance(editor_output, dict):
            edit_type = editor_output.get("edit_type", "")
            if edit_type == "field":
                new_text = editor_output.get("new_text", "")
                target_field = editor_output.get("field", field)
                if _apply_field_edit(rows, headers, spec_id, target_field, new_text):
                    changes += 1
                    report_entries.append({"spec_id": spec_id, "field": target_field, "action": "let_agent_edit_field"})
            elif edit_type == "structural":
                edits = editor_output.get("edits") or []
                rows = _apply_structural_edits(rows, headers, edits)
                changes += len(edits)
                report_entries.append({"spec_id": spec_id, "action": "let_agent_edit_structural", "edits": len(edits)})

    # Resolve output path
    output_path = resolve_output_path(config, project_root, "design_spec_path", command="refine")
    if output_path is None:
        output_path = project_root / "out" / "state" / "REFINED-SPEC.csv"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rows_to_csv(headers, rows), encoding="utf-8")

    # Write refinement report
    refinement_report = {
        "run_id": run_meta.get("run_id", ""),
        "changes_applied": changes,
        "report": report_entries,
        "output_csv_path": str(output_path),
    }
    (run_dir / "refinement_report.json").write_text(
        json.dumps(refinement_report, indent=2), encoding="utf-8"
    )

    run_meta["output_design_spec_path"] = str(output_path)
    run_meta_path.write_text(json.dumps(run_meta, indent=2), encoding="utf-8")

    return changes, str(output_path)


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
        if chosen_id == "let_agent_edit":
            sys.stdout.write("  Invoking spec_editor agent...\n")
            sys.stdout.flush()
            editor_out = _invoke_spec_editor(item, config, ctx, run_dir)
            if editor_out is None:
                sys.stderr.write("  spec_editor agent failed. Please try again.\n")
                continue
            edit_type = editor_out.get("edit_type", "")
            if edit_type == "field":
                sys.stdout.write(
                    f"  Editor result [field]: field={editor_out.get('field', '')}\n"
                    f"    {editor_out.get('new_text', '')[:200]}\n"
                )
            elif edit_type == "structural":
                edits = editor_out.get("edits", [])
                sys.stdout.write(f"  Editor result [structural]: {len(edits)} edit(s)\n")
                for e in edits:
                    sys.stdout.write(f"    {e.get('action', '?')} spec_id={e.get('spec_id', '?')}\n")
            sys.stdout.flush()
            _store_editor_output(resolutions_path, current, editor_out)
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
    run_meta_final: dict[str, Any] = {}
    if run_meta_path.exists():
        run_meta_final = json.loads(run_meta_path.read_text(encoding="utf-8"))
        run_meta_final["resolution_status"] = "resolved"
        run_meta_path.write_text(json.dumps(run_meta_final, indent=2), encoding="utf-8")

    if run_meta_final.get("command") == "refine":
        try:
            changes, output_csv = _apply_refine_resolutions(run_dir, config, ctx)
            return {
                "command": "resolve",
                "status": "completed",
                "run_id": run_id,
                "items_resolved": len(items),
                "changes_applied": changes,
                "output_path": output_csv,
            }
        except Exception as exc:
            return {
                "command": "resolve",
                "status": "failed",
                "reason": f"apply_refine_resolutions: {exc}",
            }

    return {
        "command": "resolve",
        "status": "completed",
        "run_id": run_id,
        "items_resolved": len(items),
    }
