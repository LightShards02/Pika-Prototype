"""Count non-target spec flagging rates across all scenarios and rounds."""
import json
from pathlib import Path
from collections import defaultdict

BASE = Path("dataset/specimen/scenarios/refine-blockers")

# Target spec IDs per scenario (these are expected to be flagged)
TARGETS = {
    "RB01": {"A2016"},
    "RB02": {"A2041", "A2042"},
    "RB03": {"A2028"},
    "RB04": {"A2029", "A2040"},
    "RB05": {"A2028"},
    "RB06": {"A2038"},
    "RB07": {"A2042"},
    "RB08": {"A2016"},
    "RB09": {"A2024"},
    "RB10": {"A2036"},
    "RB11": {"A2016"},
    "RB12": {"A2028", "A2050"},
}

# spec_id -> {scenario -> count of runs it was flagged in}
# Also track total valid runs per scenario
flagged_in: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
valid_runs: dict[str, int] = defaultdict(int)

for rb in sorted(TARGETS.keys()):
    runs_dir = BASE / rb / "out/agent_runs/refine"
    if not runs_dir.exists():
        continue
    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        meta_path = run_dir / "run_meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        # Only count runs that completed the agent stage
        completed = meta.get("completed_stages", [])
        resolution = meta.get("resolution_status", "")
        if "agents" not in completed and "decomposition" not in completed:
            continue
        if resolution == "running":
            continue

        valid_runs[rb] += 1

        for output_file in ["ambiguity_output.json", "testability_output.json"]:
            out_path = run_dir / output_file
            if not out_path.exists():
                continue
            try:
                data = json.loads(out_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for item in (data.get("manual_resolution_items") or []):
                sid = item.get("spec_id", "").strip()
                if sid:
                    flagged_in[sid][rb] += 1

# Compute cross-scenario stats for non-target specs
print("NON-TARGET SPEC FLAGGING RATES")
print("=" * 90)
print(f"{'Spec':<8} {'Total flags':<14} {'Scenarios':<12} {'Per-scenario rates (run_flagged/valid)'}")
print("-" * 90)

results = []
for sid, scenario_counts in flagged_in.items():
    # Check if this spec is a target in the scenarios where it was flagged
    non_target_scenarios = {
        rb: count for rb, count in scenario_counts.items()
        if sid not in TARGETS.get(rb, set())
    }
    if not non_target_scenarios:
        continue
    total_flag_runs = sum(non_target_scenarios.values())
    num_scenarios = len(non_target_scenarios)
    detail = "  ".join(
        f"{rb}:{count}/{valid_runs[rb]}"
        for rb, count in sorted(non_target_scenarios.items())
    )
    results.append((total_flag_runs, num_scenarios, sid, detail))

results.sort(reverse=True)
for total, n_scen, sid, detail in results:
    print(f"{sid:<8} {total:<14} {n_scen:<12} {detail}")

print()
print("SUMMARY — specs flagged across 3+ scenarios (non-target):")
print("-" * 60)
for total, n_scen, sid, detail in results:
    if n_scen >= 3:
        print(f"  {sid}: {n_scen} scenarios, {total} total flag-runs")
        print(f"    {detail}")
