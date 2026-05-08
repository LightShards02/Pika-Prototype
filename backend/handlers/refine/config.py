"""Refine command configuration parsing and normalization."""

from __future__ import annotations

from typing import Any



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
        quality_auditor_prompt_name: str
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

    from core.pika_config import get_prompt_name
    quality_auditor_prompt = get_prompt_name("refine", "quality_auditor")
    editor_prompt = get_prompt_name("refine", "spec_editor")

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

    appendix_cfg = refine.get("appendix") or {}
    if not isinstance(appendix_cfg, dict):
        appendix_cfg = {}
    max_appendix_chars_raw = appendix_cfg.get("max_appendix_chars", 0)
    try:
        max_appendix_chars = max(0, int(max_appendix_chars_raw))
    except (TypeError, ValueError):
        max_appendix_chars = 0

    agent_replicas_raw = refine.get("agent_replicas", 4)
    try:
        agent_replicas = max(1, int(agent_replicas_raw))
    except (TypeError, ValueError):
        agent_replicas = 4

    consensus_min_votes_raw = refine.get("consensus_min_votes", 3)
    try:
        consensus_min_votes = max(1, min(int(consensus_min_votes_raw), agent_replicas))
    except (TypeError, ValueError):
        consensus_min_votes = min(3, agent_replicas)

    return {
        "enabled": enabled,
        "quality_auditor_prompt_name": quality_auditor_prompt,
        "spec_editor_prompt_name": editor_prompt,
        "decomposition_enabled": decomp_enabled,
        "decomposition_blocking": decomp_blocking,
        "similarity_threshold": similarity_threshold,
        "variance_threshold": variance_threshold,
        "max_appendix_chars": max_appendix_chars,
        "agent_replicas": agent_replicas,
        "consensus_min_votes": consensus_min_votes,
    }
