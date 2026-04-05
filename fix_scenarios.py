"""Apply targeted mutations to RB10 and RB12 DESIGN-SPEC.csv files."""
import csv
import io
from pathlib import Path

BASE = Path("dataset/specimen/scenarios/refine-blockers")


def rewrite_spec(path: Path, mutations: dict[str, dict[str, str]]) -> None:
    """Rewrite rows in a DESIGN-SPEC.csv, applying field-level mutations keyed by spec_id."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        rows = list(reader)

    for row in rows:
        sid = row["spec_id"]
        if sid in mutations:
            for field, value in mutations[sid].items():
                row[field] = value

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers, lineterminator="\n", quoting=csv.QUOTE_ALL)
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8")
    print(f"  Written: {path}")


# ── RB10: Strengthen A2036 acceptance_criteria ─────────────────────────────
# The appendix collapses all error codes to one ACC_GENERAL_ERROR.
# The new AC explicitly requires a DISTINCT code per failure type,
# making the single-code appendix clearly untestable.
print("Fixing RB10 — A2036 acceptance_criteria")
rewrite_spec(
    BASE / "RB10/state/DESIGN-SPEC.csv",
    {
        "A2036": {
            "acceptance_criteria": (
                "When a contract rejection, a match rejection, and a replay rejection are each "
                "evaluated, the system returns a distinct canonical error code from "
                "`appendix_error_codes.csv` for each failure type, where the code for a "
                "contract rejection differs from the code for a match rejection and from the "
                "code for a replay rejection."
            )
        }
    },
)

# ── RB12: Fix A2028 requirement + A2050 requirement ────────────────────────
# A2028: was hardcoded >= 0.95 (too concrete — not vague).
#        New: explicitly references appendix_dto_definitions.csv for the field type,
#        tying the numeric comparison to the DTO whose match_score type is conflicted
#        (decimal in one entry, enum low|medium|high in the "Variant" entry).
# A2050: add explicit appendix_dto_definitions.csv reference so agent cross-checks
#        and finds the two conflicting "Reconciliation Decision DTO" entries.
print("Fixing RB12 — A2028 requirement and A2050 requirement")
rewrite_spec(
    BASE / "RB12/state/DESIGN-SPEC.csv",
    {
        "A2028": {
            "requirement": (
                "When the returned match_score as defined in appendix_dto_definitions.csv is "
                "greater than or equal to 0.95, the CORE module shall classify the candidate "
                "pair as accepted."
            )
        },
        "A2050": {
            "requirement": (
                "When CORE returns a reconciliation outcome, the SHARED module shall define the "
                "Reconciliation Decision DTO fields as specified in appendix_dto_definitions.csv."
            )
        },
    },
)

print("\nDone. Verifying mutations:")
for rb, targets in [("RB10", ["A2036"]), ("RB12", ["A2028", "A2050"])]:
    print(f"\n  {rb}:")
    with open(BASE / rb / "state/DESIGN-SPEC.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["spec_id"] in targets:
                print(f"    {row['spec_id']} req: {row['requirement'][:120]}")
                print(f"    {row['spec_id']} ac:  {row['acceptance_criteria'][:120]}")
