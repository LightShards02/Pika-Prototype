"""Manual resolution template generation, loading, validation, and context building.

When an agent or validation step emits manual_resolution_items, PIKA generates
a resolutions.yaml template. Users resolve items interactively; resolved
decisions are then injected into agent prompts on resume.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

RESOLUTIONS_FILENAME = "resolutions.yaml"
RESOLUTION_SOURCE_AGENT = "agent"
RESOLUTION_SOURCE_VALIDATION = "validation"
VALIDATION_CONFIDENCE = 1.0
AGENT_HINT_CONFIDENCE_DEFAULT = 0.6


def _is_edit_spec_item(item: dict[str, Any]) -> bool:
    """Return True when an item is a no-option spec-edit acknowledgement flow."""
    resolution_mode = str(item.get("resolution_mode", "")).strip().lower()
    if resolution_mode == "edit_spec":
        return True
    if item.get("source") != RESOLUTION_SOURCE_VALIDATION:
        return False
    options = [o for o in (item.get("options") or []) if isinstance(o, dict)]
    return len(options) == 0


def generate_resolution_template(
    run_dir: Path,
    stage: str,
    items: list[dict[str, Any]],
    command: str,
    run_id: str,
    source: str,
    *,
    spec_rows: list[dict[str, Any]] | None = None,
    headers: list[str] | None = None,
    shared_contracts: list[dict[str, Any]] | None = None,
) -> Path:
    """Generate a resolutions.yaml template in the run's manual_resolution directory.

    Args:
        run_dir: The run directory (e.g. agent_runs/implement/{run_id}).
        stage: Blocking stage name (e.g. unified_planner, contract_field_consistency).
        items: List of manual_resolution_item dicts.
        command: PIKA command (implement, plan, map, resolve_plan).
        run_id: Run identifier.
        source: "agent" or "validation" — controls free_text availability per item.
        spec_rows: Optional spec rows for hint generation.
        headers: Optional CSV headers for spec rows.
        shared_contracts: Optional shared contracts for validation-item hints.

    Returns:
        Path to the written resolutions.yaml file.
    """
    manual_dir = run_dir / "manual_resolution"
    manual_dir.mkdir(parents=True, exist_ok=True)
    out_path = manual_dir / RESOLUTIONS_FILENAME

    template_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        enriched = _enrich_item_with_hints(
            item,
            source=source,
            spec_rows=spec_rows or [],
            headers=headers or [],
            shared_contracts=shared_contracts or [],
        )
        enriched["source"] = source
        enriched["chosen_option_id"] = None
        if source == RESOLUTION_SOURCE_VALIDATION and _is_edit_spec_item(enriched):
            enriched["acknowledged"] = False
        if source == RESOLUTION_SOURCE_AGENT:
            enriched["free_text"] = None
        template_items.append(enriched)

    payload: dict[str, Any] = {
        "run_id": run_id,
        "command": command,
        "blocked_at_stage": stage,
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "items": template_items,
    }

    import yaml

    with open(out_path, "w", encoding="utf-8") as f:
        yaml.dump(payload, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return out_path


def _enrich_item_with_hints(
    item: dict[str, Any],
    *,
    source: str,
    spec_rows: list[dict[str, Any]],
    headers: list[str],
    shared_contracts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Add spec_amendment_hints to an item. Returns a copy with hints."""
    result = dict(item)
    hints = _build_spec_amendment_hints(
        item,
        source=source,
        spec_rows=spec_rows,
        headers=headers,
        shared_contracts=shared_contracts,
    )
    if hints:
        result["spec_amendment_hints"] = hints
    else:
        result["spec_amendment_hints"] = []
    return result


