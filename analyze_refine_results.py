"""Analyze refine run capture rates across all scenarios."""
import json
from pathlib import Path

BASE = Path("dataset/specimen")
SCENARIOS_BASE = BASE / "scenarios/refine-blockers"

# Scenario definitions: (expected_family, target_spec_ids, agent_output_key)
# agent_output_key: "decomposition", "ambiguity", "testability", "both"
SCENARIOS = {
    "default": {
        "expected_family": "none (control)",
        "capture_check": "false_positive_rate",
        "runs_dir": BASE / "out/agent_runs/refine",
    },
    "RB01": {
        "expected_family": "split_candidate",
        "target_spec_ids": ["A2016"],
        "capture_check": "decomposition_split",
        "runs_dir": SCENARIOS_BASE / "RB01/out/agent_runs/refine",
    },
    "RB02": {
        "expected_family": "merge_candidate",
        "target_spec_ids": ["A2041", "A2042"],
        "capture_check": "decomposition_merge",
        "runs_dir": SCENARIOS_BASE / "RB02/out/agent_runs/refine",
    },
    "RB03": {
        "expected_family": "ambiguity",
        "target_spec_ids": ["A2028"],
        "capture_check": "ambiguity",
        "runs_dir": SCENARIOS_BASE / "RB03/out/agent_runs/refine",
    },
    "RB04": {
        "expected_family": "ambiguity",
        "target_spec_ids": ["A2029", "A2040"],
        "capture_check": "ambiguity_any",
        "runs_dir": SCENARIOS_BASE / "RB04/out/agent_runs/refine",
    },
    "RB05": {
        "expected_family": "ambiguity",
        "target_spec_ids": ["A2028"],
        "capture_check": "ambiguity",
        "runs_dir": SCENARIOS_BASE / "RB05/out/agent_runs/refine",
    },
    "RB06": {
        "expected_family": "ambiguity",
        "target_spec_ids": ["A2038"],
        "capture_check": "ambiguity",
        "runs_dir": SCENARIOS_BASE / "RB06/out/agent_runs/refine",
    },
    "RB07": {
        "expected_family": "testability",
        "target_spec_ids": ["A2042"],
        "capture_check": "testability",
        "runs_dir": SCENARIOS_BASE / "RB07/out/agent_runs/refine",
    },
    "RB08": {
        "expected_family": "testability",
        "target_spec_ids": ["A2016"],
        "capture_check": "testability",
        "runs_dir": SCENARIOS_BASE / "RB08/out/agent_runs/refine",
    },
    "RB09": {
        "expected_family": "testability",
        "target_spec_ids": ["A2024"],
        "capture_check": "testability",
        "runs_dir": SCENARIOS_BASE / "RB09/out/agent_runs/refine",
    },
    "RB10": {
        "expected_family": "testability",
        "target_spec_ids": ["A2036"],
        "capture_check": "testability",
        "runs_dir": SCENARIOS_BASE / "RB10/out/agent_runs/refine",
    },
    "RB11": {
        "expected_family": "ambiguity+testability",
        "target_spec_ids": ["A2016"],
        "capture_check": "both",
        "runs_dir": SCENARIOS_BASE / "RB11/out/agent_runs/refine",
    },
    "RB12": {
        "expected_family": "ambiguity+testability",
        "target_spec_ids": ["A2028", "A2050"],
        "capture_check": "both_any",
        "runs_dir": SCENARIOS_BASE / "RB12/out/agent_runs/refine",
    },
}


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_manual_res_spec_ids(output: dict) -> set:
    items = output.get("manual_resolution_items") or []
    return {item.get("spec_id", "") for item in items if isinstance(item, dict)}


