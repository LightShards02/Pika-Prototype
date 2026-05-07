"""P6 migration helper: report enricher specs missing a ``test_plan`` side-file.

Use when upgrading a workspace from a P2-era refine output (where ``test_plan``
was optional in ``spec_testability_enricher_output.schema.json``) to P6 (where
the schema requires ``test_plan``).

What this script does
---------------------
1. Loads the workspace's design spec CSV (``out/state/REFINED-SPEC.csv`` by
   default; pass ``--design-spec`` to override).
2. Loads existing ``out/state/test_plans/<spec_id>.json`` side-files via
   ``core.spec_acceptance.load_spec_test_plans``.
3. Reports specs that have an ``acceptance_criteria`` value (i.e. the enricher
   considered them testable) but lack a ``test_plan`` side-file.

What this script does NOT do
----------------------------
It does not invoke the enricher. The cheapest way to backfill is:

  1. Re-run ``pika agent refine --project-root <workspace>`` against the same
     design spec input. The new enricher prompt (P2/P6) will produce
     ``test_plan`` for every clear spec.
  2. Resume any in-flight implement runs after refine completes.

Exit codes
----------
- ``0``: all testable specs have a test_plan side-file (no migration needed).
- ``1``: one or more testable specs are missing a test_plan side-file (the
  output lists them so you can decide to re-run refine or hand-author the
  side-files).

Usage
-----
::

    python -m scripts.migrate_test_plans \\
        --project-root /path/to/workspace \\
        [--design-spec out/state/REFINED-SPEC.csv]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as ``python -m scripts.migrate_test_plans`` from backend/.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from core.spec_acceptance import (  # noqa: E402  (sys.path bootstrap above)
    load_spec_acceptance_criteria,
    load_spec_test_plans,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument(
        "--design-spec",
        type=Path,
        default=None,
        help="Path to the SADS CSV. Defaults to <project-root>/out/state/REFINED-SPEC.csv.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    project_root: Path = args.project_root.resolve()
    if not project_root.is_dir():
        print(f"ERROR: --project-root not a directory: {project_root}", file=sys.stderr)
        return 2

    design_path: Path = (
        args.design_spec.resolve()
        if args.design_spec is not None
        else project_root / "out" / "state" / "REFINED-SPEC.csv"
    )
    if not design_path.is_file():
        print(f"ERROR: design spec CSV not found: {design_path}", file=sys.stderr)
        return 2

    ac_map = load_spec_acceptance_criteria(design_path)
    if not ac_map:
        print(
            "No specs with acceptance_criteria found. Either the design CSV "
            "is missing the acceptance_criteria column or refine has not run yet.",
            file=sys.stderr,
        )
        return 0

    test_plans = load_spec_test_plans(project_root, spec_ids=set(ac_map.keys()))
    have_plan: set[str] = {
        sid
        for sid, payload in test_plans.items()
        if isinstance(payload, dict) and isinstance(payload.get("test_plan"), dict)
    }

    missing = sorted(set(ac_map.keys()) - have_plan)
    if not missing:
        print(
            f"OK: {len(ac_map)} testable spec(s) all have test_plan side-files. "
            "P6 schema will validate."
        )
        return 0

    print(
        f"FOUND {len(missing)} spec(s) missing a test_plan side-file "
        f"(out of {len(ac_map)} testable spec(s)):"
    )
    for sid in missing:
        ac_text = (ac_map[sid].get("acceptance_criteria") or "").strip()
        ac_preview = ac_text if len(ac_text) <= 80 else ac_text[:77] + "..."
        print(f"  - {sid}: {ac_preview}")
    print()
    print(
        "To backfill: re-run `pika agent refine --project-root "
        f"{project_root}`. The P2/P6 enricher prompt produces test_plan for every "
        "clear spec, and the refine handler will write the side-files at "
        "out/state/test_plans/<spec_id>.json."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
