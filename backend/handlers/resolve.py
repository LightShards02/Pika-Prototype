"""Interactive manual resolution handler for blocked runs."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from core.format_sads import load_sads_csv_or_xlsx, rows_to_csv
from core.lifecycle import (
    find_most_recent_blocked_run_id_across_commands,
    invoke_agent_with_schema_retry,
    resolve_agent_runs_dir_for_command,
    resolve_output_path,
    resolve_project_context_content,
)
from core.resolution import (
    RESOLUTION_SOURCE_AGENT,
    _is_manual_edit_item,
    clear_resolution_item,
    generate_resolution_template,
    load_resolution_file,
    update_resolution_item,
    validate_resolutions,
)
from handlers.refine.config import _get_refine_cfg

OPTION_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Spec columns shown in context block, in display order.
_SPEC_DISPLAY_COLS = ("requirement", "acceptance_criteria", "title", "module_tag", "module_role")


def _find_run_dir(project_root: Path, run_id: str, config: dict[str, Any]) -> Path | None:
    """Find run directory for run_id by searching implement, plan, map, resolve_plan."""
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


def _build_spec_lookup(run_dir: Path) -> dict[str, dict[str, Any]]:
    """Load spec rows from run_meta's input_design_spec_path. Returns {spec_id: row}."""
    run_meta_path = run_dir / "run_meta.json"
    if not run_meta_path.exists():
        return {}
    try:
        run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    csv_path_str = run_meta.get("input_design_spec_path", "")
    if not csv_path_str:
        return {}
    csv_p = Path(csv_path_str)
    if not csv_p.exists():
        return {}
    try:
        _headers, rows = load_sads_csv_or_xlsx(csv_p)
        return {r.get("spec_id", "").strip(): r for r in rows if r.get("spec_id", "").strip()}
    except Exception:
        return {}


