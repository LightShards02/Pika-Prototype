"""Workspace memory layer: four free-form Markdown files plumbed into agent prompts.

Memory files live at ``<workspace>/out/state/memory/{memory,lessons,tasks,gaps}.md``.
Phase functions read them once at run start; manual writes happen via REST PUT.
Empty/missing files are still rendered (header + blank body) so prompts get a
predictable layout.
"""

from __future__ import annotations

import os
from pathlib import Path


_MEMORY_FILES: tuple[str, ...] = ("memory", "lessons", "tasks", "gaps")
_MEMORY_FILE_HEADERS: dict[str, str] = {
    "memory": "Workspace Memory",
    "lessons": "Lessons",
    "tasks": "Tasks",
    "gaps": "Gaps",
}


def memory_files() -> tuple[str, ...]:
    """Return the locked ordered tuple of valid memory file names."""
    return _MEMORY_FILES


def memory_dir(workspace_root: Path) -> Path:
    """Return ``<workspace>/out/state/memory``."""
    return workspace_root / "out" / "state" / "memory"


def is_valid_file(name: str) -> bool:
    """True if ``name`` is one of the four whitelisted memory file names."""
    return name in _MEMORY_FILES


def _file_path(workspace_root: Path, name: str) -> Path:
    return memory_dir(workspace_root) / f"{name}.md"


def read_file(workspace_root: Path, name: str) -> str:
    """Return file contents, or empty string when missing."""
    if not is_valid_file(name):
        raise ValueError(f"unknown memory file: {name!r}")
    path = _file_path(workspace_root, name)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def read_all(workspace_root: Path) -> dict[str, str]:
    """Return mapping with all four memory files; missing files surface as ``""``."""
    return {name: read_file(workspace_root, name) for name in _MEMORY_FILES}


def write_file(workspace_root: Path, name: str, text: str) -> None:
    """Atomically write ``text`` to the named memory file (temp + rename)."""
    if not is_valid_file(name):
        raise ValueError(f"unknown memory file: {name!r}")
    path = _file_path(workspace_root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _default_body(name: str) -> str:
    return f"# {_MEMORY_FILE_HEADERS[name]}\n\n"


def bootstrap(workspace_root: Path) -> None:
    """Create memory dir + four files with H1 headers when missing. Idempotent."""
    target = memory_dir(workspace_root)
    target.mkdir(parents=True, exist_ok=True)
    for name in _MEMORY_FILES:
        path = _file_path(workspace_root, name)
        if path.exists():
            continue
        path.write_text(_default_body(name), encoding="utf-8")


def render_for_prompt(memory: dict[str, str] | None) -> str:
    """Render the four-section Markdown blob with locked ``memory -> lessons -> tasks -> gaps`` order."""
    body = memory or {}
    parts: list[str] = ["# Workspace Memory", ""]
    for name in _MEMORY_FILES:
        header = _MEMORY_FILE_HEADERS[name]
        content = body.get(name, "") or ""
        parts.append(f"## {header}")
        parts.append("")
        parts.append(content.rstrip("\n"))
        parts.append("")
    return "\n".join(parts).rstrip("\n") + "\n"


def memory_template_value(ctx: object) -> str:
    """Return ``render_for_prompt(ctx.memory_context)`` or ``""`` when unset or invalid."""
    memory_context = getattr(ctx, "memory_context", None)
    if not isinstance(memory_context, dict) or not memory_context:
        return ""
    return render_for_prompt(memory_context)
