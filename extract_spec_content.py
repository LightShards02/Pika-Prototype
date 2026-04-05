"""Extract requirement and acceptance_criteria for target spec IDs from each scenario DESIGN-SPEC."""
import csv
from pathlib import Path

BASE = Path("dataset/specimen/scenarios/refine-blockers")

TARGETS = {
    "RB01": ["A2016"],
    "RB02": ["A2041", "A2042"],
    "RB03": ["A2028"],
    "RB04": ["A2029", "A2040"],
    "RB05": ["A2028"],
    "RB06": ["A2038"],
    "RB07": ["A2042"],
    "RB08": ["A2016"],
    "RB09": ["A2024"],
    "RB10": ["A2036"],
    "RB11": ["A2016"],
    "RB12": ["A2028", "A2050"],
}

for rb, target_ids in TARGETS.items():
    spec_path = BASE / rb / "state/DESIGN-SPEC.csv"
    print(f"\n{'='*60}")
    print(f"Scenario: {rb} | Targets: {target_ids}")
    with open(spec_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["spec_id"] in target_ids:
                print(f"  spec_id: {row['spec_id']}")
                print(f"  requirement: {row['requirement']}")
                print(f"  acceptance_criteria: {row['acceptance_criteria']}")
                print()
