"""Compare baseline vs mutated spec rows and read appendix mutations for failing scenarios."""
import csv
from pathlib import Path

BASE = Path("dataset/specimen")
SCENARIOS_BASE = BASE / "scenarios/refine-blockers"

def read_spec_row(spec_path, spec_id):
    with open(spec_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["spec_id"] == spec_id:
                return row
    return None

def read_csv_rows(path, limit=10):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows[:limit]

baseline_spec = BASE / "state/DESIGN-SPEC.csv"

# RB01 - split candidate
print("=" * 70)
print("RB01: SPLIT CANDIDATE — A2016")
print("=" * 70)
baseline = read_spec_row(baseline_spec, "A2016")
mutated = read_spec_row(SCENARIOS_BASE / "RB01/state/DESIGN-SPEC.csv", "A2016")
print("BASELINE req:", baseline["requirement"])
print("MUTATED  req:", mutated["requirement"])
print()
print("BASELINE ac :", baseline["acceptance_criteria"])
print("MUTATED  ac :", mutated["acceptance_criteria"])

# RB05 - ambiguity: duplicate config value conflict
print("\n" + "=" * 70)
print("RB05: AMBIGUITY — A2028 + appendix_config_proposals.csv mutation")
print("=" * 70)
baseline = read_spec_row(baseline_spec, "A2028")
mutated = read_spec_row(SCENARIOS_BASE / "RB05/state/DESIGN-SPEC.csv", "A2028")
print("BASELINE req:", baseline["requirement"])
print("MUTATED  req:", mutated["requirement"])
print()
print("BASELINE ac :", baseline["acceptance_criteria"])
print("MUTATED  ac :", mutated["acceptance_criteria"])
print()
print("MUTATED appendix_config_proposals.csv (all rows):")
for row in read_csv_rows(SCENARIOS_BASE / "RB05/appendix_config_proposals.csv", limit=20):
    print(" ", dict(row))

# RB06 - ambiguity: placeholder source contract fields
print("\n" + "=" * 70)
print("RB06: AMBIGUITY — A2038 + appendix_source_contracts.csv mutation")
print("=" * 70)
baseline = read_spec_row(baseline_spec, "A2038")
mutated = read_spec_row(SCENARIOS_BASE / "RB06/state/DESIGN-SPEC.csv", "A2038")
print("BASELINE req:", baseline["requirement"])
print("MUTATED  req:", mutated["requirement"])
print()
print("BASELINE ac :", baseline["acceptance_criteria"])
print("MUTATED  ac :", mutated["acceptance_criteria"])
print()
print("MUTATED appendix_source_contracts.csv (first 10 rows):")
for row in read_csv_rows(SCENARIOS_BASE / "RB06/appendix_source_contracts.csv", limit=15):
    print(" ", dict(row))

# RB10 - testability: appendix error codes collapsed
print("\n" + "=" * 70)
print("RB10: TESTABILITY — A2036 + appendix_error_codes.csv mutation")
print("=" * 70)
baseline = read_spec_row(baseline_spec, "A2036")
mutated = read_spec_row(SCENARIOS_BASE / "RB10/state/DESIGN-SPEC.csv", "A2036")
print("BASELINE req:", baseline["requirement"])
print("MUTATED  req:", mutated["requirement"])
print()
print("BASELINE ac :", baseline["acceptance_criteria"])
print("MUTATED  ac :", mutated["acceptance_criteria"])
print()
print("BASELINE appendix_error_codes.csv (first 8 rows):")
for row in read_csv_rows(BASE / "appendix_error_codes.csv", limit=8):
    print(" ", dict(row))
print()
print("MUTATED appendix_error_codes.csv (first 8 rows):")
for row in read_csv_rows(SCENARIOS_BASE / "RB10/appendix_error_codes.csv", limit=8):
    print(" ", dict(row))

# RB12 - ambiguity+testability: numeric threshold + DTO appendix conflict
print("\n" + "=" * 70)
print("RB12: AMBIGUITY+TESTABILITY — A2028, A2050 + appendix_dto_definitions.csv mutation")
print("=" * 70)
for sid in ["A2028", "A2050"]:
    baseline = read_spec_row(baseline_spec, sid)
    mutated = read_spec_row(SCENARIOS_BASE / "RB12/state/DESIGN-SPEC.csv", sid)
    print(f"--- {sid} ---")
    print("BASELINE req:", baseline["requirement"])
    print("MUTATED  req:", mutated["requirement"])
    print()
    print("BASELINE ac :", baseline["acceptance_criteria"])
    print("MUTATED  ac :", mutated["acceptance_criteria"])
    print()
print("BASELINE appendix_dto_definitions.csv (first 6 rows):")
for row in read_csv_rows(BASE / "appendix_dto_definitions.csv", limit=6):
    print(" ", dict(row))
print()
print("MUTATED appendix_dto_definitions.csv (first 10 rows):")
for row in read_csv_rows(SCENARIOS_BASE / "RB12/appendix_dto_definitions.csv", limit=10):
    print(" ", dict(row))
