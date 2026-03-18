# CSV Contracts

**Single source of truth:** This document is parsed at runtime by `core/contracts.py` for preflight validation. Required columns are read from the tables below. Do not duplicate these definitions in code.

## Scope
- Supported input formats: `.csv`, `.xlsx`
- Unsupported in this contract: Google Sheets
- Rule: existing user columns are never removed or reordered
- Rule: missing contract columns are appended at the end in the exact order defined below

## Pre-formatted Input Columns
- Inputs to the format command (Raw SADS, design spec) may contain arbitrary user-defined columns.
- All original columns are preserved in output; only missing contract columns are appended.
- For SRS/SADS hierarchical format, columns such as SRS ID, SRS, SADS ID, SADS, NOTES, MDR COMMENTS (or aliases) are accommodated.

## CLI Command Surface
- `agent plan` — Project Designer (Phase 0.a)
- `agent format` — SADS Formatter (Phase 0.b; deterministic only)
- `agent review` — Design Reviewer
- `agent map` — SADS Mapper (Phase 2)
- `agent implement` — Implementer (Phase 1)
- `agent resolve_plan` — Resolution Organizer (Phase 2/4)

## Design Spec (SADS) Table Contract

| Column | Required | Added if Missing | Meaning |
|---|---|---|---|
| spec_id | Yes | Yes | Stable deterministic spec identifier (one letter + number, for example `A1001`). |
| module_tag | Yes | Yes | Partition key for implement command; groups specs by module. Manually added. Implement does not use subunit. |
| subunit | No | Yes | User-provided grouping key for map command. Specs with the same subunit are sent to the LLM together. Required for map; each row must have a non-empty value. |
| title | Yes | No | Human-readable requirement title. |
| requirement | Yes | No | Core requirement statement to be implemented/indexed. |
| acceptance_criteria | No | No | Concrete acceptance criteria for verification. |
| implementation_status | No | No | User workflow status for the spec row. For implement workset selection: boolean (done or not done). |
| mapped_code_symbols | No | Yes | Comma-delimited mapped symbols in `path::symbol_name` format (path relative to codebase root). Legacy entries may contain symbol_name only. |
| mapped_confidence | No | Yes | Comma-delimited confidence scores (0-1) per symbol, same order as mapped_code_symbols. |
| mapped_consistency_score | No | Yes | Comma-delimited consistency scores (0-1) per symbol, same order as mapped_code_symbols. |
| mapped_problems | No | Yes | Semicolon-delimited problem notes per symbol (reason for low confidence/inconsistency); same order as mapped_code_symbols. |
| map_status | Yes | Yes | Index result state (`mapped`, `partial`, `unmapped`, `blocked`). |
| map_assumptions | No | Yes | Assumptions made to produce the mapping. Nullable. |
| mapped_at | No | Yes | Timestamp of latest indexing run: agent `created_at` when provided, else invocation time. Format: `YYYY-MM-DDTHH:MM:SS UTC+X`. |
| map_run_id | No | Yes | Run ID of the latest map invocation. |

## Implementation Issue Tracking Table Contract

| Column | Required | Added if Missing | Meaning |
|---|---|---|---|
| issue_id | Yes | Yes | Stable deterministic issue identifier (two letters + number, for example `IS1001`). |
| summary | Yes | No | Short issue title. |
| description | Yes | No | Full issue details and expected behavior. |
| severity | No | No | User-defined severity (for example: blocker/high/medium/low). |
| status | No | No | User workflow status for issue processing. |
| author | Yes | Yes | Source of row. Default is `source` for original records; set to agent ID when an agent updates the row. |
| mapped_spec_ids | No | Yes | Comma-delimited spec IDs linked to this issue. |
| issue_notes | No | Yes | Mapping or resolution notes for the issue row. |
| follow_up_uncertainties | Yes | Yes | Required post-resolution uncertainty statement. Must be explicit; if none, set `No follow_up_uncertainties`. |
| last_resolved_at | No | Yes | ISO-8601 UTC timestamp of latest resolution run. |