def analyze_run(run_dir: Path, scenario: dict) -> dict:
    """Returns {'valid': bool, 'captured': bool, 'notes': str}"""
    meta = load_json(run_dir / "run_meta.json")
    if not meta:
        return {"valid": False, "captured": False, "notes": "no run_meta"}

    check = scenario["capture_check"]
    targets = set(scenario.get("target_spec_ids", []))

    if check == "false_positive_rate":
        # For default: count any manual_resolution_items raised
        completed = meta.get("completed_stages", [])
        valid = bool(completed)
        ambig_out = load_json(run_dir / "ambiguity_output.json")
        test_out = load_json(run_dir / "testability_output.json")
        ambig_ids = get_manual_res_spec_ids(ambig_out)
        test_ids = get_manual_res_spec_ids(test_out)
        all_flags = ambig_ids | test_ids
        # Also check decomp
        decomp = load_json(run_dir / "decomposition_flags.json")
        split_ids = {s for entry in (decomp.get("split_candidates") or []) for s in entry.get("spec_ids", [])}
        merge_ids = {s for entry in (decomp.get("merge_candidates") or []) for s in entry.get("spec_ids", [])}
        notes = f"ambig={sorted(ambig_ids)}, test={sorted(test_ids)}, split={sorted(split_ids)}, merge={sorted(merge_ids)}"
        return {"valid": valid, "captured": False, "flags": all_flags | split_ids | merge_ids, "notes": notes}

    if check == "decomposition_split":
        decomp = load_json(run_dir / "decomposition_flags.json")
        if decomp.get("skipped"):
            return {"valid": False, "captured": False, "notes": "decomp skipped"}
        split_candidates = decomp.get("split_candidates") or []
        split_spec_ids = {s for entry in split_candidates for s in entry.get("spec_ids", [])}
        captured = bool(targets & split_spec_ids)
        valid = True
        return {"valid": valid, "captured": captured, "notes": f"split_ids={sorted(split_spec_ids)}"}

    if check == "decomposition_merge":
        decomp = load_json(run_dir / "decomposition_flags.json")
        if decomp.get("skipped"):
            return {"valid": False, "captured": False, "notes": "decomp skipped"}
        merge_candidates = decomp.get("merge_candidates") or []
        # Check if targets appear in the SAME merge candidate entry
        captured = False
        for entry in merge_candidates:
            ids_in_entry = set(entry.get("spec_ids", []))
            if targets.issubset(ids_in_entry):
                captured = True
                break
        all_merge_ids = {s for e in merge_candidates for s in e.get("spec_ids", [])}
        valid = True
        return {"valid": valid, "captured": captured, "notes": f"merge_ids={sorted(all_merge_ids)}"}

    if check == "ambiguity":
        ambig_out = load_json(run_dir / "ambiguity_output.json")
        flagged = get_manual_res_spec_ids(ambig_out)
        captured = bool(targets & flagged)
        valid = bool(meta.get("completed_stages"))
        return {"valid": valid, "captured": captured, "notes": f"ambig_flagged={sorted(flagged)}"}

    if check == "ambiguity_any":
        ambig_out = load_json(run_dir / "ambiguity_output.json")
        flagged = get_manual_res_spec_ids(ambig_out)
        captured = bool(targets & flagged)
        valid = bool(meta.get("completed_stages"))
        return {"valid": valid, "captured": captured, "notes": f"ambig_flagged={sorted(flagged)}"}

    if check == "testability":
        test_out = load_json(run_dir / "testability_output.json")
        flagged = get_manual_res_spec_ids(test_out)
        captured = bool(targets & flagged)
        valid = bool(meta.get("completed_stages"))
        return {"valid": valid, "captured": captured, "notes": f"test_flagged={sorted(flagged)}"}

    if check == "both":
        ambig_out = load_json(run_dir / "ambiguity_output.json")
        test_out = load_json(run_dir / "testability_output.json")
        ambig_flagged = get_manual_res_spec_ids(ambig_out)
        test_flagged = get_manual_res_spec_ids(test_out)
        captured = bool(targets & ambig_flagged) and bool(targets & test_flagged)
        valid = bool(meta.get("completed_stages"))
        return {
            "valid": valid, "captured": captured,
            "notes": f"ambig={sorted(ambig_flagged)}, test={sorted(test_flagged)}"
        }

    if check == "both_any":
        ambig_out = load_json(run_dir / "ambiguity_output.json")
        test_out = load_json(run_dir / "testability_output.json")
        ambig_flagged = get_manual_res_spec_ids(ambig_out)
        test_flagged = get_manual_res_spec_ids(test_out)
        ambig_captured = bool(targets & ambig_flagged)
        test_captured = bool(targets & test_flagged)
        captured = ambig_captured and test_captured
        valid = bool(meta.get("completed_stages"))
        return {
            "valid": valid, "captured": captured,
            "ambig_captured": ambig_captured,
            "test_captured": test_captured,
            "notes": f"ambig={sorted(ambig_flagged)}, test={sorted(test_flagged)}"
        }

    return {"valid": False, "captured": False, "notes": f"unknown check: {check}"}