def _render_item(
    item: dict[str, Any],
    index: int,
    total: int,
    spec_lookup: dict[str, dict[str, Any]],
    run_id: str,
    console: "Any",
    command: str = "",
) -> None:
    """Render a single resolution item to the terminal using rich."""
    from rich.text import Text
    from rich.padding import Padding

    title = item.get("title", "Untitled")
    question = item.get("question", "")
    blocking_reason = item.get("blocking_reason", "")
    options = item.get("options") or []
    hints = item.get("spec_amendment_hints") or []
    source = item.get("source", RESOLUTION_SOURCE_AGENT)
    spec_id = item.get("spec_id", "")
    vague_phrases = item.get("vague_phrases") or []
    untestable_reason = item.get("untestable_reason", "")
    field = item.get("field", "")

    console.print()

    # ── Progress header ──────────────────────────────────────────────────────
    counter = Text()
    counter.append(f" {index + 1}", style="bold cyan")
    counter.append(f"/{total}", style="dim")
    counter.append(f"  ·  {run_id} ", style="dim")
    console.rule(counter, style="bright_black")

    # ── Spec context ─────────────────────────────────────────────────────────
    if spec_id:
        console.print()
        spec_header = Text()
        spec_header.append("  SPEC  ", style="bold white on dark_blue")
        spec_header.append(f"  {spec_id}", style="bold yellow")
        if field:
            spec_header.append("   ·  field: ", style="dim")
            spec_header.append(field, style="bold magenta")
        console.print(spec_header)

        row = spec_lookup.get(spec_id)
        if row:
            for col in _SPEC_DISPLAY_COLS:
                val = (row.get(col) or "").strip()
                if not val:
                    continue
                # Label on its own line; value below with left+right margin so
                # every wrapped continuation line carries the same indent.
                console.print(f"    [dim]{col}[/dim]")
                console.print(Padding(val, pad=(0, 6, 0, 6)))
        console.print()

    # ── Issue ────────────────────────────────────────────────────────────────
    console.rule(Text(f"  {title}  ", style="bold white"), style="red", align="left")
    if question:
        console.print()
        console.print("  [yellow]Question[/yellow]")
        console.print(Padding(question, pad=(0, 4, 0, 4)))
    if blocking_reason:
        console.print("  [red]Blocking[/red]")
        console.print(Padding(blocking_reason, pad=(0, 4, 0, 4)))
    if vague_phrases:
        console.print(f"  [dim italic]Vague phrases:  {',  '.join(vague_phrases)}[/dim italic]")
    if untestable_reason:
        console.print("  [dim]Untestable[/dim]")
        console.print(Padding(untestable_reason, pad=(0, 4, 0, 4)))

    # ── Suggested improvement ─────────────────────────────────────────────────
    suggested_improvement = item.get("suggested_improvement", "")
    if suggested_improvement:
        console.print()
        console.print("  [green]Suggested improvement[/green]")
        console.print(Padding(suggested_improvement, pad=(0, 4, 0, 4)))

    # ── Options ──────────────────────────────────────────────────────────────
    if options:
        console.print()
        console.rule("  Options  ", style="bright_black", align="left")
        for i, opt in enumerate(options):
            if isinstance(opt, dict):
                letter = OPTION_LETTERS[i] if i < len(OPTION_LETTERS) else str(i + 1)
                label = opt.get("label", "")
                effect = opt.get("effect", "")
                console.print(f"    [bold green]{letter}[/bold green]  {label}")
                if effect:
                    # 7-space indent aligns effect text under the option label
                    console.print(Padding(effect, pad=(0, 4, 0, 7)), style="dim")
    else:
        console.print()
        console.print("  [dim](no selectable options)[/dim]")

    # ── Hints ────────────────────────────────────────────────────────────────
    if hints:
        console.print()
        console.print("  [dim]Hints[/dim]")
        for h in hints:
            sid = h.get("spec_id", "")
            suggestion = h.get("suggestion", "")
            confidence = h.get("confidence", 0)
            console.print(f"  [dim]  • [{sid}] ({confidence})[/dim]")
            if suggestion:
                console.print(Padding(suggestion, pad=(0, 4, 0, 6)), style="dim")

    # ── Input prompt ─────────────────────────────────────────────────────────
    console.print()
    prompt_parts: list[str] = []
    if options:
        last = OPTION_LETTERS[len(options) - 1] if len(options) <= 26 else "?"
        prompt_parts.append(f"[bold green]A-{last}[/bold green]")
    if source == RESOLUTION_SOURCE_AGENT:
        # Only show O (guided agent edit) for items without a let_agent_edit option
        option_ids = {
            str(o.get("option_id", ""))
            for o in (item.get("options") or [])
            if isinstance(o, dict)
        }
        if "let_agent_edit" not in option_ids:
            other_label = "[cyan]O (agent edit)[/cyan]" if command == "refine" else "[cyan]O[/cyan]"
            prompt_parts.append(other_label)
    if _is_manual_edit_item(item):
        prompt_parts.append("[cyan]M (manual edit)[/cyan]")
    prompt_parts.append("[dim]N next[/dim]")
    prompt_parts.append("[dim]Z back[/dim]")
    prompt_parts.append("[dim]Q quit[/dim]")
    console.print("  " + "  [dim]·[/dim]  ".join(prompt_parts) + "  [bold]>[/bold] ", end="")