def _build_spec_amendment_hints(
    item: dict[str, Any],
    *,
    source: str,
    spec_rows: list[dict[str, Any]],
    headers: list[str],
    shared_contracts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build spec amendment hints for an item.

    Validation-originated hints: confidence fixed at 1.
    Agent-originated hints: confidence between 0 and 1.
    """
    hints: list[dict[str, Any]] = []
    item_id = str(item.get("item_id", ""))

    if source == RESOLUTION_SOURCE_VALIDATION:
        # Parse item_id: field_mismatch_{contract_id}_{spec_id}_{token}
        # or provider_deviation_{contract_id}_{provider_spec_id}
        if item_id.startswith("field_mismatch_"):
            parts = item_id.replace("field_mismatch_", "").rsplit("_", 2)
            if len(parts) >= 3:
                contract_id, spec_id, token = parts[0], parts[1], parts[2]
                contract_fields = _get_contract_fields(shared_contracts, contract_id)
                suggestion = (
                    f"In {spec_id} requirement/acceptance_criteria, replace '{token}' "
                    f"with contract field names: {sorted(contract_fields)}"
                )
                hints.append({
                    "spec_id": spec_id,
                    "field": "requirement",
                    "suggestion": suggestion,
                    "confidence": VALIDATION_CONFIDENCE,
                })
        elif item_id.startswith("provider_deviation_"):
            parts = item_id.replace("provider_deviation_", "").rsplit("_", 1)
            if len(parts) >= 2:
                contract_id, provider_spec_id = parts[0], parts[1]
                contract_fields = _get_contract_fields(shared_contracts, contract_id)
                suggestion = (
                    f"In {provider_spec_id}, add mention of contract fields: "
                    f"{sorted(contract_fields)}"
                )
                hints.append({
                    "spec_id": provider_spec_id,
                    "field": "requirement",
                    "suggestion": suggestion,
                    "confidence": VALIDATION_CONFIDENCE,
                })

    elif source == RESOLUTION_SOURCE_AGENT:
        evidence_refs = item.get("evidence_refs") or []
        if isinstance(evidence_refs, list) and evidence_refs:
            spec_ids = [str(s).strip() for s in evidence_refs if str(s).strip()]
            if spec_ids:
                suggestion = (
                    f"Review {', '.join(spec_ids[:5])}"
                    + ("..." if len(spec_ids) > 5 else "")
                    + " to align on the ambiguity described above."
                )
                hints.append({
                    "spec_id": spec_ids[0],
                    "field": "requirement",
                    "suggestion": suggestion,
                    "confidence": AGENT_HINT_CONFIDENCE_DEFAULT,
                })

    return hints


def _get_contract_fields(shared_contracts: list[dict[str, Any]], contract_id: str) -> set[str]:
    """Extract field names from a contract by contract_id."""
    for c in shared_contracts:
        if not isinstance(c, dict):
            continue
        if str(c.get("contract_id", "")).strip() == contract_id:
            fields = c.get("fields") or []
            return {
                str(f.get("name", "")).strip().lower()
                for f in fields
                if isinstance(f, dict) and str(f.get("name", "")).strip()
            }
    return set()


def load_resolution_file(run_dir: Path) -> dict[str, Any] | None:
    """Load and parse resolutions.yaml from a run directory.

    Looks for run_dir/manual_resolution/resolutions.yaml.

    Returns:
        Parsed YAML as dict, or None if file does not exist or is invalid.
    """
    path = run_dir / "manual_resolution" / RESOLUTIONS_FILENAME
    if not path.exists() or not path.is_file():
        return None
    import yaml

    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def validate_resolutions(template: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate that every required item has a valid resolution.

    For agent items: chosen_option_id or non-empty free_text.
    For validation items:
      - edit_spec/no-option items require acknowledged=true.
      - option-based items require chosen_option_id in options.

    Returns:
        (is_valid, list of error messages).
    """
    errors: list[str] = []
    items = template.get("items") or []
    options_by_id: dict[str, dict[str, Any]] = {}

    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("item_id", ""))
        if not item_id:
            continue
        required = item.get("required", True)
        if not required:
            continue

        source = item.get("source", RESOLUTION_SOURCE_AGENT)
        chosen = item.get("chosen_option_id")
        free_text = (item.get("free_text") or "").strip()
        opts = [o for o in item.get("options", []) if isinstance(o, dict)]
        valid_ids = {str(o.get("option_id", "")).strip() for o in opts}

        if source == RESOLUTION_SOURCE_VALIDATION:
            if _is_edit_spec_item(item):
                if not bool(item.get("acknowledged")):
                    errors.append(
                        f"Item {item_id}: edit_spec validation items require acknowledged=true"
                    )
            elif not chosen:
                errors.append(f"Item {item_id}: validation items require chosen_option_id")
            else:
                if chosen not in valid_ids:
                    errors.append(f"Item {item_id}: chosen_option_id '{chosen}' not in options")
        else:
            if free_text:
                pass  # free_text overwrites chosen_option_id, valid
            elif chosen:
                if chosen not in valid_ids:
                    errors.append(f"Item {item_id}: chosen_option_id '{chosen}' not in options")
            else:
                errors.append(f"Item {item_id}: agent items require chosen_option_id or free_text")

    return (len(errors) == 0, errors)


