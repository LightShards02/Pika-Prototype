"""Workspace scaffolding helpers.

Idempotently seeds a minimal valid ``config/config.yaml`` into a workspace
root from the bundled ``backend/templates/workspaces/default/`` template.
This module is intentionally self-contained: it does not import from
``core/`` or ``handlers/`` and uses only the standard library so it
remains usable in any context where the workspace base directory has
just been materialized.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["seed_default_config_if_missing"]


# backend/api/workspace_scaffold.py -> backend/templates/workspaces/default
_TEMPLATE_ROOT = (
    Path(__file__).resolve().parent.parent / "templates" / "workspaces" / "default"
)
_TEMPLATE_CONFIG = _TEMPLATE_ROOT / "config" / "config.yaml"


def seed_default_config_if_missing(workspace_root: Path) -> bool:
    """Seed a minimal valid ``config/config.yaml`` into ``workspace_root``.

    Behavior:
      * If ``workspace_root/config/config.yaml`` already exists, return
        ``False`` without modifying any file on disk. The check is
        strictly idempotent.
      * Otherwise, create ``workspace_root/config/`` (and parents) if
        needed, then write the bundled template after substituting the
        ``{{ name }}`` placeholder with ``workspace_root.name``. Returns
        ``True``.

    The substitution uses plain ``str.replace`` -- no template engine is
    used or required. The bundled template lives at
    ``backend/templates/workspaces/default/config/config.yaml`` and must
    validate against ``backend/config/config.schema.json`` once
    substituted.
    """
    workspace_root = Path(workspace_root)
    target = workspace_root / "config" / "config.yaml"
    if target.exists():
        return False

    template_text = _TEMPLATE_CONFIG.read_text(encoding="utf-8")
    seeded = template_text.replace("{{ name }}", workspace_root.name)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(seeded, encoding="utf-8")
    return True