def _parse_input(
    raw: str,
    item: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Parse user input into chosen_option_id or free_text.

    Returns (chosen_option_id, free_text). One will be set, the other None.
    Special sentinels: "Z", "QUIT", "DONE", "OTHER", "NEXT".
    """
    raw = raw.strip().upper()
    if not raw:
        return None, None
    if raw == "Z":
        return "Z", None
    if raw == "Q":
        return "QUIT", None
    if raw == "N":
        return "NEXT", None
    if raw in {"O", "OTHER"}:
        return "OTHER", None
    if raw in {"M", "MANUAL"} and _is_manual_edit_item(item):
        return "MANUAL_EDIT", None

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
    user_guide: str | None = None,
) -> dict[str, Any] | None:
    """Invoke spec_editor agent for a let_agent_edit resolution.

    Determines edit mode from item options:
    - field mode: item has accept_suggestion option (ambiguity/testability items)
    - structural mode: item has only let_agent_edit/skip (decomposition items)

    user_guide: optional free-text instruction from the user passed as extra context.

    Returns editor output dict or None on failure.
    """
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
    if user_guide:
        issue_description = f"{issue_description}\n\nUser editing guide: {user_guide}"

    spec_id = item.get("spec_id", "")
    field = item.get("field", "") if issue_kind == "field" else ""
    affected_spec_ids = spec_id if issue_kind == "structural" else ""

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
        sys.stderr.write(f"[PIKA] spec_editor failed: {exc}\n")
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

        if chosen_id == "skip":
            report_entries.append({"spec_id": spec_id, "action": "skip"})
            continue

        # Handle manual spec edits
        manual_edit_text = (item.get("manual_edit_text") or "").strip()
        if manual_edit_text:
            edit_spec_id = item.get("manual_edit_spec_id", spec_id) or spec_id
            edit_field = item.get("manual_edit_field", "requirement") or "requirement"
            if _apply_field_edit(rows, headers, edit_spec_id, edit_field, manual_edit_text):
                changes += 1
                report_entries.append({
                    "spec_id": edit_spec_id,
                    "field": edit_field,
                    "action": "manual_edit",
                })
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


def _apply_implement_resolutions(
    run_dir: Path,
    config: dict[str, Any],
    ctx: Any,
) -> tuple[int, str]:
    """Apply manual spec edits from implement resolutions to the design spec CSV.

    Returns (changes_applied, output_csv_path_or_empty).
    If no manual edits exist, returns (0, "").
    """
    project_root = Path(ctx.project_root)

    run_meta_path = run_dir / "run_meta.json"
    run_meta: dict[str, Any] = {}
    if run_meta_path.exists():
        run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))

    input_csv_path_str = run_meta.get("input_design_spec_path", "")
    if not input_csv_path_str:
        return 0, ""

    data = load_resolution_file(run_dir)
    if not data:
        return 0, ""

    # Collect manual edits
    items = data.get("items") or []
    edits: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        manual_text = (item.get("manual_edit_text") or "").strip()
        if manual_text:
            edits.append({
                "spec_id": item.get("manual_edit_spec_id", ""),
                "field": item.get("manual_edit_field", "requirement"),
                "text": manual_text,
            })

    if not edits:
        return 0, ""

    csv_p = Path(input_csv_path_str)
    if not csv_p.exists():
        raise ValueError(f"Input CSV not found: {csv_p}")

    headers, rows = load_sads_csv_or_xlsx(csv_p)

    changes = 0
    for edit in edits:
        if _apply_field_edit(rows, headers, edit["spec_id"], edit["field"], edit["text"]):
            changes += 1

    # Write updated CSV to output path
    output_path = resolve_output_path(config, project_root, "design_spec_path", command="implement")
    if output_path is None:
        output_path = run_dir / "EDITED-SPEC.csv"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rows_to_csv(headers, rows), encoding="utf-8")

    run_meta["output_design_spec_path"] = str(output_path)
    run_meta_path.write_text(json.dumps(run_meta, indent=2), encoding="utf-8")

    return changes, str(output_path)


def _show_editor_preview(
    editor_out: dict[str, Any],
    item: dict[str, Any],
    spec_lookup: dict[str, dict[str, Any]],
    console: "Any",
) -> bool:
    """Render a preview of proposed spec edits and prompt the user to accept or reject.

    Returns True if the user accepts (Y), False if they reject (N or empty).
    """
    from rich.padding import Padding
    from rich.text import Text

    edit_type = editor_out.get("edit_type", "")
    console.print()
    console.rule(Text(f"  Preview  [{edit_type}]  ", style="bold yellow"), style="yellow", align="left")

    if edit_type == "field":
        spec_id = editor_out.get("spec_id") or item.get("spec_id", "")
        field = editor_out.get("field") or item.get("field", "")
        new_text = editor_out.get("new_text", "")

        old_text = ""
        row = spec_lookup.get(spec_id)
        if row:
            for k, v in row.items():
                if k.strip().lower() == (field or "").strip().lower():
                    old_text = str(v).strip()
                    break

        console.print(f"  [dim]Spec:[/dim]  [yellow]{spec_id}[/yellow]")
        console.print(f"  [dim]Field:[/dim] [magenta]{field}[/magenta]")
        console.print()
        if old_text:
            console.print("  [dim]OLD[/dim]")
            console.print(Padding(old_text, pad=(0, 4, 0, 4)), style="dim")
        console.print("  [green]NEW[/green]")
        console.print(Padding(new_text or "(empty)", pad=(0, 4, 0, 4)))

    elif edit_type == "structural":
        edits = editor_out.get("edits") or []
        console.print(f"  [dim]{len(edits)} edit(s) proposed[/dim]")
        for e in edits:
            action = e.get("action", "?")
            spec_id = e.get("spec_id", "?")
            row_data = e.get("row_data") or {}
            color = {"add": "green", "update": "yellow", "delete": "red"}.get(action, "white")
            console.print()
            console.print(f"  [{color}]{action:<8}[/{color}]  [yellow]{spec_id}[/yellow]")
            if action in ("add", "update"):
                old_row = spec_lookup.get(spec_id) or {}
                for field_name, new_val in row_data.items():
                    if field_name == "spec_id":
                        continue
                    old_val = str(old_row.get(field_name, "")).strip()
                    new_str = str(new_val).strip() if new_val is not None else ""
                    console.print(f"    [dim]{field_name}[/dim]")
                    if old_val:
                        console.print(Padding(old_val, pad=(0, 4, 0, 6)), style="dim")
                    console.print(Padding(new_str or "(empty)", pad=(0, 4, 0, 6)), style="green")
    else:
        console.print(f"  [dim]edit_type: {edit_type!r}[/dim]")

    console.print()
    console.print(
        "  Accept this edit?  [bold green]Y[/bold green] / [bold red]N[/bold red]  [bold]>[/bold] ",
        end="",
    )
    answer = sys.stdin.readline().strip().upper()
    return answer == "Y"


def _apply_only(
    run_dir: Path,
    run_id: str,
    data: dict[str, Any],
    items: list[dict[str, Any]],
    config: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    """Non-interactive apply path: validate pre-filled resolutions.yaml and apply changes.

    Used by the desktop GUI which writes resolutions.yaml directly instead of
    using the interactive TUI loop.
    """
    valid, errors = validate_resolutions(data)
    if not valid:
        return {
            "command": "resolve",
            "status": "failed",
            "reason": "validation_failed",
            "errors": errors,
        }

    run_meta_path = run_dir / "run_meta.json"
    run_meta: dict[str, Any] = {}
    if run_meta_path.exists():
        run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
    run_meta["resolution_status"] = "resolved"
    run_meta_path.write_text(json.dumps(run_meta, indent=2), encoding="utf-8")

    cmd = run_meta.get("command", "")
    if cmd == "refine":
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

    if cmd == "implement":
        try:
            changes, output_csv = _apply_implement_resolutions(run_dir, config, ctx)
            result: dict[str, Any] = {
                "command": "resolve",
                "status": "completed",
                "run_id": run_id,
                "items_resolved": len(items),
                "changes_applied": changes,
            }
            if output_csv:
                result["output_path"] = output_csv
            return result
        except Exception as exc:
            return {
                "command": "resolve",
                "status": "failed",
                "reason": f"apply_implement_resolutions: {exc}",
            }

    return {
        "command": "resolve",
        "status": "completed",
        "run_id": run_id,
        "items_resolved": len(items),
    }


def run_resolve(config: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """Run interactive resolution loop for a blocked run.

    Presents items one by one. Does not exit until all items have valid answers.
    """
    from rich.console import Console
    console = Console(highlight=False)
    err_console = Console(stderr=True, highlight=False)

    project_root = Path(ctx.project_root)
    run_id = (ctx.input_overrides.get("run_id") or "").strip()
    if not run_id:
        auto_run_id = find_most_recent_blocked_run_id_across_commands(
            config,
            project_root,
            ["implement", "plan", "map", "resolve_plan", "refine"],
        )
        if auto_run_id:
            err_console.print(f"[PIKA] Auto-resolving most recent blocked run: [cyan]{auto_run_id}[/cyan]")
            run_id = auto_run_id
        else:
            return {
                "command": "resolve",
                "status": "failed",
                "reason": "No blocked run found. Pass --run <run_id> to specify one explicitly.",
            }

    run_dir = _find_run_dir(project_root, run_id, config)
    if not run_dir:
        return {
            "command": "resolve",
            "status": "failed",
            "reason": f"No blocked run found for run_id={run_id}",
        }

    # Read command from run_meta so the loop can apply command-specific behaviour.
    run_command = ""
    _run_meta_path = run_dir / "run_meta.json"
    if _run_meta_path.exists():
        try:
            run_command = json.loads(_run_meta_path.read_text(encoding="utf-8")).get("command", "")
        except Exception:
            pass

    resolutions_path = run_dir / "manual_resolution" / "resolutions.yaml"
    if not resolutions_path.exists():
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

    # Non-interactive apply-only mode (for desktop GUI).
    # Validates a pre-filled resolutions.yaml and applies changes without TUI.
    if ctx.input_overrides.get("apply_only") == "true":
        return _apply_only(run_dir, run_id, data, items, config, ctx)

    spec_lookup = _build_spec_lookup(run_dir)

    # Session header
    console.print()
    console.rule(
        f"[bold cyan] PIKA RESOLVE [/bold cyan]  [dim]{run_id}[/dim]  [dim]{len(items)} item(s)[/dim]",
        style="cyan",
    )
    console.print()

    resolved: list[int] = []
    current = 0

    while current < len(items):
        item = items[current]
        if not isinstance(item, dict):
            current += 1
            continue

        chosen = item.get("chosen_option_id")
        free_text = (item.get("free_text") or "").strip()
        manual_edit = (item.get("manual_edit_text") or "").strip()
        is_resolved = current in resolved or bool(chosen or free_text or manual_edit)
        if is_resolved:
            current += 1
            continue

        _render_item(item, current, len(items), spec_lookup, run_id, console, run_command)
        raw = sys.stdin.readline().strip()

        chosen_id, _ = _parse_input(raw, item)
        if chosen_id == "QUIT":
            return {
                "command": "resolve",
                "status": "quit",
                "run_id": run_id,
                "reason": "user quit interactive session",
            }
        if chosen_id == "NEXT":
            # Skip without recording a resolution — item stays pending.
            current += 1
            continue
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
        if chosen_id == "MANUAL_EDIT":
            spec_id = item.get("spec_id", "")
            field = item.get("field", "")
            if not spec_id:
                refs = item.get("evidence_refs") or []
                spec_id = refs[0] if refs else ""
            if not spec_id:
                console.print("  [red]No spec_id found for this item.[/red]")
                continue

            row = spec_lookup.get(spec_id, {})
            target_field = field or "requirement"
            current_text = str(row.get(target_field, "")).strip()
            console.print(f"\n  [dim]Current {target_field} for {spec_id}:[/dim]")
            from rich.padding import Padding as _Pad
            console.print(_Pad(current_text or "(empty)", pad=(0, 4, 0, 4)), style="dim")
            console.print(f"\n  [cyan]Enter replacement text (empty line to cancel):[/cyan]")
            console.print("  [bold]>[/bold] ", end="")
            new_text = sys.stdin.readline().strip()
            if not new_text:
                console.print("  [dim]Cancelled.[/dim]")
                continue
            update_resolution_item(
                resolutions_path, current, None, None,
                manual_edit_text=new_text,
                manual_edit_spec_id=spec_id,
                manual_edit_field=target_field,
            )
            resolved.append(current)
            current += 1
            data = load_resolution_file(run_dir)
            if data:
                items = data.get("items") or []
            continue
        if chosen_id == "OTHER":
            if item.get("source") != RESOLUTION_SOURCE_AGENT:
                console.print("  [red]'other' only available for agent-originated items.[/red]")
                continue
            other_option_ids = {
                str(o.get("option_id", ""))
                for o in (item.get("options") or [])
                if isinstance(o, dict)
            }
            if "let_agent_edit" in other_option_ids:
                console.print("  [red]Use the let_agent_edit option instead.[/red]")
                continue
            if run_command == "refine":
                # For refine: treat OTHER as a guided agent edit.
                console.print("  [cyan]Enter editing guide for the agent[/cyan] [bold]>[/bold] ", end="")
                user_guide = sys.stdin.readline().strip()
                if not user_guide:
                    console.print("  [red]Guide cannot be empty.[/red]")
                    continue
                console.print("  [dim]Invoking spec_editor agent with your guide…[/dim]")
                editor_out = _invoke_spec_editor(item, config, ctx, run_dir, user_guide=user_guide)
                if editor_out is None:
                    console.print("  [red]spec_editor agent failed. Please try again.[/red]")
                    continue
                if not _show_editor_preview(editor_out, item, spec_lookup, console):
                    console.print("  [dim]Edit rejected — returning to item.[/dim]")
                    continue
                _store_editor_output(resolutions_path, current, editor_out)
                resolved.append(current)
                current += 1
                data = load_resolution_file(run_dir)
                if data:
                    items = data.get("items") or []
            else:
                # For non-refine commands: free text.
                console.print("  [cyan]Enter free text[/cyan] [bold]>[/bold] ", end="")
                free_text = sys.stdin.readline().strip()
                if not free_text:
                    console.print("  [red]Free text cannot be empty.[/red]")
                    continue
                update_resolution_item(resolutions_path, current, None, free_text)
                resolved.append(current)
                current += 1
                data = load_resolution_file(run_dir)
                if data:
                    items = data.get("items") or []
            continue
        if chosen_id == "let_agent_edit":
            console.print("  [cyan]Provide instructions for the agent (or Enter to skip):[/cyan]")
            console.print("  [bold]>[/bold] ", end="")
            user_guide = sys.stdin.readline().strip() or None
            console.print("  [dim]Invoking spec_editor agent…[/dim]")
            editor_out = _invoke_spec_editor(item, config, ctx, run_dir, user_guide=user_guide)
            if editor_out is None:
                console.print("  [red]spec_editor agent failed. Please try again.[/red]")
                continue
            if not _show_editor_preview(editor_out, item, spec_lookup, console):
                console.print("  [dim]Edit rejected — returning to item.[/dim]")
                continue
            _store_editor_output(resolutions_path, current, editor_out)
            resolved.append(current)
            current += 1
            data = load_resolution_file(run_dir)
            if data:
                items = data.get("items") or []
            continue

        if chosen_id == "manual_edit":
            # manual_edit selected via option letter — same flow as M
            spec_id = item.get("spec_id", "")
            field = item.get("field", "")
            if not spec_id:
                refs = item.get("evidence_refs") or []
                spec_id = refs[0] if refs else ""
            if not spec_id:
                console.print("  [red]No spec_id found for this item.[/red]")
                continue
            row = spec_lookup.get(spec_id, {})
            target_field = field or "requirement"
            current_text = str(row.get(target_field, "")).strip()
            from rich.padding import Padding as _Pad2
            console.print(f"\n  [dim]Current {target_field} for {spec_id}:[/dim]")
            console.print(_Pad2(current_text or "(empty)", pad=(0, 4, 0, 4)), style="dim")
            console.print(f"\n  [cyan]Enter replacement text (empty line to cancel):[/cyan]")
            console.print("  [bold]>[/bold] ", end="")
            new_text = sys.stdin.readline().strip()
            if not new_text:
                console.print("  [dim]Cancelled.[/dim]")
                continue
            update_resolution_item(
                resolutions_path, current, None, None,
                manual_edit_text=new_text,
                manual_edit_spec_id=spec_id,
                manual_edit_field=target_field,
            )
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

        console.print("  [red]Invalid input. Please try again.[/red]")

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

    cmd = run_meta_final.get("command", "")
    if cmd == "refine":
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

    if cmd == "implement":
        try:
            changes, output_csv = _apply_implement_resolutions(run_dir, config, ctx)
            result: dict[str, Any] = {
                "command": "resolve",
                "status": "completed",
                "run_id": run_id,
                "items_resolved": len(items),
                "changes_applied": changes,
            }
            if output_csv:
                result["output_path"] = output_csv
            return result
        except Exception as exc:
            return {
                "command": "resolve",
                "status": "failed",
                "reason": f"apply_implement_resolutions: {exc}",
            }

    return {
        "command": "resolve",
        "status": "completed",
        "run_id": run_id,
        "items_resolved": len(items),
    }