## ID Generation Rule (Stable and Deterministic)

1. ID format:
   - Spec IDs: `^[A-Za-z][0-9]+$` (one letter followed by digits)
   - Issue IDs: `^[A-Za-z]{2}[0-9]+$` (two letters followed by digits)
2. Numeric suffixes must be unique within each ID type only.
   - Spec IDs: no duplicate numeric suffix among spec IDs.
   - Issue IDs: no duplicate numeric suffix among issue IDs.
   - Cross-type reuse is allowed. Example: `A1001` and `IS1001` can both exist.
3. If a row already has a valid ID, it is preserved as-is.
4. For rows missing IDs, deterministic assignment uses a persisted registry:
   - Registry path: `out/state/id_registry.json`
   - Registry key: row fingerprint from canonicalized stable fields:
     - Spec: `title + requirement + acceptance_criteria`
     - Issue: `summary + description`
   - If fingerprint exists in registry, reuse the existing ID.
   - Otherwise allocate next sequence number from current max and persist.
5. This ensures reruns do not change prior IDs even if row order changes.

## SRS/SADS Hierarchical Format (Sample-Spec)

When Raw SADS uses a hierarchical SRS/SADS structure (e.g. Sample-Spec.xlsx):

1. **Columns**: SRS ID | SRS | UNIT | SADS ID | SADS | NOTES | MDR COMMENTS (or aliases)
2. **Layout**: SRS rows have SRS ID + SRS text; child SADS rows have empty SRS ID/SRS (inherited from previous row)
3. **ID formats**: SRS ID = `R{number}` (e.g. R627); SADS ID = `D{number}.{subnumber}` (e.g. D627.01)
4. **Relationship**: The numeric part of SRS ID maps one-to-many to SADS IDs (e.g. R627 → D627.01, D627.02)
5. **Format command**: Forward-fills SRS ID/SRS, filters to rows with valid SADS ID, assigns deterministic spec_ids, derives title/requirement from SADS ID/SADS when missing

### SADS ID Mapping Artifact

When SADS format is detected, the format command writes `out/state/sads_id_mapping.json` (or `commands.format.sads_id_mapping_path`):

```json
{
  "by_sads_id": {
    "D627.01": { "spec_id": "A1", "srs_id": "R627" },
    "D627.02": { "spec_id": "A2", "srs_id": "R627" }
  },
  "by_srs_id": {
    "R627": ["A1", "A2"]
  }
}
```

- `by_sads_id`: maps each SADS ID to its new spec_id and parent SRS ID
- `by_srs_id`: maps each SRS ID to the list of spec_ids for its SADS children

## Missing Column Addition Rule

1. Read source table exactly as provided.
2. Preserve all original columns in original order.
3. For each contract column marked "Added if Missing":
   - If absent, append column at end (never insert between existing columns).
   - Initialize values with empty string unless command-specific defaults exist.
   - Exception defaults:
     - `author` defaults to `source` for pre-existing source rows.
     - `follow_up_uncertainties` defaults to `No follow_up_uncertainties` after issue resolution when none are identified.
4. Write output table to configured output path only; never overwrite source without backup copy.
5. Backup is created before any write operation.

## author Column Rules

1. `author` is required in issue tracking output.
2. For rows coming from the original input document, `author` is `source`.
3. If an agent updates a row, set `author` to that agent's ID (for example `agent-index-v1`).
4. If multiple agents update in sequence, `author` stores the last updater; detailed audit trail should be captured in logs/run artifacts.

## Column Definitions For Agents

1. Agent prompts should include column definition context for each relevant CSV table.
2. Minimum required definitions:
   - Name
   - Meaning
   - Expected type/format
   - Required/optional
3. The authoritative source for these definitions is this contract document.

## Centralized Manual Resolution File

1. Any command that produces manual-only items must append them to `out/agent_runs/manual_resolution.csv`.
2. Minimum columns in centralized file:
   - `command`
   - `entity_type`
   - `entity_id`
   - `reason`
   - `details`
   - `created_at`
3. The file is append-only and deterministic by run order.
