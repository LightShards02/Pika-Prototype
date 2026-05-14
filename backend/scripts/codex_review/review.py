"""Codex code reviewer driver.

Invokes Loca's openai-codex provider with the PIKA reviewer prompt and a
structured-output schema. Returns a JSON review object.

Usage (from backend/):
    python -m scripts.codex_review.review \
        --brief path/to/milestone_brief.md \
        --diff path/to/changes.diff \
        --inventory path/to/file_inventory.md \
        --out path/to/review.json

Or import as a module:
    from scripts.codex_review.review import run_codex_review
    review = run_codex_review(brief=..., diff=..., inventory=..., locked_decisions=...)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from loca.config import LocaConfig
from loca.agent import Agent
from loca.llm import get_llm_client
from loca.tools import build_default_registry


_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parents[2]  # backend/scripts/codex_review/.. = repo root
_MEMORY_FILE = Path.home() / ".claude" / "projects" / "C--Users-night-Work-Echelondx-Pika" / "memory" / "project_rest_api_redesign.md"


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_reviewer_prompt() -> str:
    return _load_text(_THIS_DIR / "reviewer_prompt.md")


def _load_review_schema() -> dict[str, Any]:
    return json.loads(_load_text(_THIS_DIR / "review_schema.json"))


def _load_locked_decisions() -> str:
    """Read locked decisions from the project memory file."""
    if _MEMORY_FILE.exists():
        return _load_text(_MEMORY_FILE)
    return "(locked decisions file not found; reviewer must rely on the brief alone)"


def _build_user_prompt(
    *,
    brief: str,
    diff: str,
    inventory: str,
    locked_decisions: str,
) -> str:
    return (
        "# Context: locked architectural decisions\n\n"
        f"{locked_decisions}\n\n"
        "---\n\n"
        "# Milestone brief\n\n"
        f"{brief}\n\n"
        "---\n\n"
        "# File inventory\n\n"
        f"{inventory}\n\n"
        "---\n\n"
        "# Unified diff\n\n"
        "```diff\n"
        f"{diff}\n"
        "```\n\n"
        "---\n\n"
        "Produce the structured review per the schema. JSON only."
    )


def _build_loca_config(working_dir: Path) -> LocaConfig:
    """Build a LocaConfig for openai-codex with parameters suited to code review."""
    config_dict: dict[str, Any] = {
        "model": {
            "provider": "openai-codex",
            "name": "gpt-5.3-codex",
            "api_key": "",
            "temperature": 0.0,
            "top_p": None,
            "reasoning_effort": "high",
            "base_url": None,
        },
        "agent": {
            "max_turns": 30,
            "max_output_bytes": 262_144,
            "timeout_seconds": 600,
            "max_schema_retries": 2,
        },
        "sandbox": {
            "mode": "full_auto",
            "working_dir": str(working_dir.resolve()),
        },
        "output": {
            "format": "plain",
            "show_tool_calls": False,
            "stream": False,
        },
    }
    return LocaConfig.model_validate(config_dict)


def run_codex_review(
    *,
    brief: str,
    diff: str,
    inventory: str,
    locked_decisions: str | None = None,
    working_dir: Path | None = None,
) -> dict[str, Any]:
    """Invoke Codex via Loca to review a milestone diff.

    Returns the parsed review JSON conforming to review_schema.json.
    Raises RuntimeError on invocation failure.
    """
    system_prompt = _load_reviewer_prompt()
    schema = _load_review_schema()
    decisions = locked_decisions if locked_decisions is not None else _load_locked_decisions()
    user_prompt = _build_user_prompt(
        brief=brief, diff=diff, inventory=inventory, locked_decisions=decisions,
    )
    cfg = _build_loca_config(working_dir or _REPO_ROOT)

    llm = get_llm_client(cfg)
    tools = build_default_registry(cfg)
    agent = Agent(
        llm=llm,
        tools=tools,
        system=system_prompt,
        max_turns=cfg.agent.max_turns,
        stream=False,
        json_schema=schema,
        max_schema_retries=cfg.agent.max_schema_retries,
    )
    result = agent.run(user_prompt)

    if result.stop_reason == "error":
        raise RuntimeError(f"Codex reviewer error: {result.error}")
    if result.stop_reason == "max_turns":
        raise RuntimeError(f"Codex reviewer exceeded max turns ({result.turns})")
    if result.json_output is None:
        raise RuntimeError(
            f"Codex reviewer produced no JSON output (stop_reason={result.stop_reason})"
        )

    return result.json_output


def _main() -> int:
    parser = argparse.ArgumentParser(description="Run Codex code review for a PIKA milestone.")
    parser.add_argument("--brief", required=True, type=Path, help="Path to milestone brief markdown.")
    parser.add_argument("--diff", required=True, type=Path, help="Path to unified diff file.")
    parser.add_argument("--inventory", required=True, type=Path, help="Path to file inventory markdown.")
    parser.add_argument("--decisions", type=Path, default=None, help="Optional override for locked decisions file.")
    parser.add_argument("--working-dir", type=Path, default=None, help="Sandbox working dir (default: repo root).")
    parser.add_argument("--out", type=Path, required=True, help="Path to write review JSON.")
    args = parser.parse_args()

    decisions = args.decisions.read_text(encoding="utf-8") if args.decisions else None
    review = run_codex_review(
        brief=args.brief.read_text(encoding="utf-8"),
        diff=args.diff.read_text(encoding="utf-8"),
        inventory=args.inventory.read_text(encoding="utf-8"),
        locked_decisions=decisions,
        working_dir=args.working_dir,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(review, indent=2), encoding="utf-8")
    print(f"Review written to {args.out}", file=sys.stderr)
    print(f"Verdict: {review.get('verdict')}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