def build_resolved_decisions_context(resolutions: dict[str, Any]) -> str:
    """Format resolved decisions as a text block for agent prompt injection.

    For each item: use free_text if non-empty (agent items only), else the
    label of the chosen option.
    """
    lines: list[str] = []
    items = resolutions.get("items") or []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("item_id", ""))
        if not item_id:
            continue

        free_text = (item.get("free_text") or "").strip()
        acknowledged = bool(item.get("acknowledged"))
        chosen_id = item.get("chosen_option_id")
        options = item.get("options") or []

        if free_text:
            lines.append(f"- [{item_id}] {free_text}")
        elif acknowledged:
            lines.append(f"- [{item_id}] Spec edits acknowledged")
        elif chosen_id:
            label = chosen_id
            for opt in options:
                if isinstance(opt, dict) and str(opt.get("option_id", "")) == chosen_id:
                    label = str(opt.get("label", chosen_id))
                    effect = opt.get("effect", "")
                    if effect:
                        lines.append(f"- [{item_id}] {label}")
                        lines.append(f"  (Effect: {effect})")
                    else:
                        lines.append(f"- [{item_id}] {label}")
                    break
            else:
                lines.append(f"- [{item_id}] {chosen_id}")
        else:
            continue

    return "\n".join(lines) if lines else ""


def update_resolution_item(
    resolutions_path: Path,
    item_index: int,
    chosen_option_id: str | None,
    free_text: str | None,
    acknowledged: bool | None = None,
) -> None:
    """Update a single item's resolution in resolutions.yaml."""
    import yaml

    with open(resolutions_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    items = data.get("items") or []
    if 0 <= item_index < len(items):
        item = items[item_index]
        if isinstance(item, dict):
            if free_text is not None:
                item["free_text"] = free_text.strip() if free_text else None
                item["chosen_option_id"] = None
            elif chosen_option_id is not None:
                item["chosen_option_id"] = chosen_option_id
                item["free_text"] = None
            if acknowledged is not None:
                item["acknowledged"] = bool(acknowledged)
                if acknowledged:
                    item["chosen_option_id"] = None
                    if "free_text" in item:
                        item["free_text"] = None

    with open(resolutions_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def clear_resolution_item(resolutions_path: Path, item_index: int) -> None:
    """Clear a single item's resolution (for Z / go-back)."""
    import yaml

    with open(resolutions_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    items = data.get("items") or []
    if 0 <= item_index < len(items):
        item = items[item_index]
        if isinstance(item, dict):
            item["chosen_option_id"] = None
            item["free_text"] = None
            if "acknowledged" in item:
                item["acknowledged"] = False

    with open(resolutions_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
