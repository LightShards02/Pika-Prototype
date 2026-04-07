"""Deterministic NLP decomposition check for the refine command.

Uses sentence-transformers to detect specs with mixed topic responsibilities
(split candidates) and specs that are overly similar within the same module
(merge candidates).
"""

from __future__ import annotations

import re
from typing import Any

try:
    from sentence_transformers import SentenceTransformer  # type: ignore[import]
except ImportError:
    SentenceTransformer = None  # type: ignore[assignment,misc]


_MIN_SENTENCES_FOR_VARIANCE = 3
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _embed_texts(texts: list[str], model: Any) -> list[Any]:
    """Embed a list of texts using the provided sentence-transformers model."""
    return model.encode(texts, convert_to_numpy=True, show_progress_bar=False)


def _compute_pairwise_cosine(a: Any, b: Any) -> float:
    """Compute cosine similarity between two numpy embedding vectors."""
    import numpy as np

    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _compute_sentence_variance(text: str, model: Any) -> float:
    """Compute mean pairwise cosine similarity variance across sentence embeddings.

    Splits text into sentences, embeds each, and computes the variance of all
    pairwise cosine similarities. High variance indicates mixed topic content.

    Returns 0.0 when fewer than _MIN_SENTENCES_FOR_VARIANCE sentences are found.
    """
    import numpy as np

    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    if len(sentences) < _MIN_SENTENCES_FOR_VARIANCE:
        return 0.0

    embeddings = _embed_texts(sentences, model)
    sims: list[float] = []
    for i in range(len(embeddings)):
        for j in range(i + 1, len(embeddings)):
            sims.append(_compute_pairwise_cosine(embeddings[i], embeddings[j]))

    return float(np.var(sims)) if sims else 0.0


def _build_decomposition_items(flags: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert decomposition flags into manual_resolution_item dicts.

    Decomposition items offer only let_agent_edit and skip — no accept_suggestion
    because structural changes (split/merge) require agent judgment, not a
    pre-computed text replacement.
    """
    items: list[dict[str, Any]] = []

    for candidate in flags.get("split_candidates", []):
        spec_id = str(candidate.get("spec_id", ""))
        variance = float(candidate.get("variance", 0.0))
        reason = str(candidate.get("reason", "High topic variance detected."))
        items.append({
            "item_id": f"DECOMP-SPLIT-{spec_id}",
            "title": f"Spec may have mixed responsibilities: {spec_id}",
            "spec_id": spec_id,
            "issue_kind": "split_candidate",
            "reason": reason,
            "variance": variance,
            "options": [
                {
                    "option_id": "let_agent_edit",
                    "label": "Let agent split",
                    "effect": "Calls spec_editor to split this spec into two or more focused specs.",
                },
                {
                    "option_id": "skip",
                    "label": "Keep as-is",
                    "effect": "Leaves this spec unchanged.",
                },
            ],
        })

    for candidate in flags.get("merge_candidates", []):
        spec_ids: list[str] = [str(s) for s in candidate.get("spec_ids", [])]
        similarity = float(candidate.get("similarity", 0.0))
        reason = str(candidate.get("reason", "High cosine similarity detected."))
        id_label = "-".join(spec_ids[:2])
        items.append({
            "item_id": f"DECOMP-MERGE-{id_label}",
            "title": f"Specs may overlap: {' + '.join(spec_ids)}",
            "spec_ids": spec_ids,
            "issue_kind": "merge_candidate",
            "reason": reason,
            "similarity": similarity,
            "options": [
                {
                    "option_id": "let_agent_edit",
                    "label": "Let agent merge",
                    "effect": "Calls spec_editor to merge these specs into one.",
                },
                {
                    "option_id": "skip",
                    "label": "Keep as-is",
                    "effect": "Leaves these specs unchanged.",
                },
            ],
        })

    return items


def run_decomposition_check(
    rows: list[dict[str, Any]],
    *,
    similarity_threshold: float = 0.85,
    variance_threshold: float = 0.15,
) -> dict[str, Any]:
    """Run NLP decomposition check on SADS spec rows.

    Uses each row's requirement text only (refine input does not include acceptance_criteria).

    Returns:
        {
            "split_candidates": [{"spec_id", "reason", "variance"}],
            "merge_candidates": [{"spec_ids", "reason", "similarity"}],
            "skipped": False,
        }
    """
    if SentenceTransformer is None:
        from core.errors import PikaError
        raise PikaError(
            "sentence-transformers library is not installed. "
            "Install it (`pip install sentence-transformers`) or set decomposition.enabled: false in config."
        )
    model = SentenceTransformer("all-MiniLM-L6-v2")

    req_col = _find_col_lower(rows, "requirement")
    spec_col = _find_col_lower(rows, "spec_id")
    tag_col = _find_col_lower(rows, "module_tag")

    split_candidates: list[dict[str, Any]] = []
    merge_candidates: list[dict[str, Any]] = []

    # --- Split candidates: per-spec sentence variance ---
    for row in rows:
        if not isinstance(row, dict):
            continue
        spec_id = str(row.get(spec_col or "spec_id", "")).strip()
        if not spec_id:
            continue
        req = str(row.get(req_col or "requirement", "")).strip()
        combined = req
        if not combined:
            continue
        variance = _compute_sentence_variance(combined, model)
        if variance > variance_threshold:
            split_candidates.append({
                "spec_id": spec_id,
                "reason": (
                    f"Sentence-level embedding variance {variance:.3f} exceeds threshold "
                    f"{variance_threshold:.3f}, suggesting mixed responsibilities."
                ),
                "variance": round(variance, 4),
            })

    # --- Merge candidates: cross-spec similarity within same module_tag ---
    by_module: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        spec_id = str(row.get(spec_col or "spec_id", "")).strip()
        module_tag = str(row.get(tag_col or "module_tag", "")).strip()
        if not spec_id or not module_tag:
            continue
        req = str(row.get(req_col or "requirement", "")).strip()
        combined = req
        by_module.setdefault(module_tag, []).append({
            "spec_id": spec_id,
            "text": combined,
        })

    for module_tag, specs in by_module.items():
        if len(specs) < 2:
            continue
        texts = [s["text"] for s in specs]
        embeddings = _embed_texts(texts, model)
        for i in range(len(specs)):
            for j in range(i + 1, len(specs)):
                sim = _compute_pairwise_cosine(embeddings[i], embeddings[j])
                if sim >= similarity_threshold:
                    merge_candidates.append({
                        "spec_ids": [specs[i]["spec_id"], specs[j]["spec_id"]],
                        "reason": (
                            f"Cosine similarity {sim:.3f} exceeds threshold "
                            f"{similarity_threshold:.3f} within module '{module_tag}'."
                        ),
                        "similarity": round(sim, 4),
                    })

    return {
        "split_candidates": split_candidates,
        "merge_candidates": merge_candidates,
        "skipped": False,
    }


def _find_col_lower(rows: list[dict[str, Any]], name: str) -> str | None:
    """Return the actual column key matching name case-insensitively from the first row."""
    if not rows:
        return None
    first = rows[0]
    if not isinstance(first, dict):
        return None
    for key in first:
        if str(key).strip().lower() == name.lower():
            return key
    return None