def analyze_scenario(name: str, scenario: dict) -> dict:
    runs_dir = scenario["runs_dir"]
    if not runs_dir.exists():
        return {"scenario": name, "total": 0, "valid": 0, "captured": 0, "rate": "N/A", "runs": []}

    run_dirs = sorted([d for d in runs_dir.iterdir() if d.is_dir()])
    results = []
    for run_dir in run_dirs:
        r = analyze_run(run_dir, scenario)
        r["run_id"] = run_dir.name
        results.append(r)

    valid_runs = [r for r in results if r["valid"]]
    captured_runs = [r for r in valid_runs if r["captured"]]
    total = len(run_dirs)
    valid = len(valid_runs)
    captured = len(captured_runs)
    rate = f"{captured}/{valid} ({100*captured//valid if valid else 0}%)" if valid else "0/0"
    return {
        "scenario": name,
        "family": scenario["expected_family"],
        "total_runs": total,
        "valid_runs": valid,
        "captured": captured,
        "rate": rate,
        "runs": results,
    }


def main():
    rows = []
    for name, scenario in SCENARIOS.items():
        result = analyze_scenario(name, scenario)
        rows.append(result)
        # Print per-run detail for debugging
        print(f"\n{'='*60}")
        print(f"Scenario: {name} | Family: {result['family']}")
        print(f"Runs: {result['total_runs']} total, {result['valid_runs']} valid, {result['captured']} captured | Rate: {result['rate']}")
        for r in result["runs"]:
            status = "CAPTURED" if r.get("captured") else ("VALID" if r.get("valid") else "INVALID")
            print(f"  [{status}] {r.get('run_id','?')} — {r.get('notes','')}")

    print("\n\n" + "="*80)
    print("SUMMARY TABLE — Successful Capture Rate")
    print("="*80)
    print(f"{'Scenario':<10} {'Expected Family':<25} {'Valid Runs':<12} {'Captured':<10} {'Rate':<12} {'Notes'}")
    print("-"*100)

    for result in rows:
        name = result["scenario"]
        family = result["family"]
        valid = result["valid_runs"]
        captured = result["captured"]
        rate = result["rate"]

        # Build notable observations
        observations = []
        if name == "RB12":
            test_captures = sum(1 for r in result["runs"] if r.get("valid") and r.get("test_captured"))
            ambig_captures = sum(1 for r in result["runs"] if r.get("valid") and r.get("ambig_captured"))
            if test_captures != ambig_captures:
                observations.append(f"ambig_only={ambig_captures-min(ambig_captures,test_captures)}")
        if name == "default":
            # Count runs with any flags
            flagged_runs = sum(1 for r in result["runs"] if r.get("flags"))
            observations.append(f"{flagged_runs}/{valid} runs had flags (false positives)")
            rate = f"{flagged_runs}/{valid} FP"

        obs = "; ".join(observations) if observations else ""
        print(f"{name:<10} {family:<25} {valid:<12} {captured:<10} {rate:<12} {obs}")


if __name__ == "__main__":
    main()
