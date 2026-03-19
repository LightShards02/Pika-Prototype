"""Refine command configuration parsing and normalization."""

from __future__ import annotations

from typing import Any


_DEFAULT_AMBIGUITY_PROMPT = "spec_ambiguity_detector"
_DEFAULT_TESTABILITY_PROMPT = "spec_testability_auditor"
_DEFAULT_SPEC_EDITOR_PROMPT = "spec_editor"
_DEFAULT_DECOMPOSITION_ENABLED = True
_DEFAULT_DECOMPOSITION_BLOCKING = False
_DEFAULT_SIMILARITY_THRESHOLD = 0.85
_DEFAULT_VARIANCE_THRESHOLD = 0.15


def _parse_threshold(value: Any, default: float) -> float:
    """Parse a float threshold clamped to [0.0, 1.0]."""
    if value is None:
        return default
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _get_refine_cfg(config: dict[str, Any]) -> dict[str, Any]:
    """Return refine config with defaults and normalized values.

    Returns dict with keys:
        enabled: bool
        ambiguity_detector_prompt_name: str
        testability_auditor_prompt_name: str
        spec_editor_prompt_name: str
        decomposition_enabled: bool
        decomposition_blocking: bool
        similarity_threshold: float
        variance_threshold: float
    """
    commands = config.get("commands") if isinstance(config, dict) else {}
    refine = commands.get("refine") if isinstance(commands, dict) else {}
    if not isinstance(refine, dict):
        refine = {}

    enabled_raw = refine.get("enabled", True)
    enabled = enabled_raw if isinstance(enabled_raw, bool) else True

    ambiguity_cfg = refine.get("ambiguity_detector") or {}
    if not isinstance(ambiguity_cfg, dict):
        ambiguity_cfg = {}
    ambiguity_prompt = str(
        ambiguity_cfg.get("prompt_name", _DEFAULT_AMBIGUITY_PROMPT)
    ).strip() or _DEFAULT_AMBIGUITY_PROMPT

    testability_cfg = refine.get("testability_auditor") or {}
    if not isinstance(testability_cfg, dict):
        testability_cfg = {}
    testability_prompt = str(
        testability_cfg.get("prompt_name", _DEFAULT_TESTABILITY_PROMPT)
    ).strip() or _DEFAULT_TESTABILITY_PROMPT

    editor_cfg = refine.get("spec_editor") or {}
    if not isinstance(editor_cfg, dict):
        editor_cfg = {}
    editor_prompt = str(
        editor_cfg.get("prompt_name", _DEFAULT_SPEC_EDITOR_PROMPT)
    ).strip() or _DEFAULT_SPEC_EDITOR_PROMPT

    decomp_cfg = refine.get("decomposition") or {}
    if not isinstance(decomp_cfg, dict):
        decomp_cfg = {}

    decomp_enabled_raw = decomp_cfg.get("enabled", _DEFAULT_DECOMPOSITION_ENABLED)
    decomp_enabled = decomp_enabled_raw if isinstance(decomp_enabled_raw, bool) else _DEFAULT_DECOMPOSITION_ENABLED

    decomp_blocking_raw = decomp_cfg.get("blocking", _DEFAULT_DECOMPOSITION_BLOCKING)
    decomp_blocking = decomp_blocking_raw if isinstance(decomp_blocking_raw, bool) else _DEFAULT_DECOMPOSITION_BLOCKING

    similarity_threshold = _parse_threshold(
        decomp_cfg.get("similarity_threshold"), _DEFAULT_SIMILARITY_THRESHOLD
    )
    variance_threshold = _parse_threshold(
        decomp_cfg.get("variance_threshold"), _DEFAULT_VARIANCE_THRESHOLD
    )

    return {
        "enabled": enabled,
        "ambiguity_detector_prompt_name": ambiguity_prompt,
        "testability_auditor_prompt_name": testability_prompt,
        "spec_editor_prompt_name": editor_prompt,
        "decomposition_enabled": decomp_enabled,
        "decomposition_blocking": decomp_blocking,
        "similarity_threshold": similarity_threshold,
        "variance_threshold": variance_threshold,
    }
