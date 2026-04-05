#!/usr/bin/env python
"""Run pika agent refine for RB12 scenario and collect results."""
import sys
import os
import subprocess
import json
import time

# Set up path
BACKEND_DIR = "C:/Users/night/Work/Echelondx/Pika/backend"
RB12_DIR = "C:/Users/night/Work/Echelondx/Pika/dataset/specimen/scenarios/refine-blockers/RB12"
REFINE_RUNS_DIR = os.path.join(RB12_DIR, "out", "agent_runs", "refine")
CONFIG_PATH = os.path.join(RB12_DIR, "config.yaml")

sys.path.insert(0, BACKEND_DIR)


def get_latest_run_dir():
    """Get the most recently created run directory (sort descending, take first)."""
    try:
        dirs = sorted(os.listdir(REFINE_RUNS_DIR), reverse=True)
        if dirs:
            return os.path.join(REFINE_RUNS_DIR, dirs[0])
    except FileNotFoundError:
        return None
    return None


def read_json(path):
    """Read and parse JSON file, return None if not found."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def extract_spec_ids(output_data):
    """Extract spec_ids from manual_resolution_items."""
    if not output_data:
        return []
    items = output_data.get("manual_resolution_items", [])
    ids = []
    for item in items:
        sid = item.get("spec_id")
        if sid:
            ids.append(sid)
    return ids


def run_once(run_number):
    """Execute one pika agent refine run and return the result dict."""
    print(f"\n{'='*60}", flush=True)
    print(f"RUN {run_number}/10 starting...", flush=True)

    # Record existing dirs before run
    try:
        before_dirs = set(os.listdir(REFINE_RUNS_DIR))
    except FileNotFoundError:
        before_dirs = set()

    # Execute the command
    python_exe = "C:/Users/night/miniconda3/envs/Local/python.exe"
    cmd = [
        python_exe,
        os.path.join(BACKEND_DIR, "cli.py"),
        "agent", "refine",
        "--config", CONFIG_PATH,
        "--project-root", RB12_DIR
    ]

    env = os.environ.copy()
    env["PYTHONPATH"] = BACKEND_DIR
    env["PYTHONIOENCODING"] = "utf-8"

    print(f"  Executing command...", flush=True)
    start = time.time()
    result = subprocess.run(
        cmd,
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )
    elapsed = time.time() - start
    exit_code = result.returncode

    print(f"  Exit code: {exit_code}, elapsed: {elapsed:.1f}s", flush=True)
    if result.stderr:
        # Print last few lines of stderr for context
        stderr_lines = result.stderr.strip().split("\n")
        for line in stderr_lines[-5:]:
            print(f"  STDERR: {line}", flush=True)

    # Check for 429/network errors in output
    combined_output = (result.stdout or "") + (result.stderr or "")
    if "429" in combined_output or "rate limit" in combined_output.lower():
        print("  *** 429 / rate limit detected! ***", flush=True)
        return {
            "run_number": run_number,
            "run_id": None,
            "exit_code": exit_code,
            "status": "RATE_LIMITED",
            "ambiguity_spec_ids": [],
            "testability_spec_ids": [],
            "captured": False,
            "error": "429 or rate limit"
        }

    if "network error" in combined_output.lower() or "connection" in combined_output.lower() and exit_code != 0:
        # Check specifically for network errors
        pass

    # Find the new run dir
    try:
        after_dirs = set(os.listdir(REFINE_RUNS_DIR))
    except FileNotFoundError:
        after_dirs = set()

    new_dirs = after_dirs - before_dirs
    if new_dirs:
        run_dir_name = sorted(new_dirs, reverse=True)[0]
    else:
        # Fallback: just take the latest
        all_dirs = sorted(after_dirs, reverse=True)
        run_dir_name = all_dirs[0] if all_dirs else None

    if not run_dir_name:
        print("  WARNING: No run directory found!", flush=True)
        return {
            "run_number": run_number,
            "run_id": None,
            "exit_code": exit_code,
            "status": "NO_RUN_DIR",
            "ambiguity_spec_ids": [],
            "testability_spec_ids": [],
            "captured": False,
            "error": "no run directory created"
        }

    run_dir = os.path.join(REFINE_RUNS_DIR, run_dir_name)
    print(f"  Run dir: {run_dir_name}", flush=True)

    # Read run_meta.json
    run_meta = read_json(os.path.join(run_dir, "run_meta.json"))
    status = run_meta.get("status") if run_meta else "UNKNOWN"

    # Read ambiguity_output.json
    ambiguity_data = read_json(os.path.join(run_dir, "ambiguity_output.json"))
    ambiguity_spec_ids = extract_spec_ids(ambiguity_data)

    # Read testability_output.json (may not exist if run failed)
    testability_data = read_json(os.path.join(run_dir, "testability_output.json"))
    testability_spec_ids = extract_spec_ids(testability_data)

    print(f"  Status: {status}", flush=True)
    print(f"  Ambiguity spec_ids: {ambiguity_spec_ids}", flush=True)
    print(f"  Testability spec_ids: {testability_spec_ids}", flush=True)

    # Capture definition: ambiguity flagged A2028 or A2050 AND testability flagged A2028 or A2050
    target = {"A2028", "A2050"}
    ambiguity_hit = bool(target & set(ambiguity_spec_ids))
    testability_hit = bool(target & set(testability_spec_ids))
    captured = ambiguity_hit and testability_hit

    print(f"  Captured: {captured}", flush=True)

    return {
        "run_number": run_number,
        "run_id": run_dir_name,
        "exit_code": exit_code,
        "status": status,
        "ambiguity_spec_ids": ambiguity_spec_ids,
        "testability_spec_ids": testability_spec_ids,
        "captured": captured
    }


def main():
    results = []

    for i in range(1, 11):
        record = run_once(i)
        results.append(record)

        # Check for stop condition
        if record.get("error") in ("429 or rate limit",) or "RATE_LIMITED" in record.get("status", ""):
            print(f"\nStopping due to rate limit at run {i}.", flush=True)
            break

        # Small pause between runs
        if i < 10:
            time.sleep(2)

    print("\n" + "="*60, flush=True)
    print("FINAL RESULTS:", flush=True)
    print(json.dumps(results, indent=2), flush=True)

    # Write results to file
    output_path = "C:/Users/night/Work/Echelondx/Pika/rb12_run_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written to: {output_path}", flush=True)

    return results


if __name__ == "__main__":
    main()
