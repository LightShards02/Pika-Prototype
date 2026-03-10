"""Load and format per-project controlled vocabulary for LLM prompts.

The control vocab is a YAML file with categorized terms and definitions.
It is injected into all LLM-using agent prompts to ensure consistent terminology.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.errors import PromptParseError

try:
    import yaml
except ImportError:  # pragma: no cover - environment dependency
    yaml = None

_LOGGER = logging.getLogger(__name__)


def load_control_vocab(path: Path) -> dict[str, Any]:
    """Parse and validate the control vocab YAML file.

    Args:
        path: Path to the vocab YAML file.

    Returns:
        Parsed vocab dict with 'version' and 'categories' keys.
        categories maps category name -> list of {term, definition, synonyms?} dicts.

    Raises:
        PromptParseError: When YAML is malformed or structure is invalid.
    """
    if yaml is None:
        raise PromptParseError(
            "Missing dependency 'pyyaml'. Install it with: pip install pyyaml"
        )

    if not path.exists() or not path.is_file():
        raise PromptParseError(f"Control vocab file not found: {path}")

    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PromptParseError(
            f"Invalid YAML in control vocab file {path}: {exc}"
        ) from exc
    except OSError as exc:
        raise PromptParseError(
            f"Unable to read control vocab file {path}: {exc}"
        ) from exc

    if loaded is None:
        return {"version": 1, "categories": {}}

    if not isinstance(loaded, dict):
        raise PromptParseError(
            f"Control vocab file root must be an object: {path}"
        )

    categories = loaded.get("categories")
    if categories is None:
        return {"version": loaded.get("version", 1), "categories": {}}

    if not isinstance(categories, dict):
        raise PromptParseError(
            f"Control vocab 'categories' must be an object: {path}"
        )

    normalized: dict[str, list[dict[str, Any]]] = {}
    for cat_name, items in categories.items():
        if not isinstance(cat_name, str) or not cat_name.strip():
            raise PromptParseError(
                f"Control vocab category name must be non-empty string: {path}"
            )
        if not isinstance(items, list):
            raise PromptParseError(
                f"Control vocab category '{cat_name}' must be a list: {path}"
            )
        term_list: list[dict[str, Any]] = []
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                raise PromptParseError(
                    f"Control vocab category '{cat_name}' item [{idx}] must be object: {path}"
                )
            term_val = item.get("term")
            def_val = item.get("definition")
            if not isinstance(term_val, str) or not term_val.strip():
                raise PromptParseError(
                    f"Control vocab category '{cat_name}' item [{idx}] must have non-empty 'term': {path}"
                )
            if not isinstance(def_val, str):
                raise PromptParseError(
                    f"Control vocab category '{cat_name}' item [{idx}] must have 'definition' string: {path}"
                )
            entry: dict[str, Any] = {"term": term_val.strip(), "definition": str(def_val)}
            raw_synonyms = item.get("synonyms")
            if raw_synonyms is not None:
                if not isinstance(raw_synonyms, list):
                    raise PromptParseError(
                        f"Control vocab category '{cat_name}' item [{idx}] "
                        f"'synonyms' must be a list: {path}"
                    )
                synonyms_list: list[str] = []
                for s_idx, s_val in enumerate(raw_synonyms):
                    if not isinstance(s_val, str):
                        raise PromptParseError(
                            f"Control vocab category '{cat_name}' item [{idx}] "
                            f"synonyms[{s_idx}] must be string: {path}"
                        )
                    synonyms_list.append(str(s_val).strip())
                entry["synonyms"] = [s for s in synonyms_list if s]
            term_list.append(entry)
        normalized[cat_name.strip()] = term_list

    return {"version": loaded.get("version", 1), "categories": normalized}


def format_control_vocab_section(vocab: dict[str, Any]) -> str:
    """Render categories/terms/definitions into a prompt-friendly text block.

    Args:
        vocab: Parsed vocab dict from load_control_vocab.

    Returns:
        Formatted string suitable for injection into prompts.
        Empty string when vocab has no categories or all categories are empty.
    """
    categories = vocab.get("categories")
    if not isinstance(categories, dict) or not categories:
        return ""

    lines: list[str] = ["Controlled Vocabulary:", ""]
    for cat_name, items in sorted(categories.items()):
        if not items:
            continue
        # Title-case category for display (e.g. "architecture" -> "Architecture")
        display_name = cat_name[0].upper() + cat_name[1:] if cat_name else ""
        lines.append(f"[{display_name}]")
        for item in items:
            term = item.get("term", "")
            definition = item.get("definition", "")
            synonyms = item.get("synonyms")
            if isinstance(synonyms, list) and synonyms:
                synonym_str = ", ".join(str(s) for s in synonyms if s)
                term_part = f"{term} (also: {synonym_str})"
            else:
                term_part = term
            lines.append(f"- {term_part}: {definition}")
        lines.append("")

    result = "\n".join(lines).rstrip()
    return result if result else ""


def resolve_control_vocab_content(
    config: dict[str, Any],
    project_root: Path,
) -> str:
    """Resolve control vocab content for injection into prompts.

    Reads project.control_vocab_path from config, loads and formats the file.
    Returns empty string when not configured, file missing, or file is empty.

    Args:
        config: Full PIKA config.
        project_root: Project root path.

    Returns:
        Formatted control vocab section, or empty string.
    """
    project = config.get("project")
    if not isinstance(project, dict):
        return ""

    path_val = project.get("control_vocab_path")
    if not isinstance(path_val, str) or not path_val.strip():
        return ""

    path_val = path_val.strip()
    candidate = Path(path_val)
    if not candidate.is_absolute():
        candidate = (project_root / path_val).resolve()

    if not candidate.exists() or not candidate.is_file():
        _LOGGER.warning(
            "Control vocab file not found at %s; skipping vocab injection.",
            candidate,
        )
        return ""

    try:
        vocab = load_control_vocab(candidate)
    except PromptParseError:
        raise

    return format_control_vocab_section(vocab)
