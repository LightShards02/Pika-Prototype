# CSV Contracts

## Scope
- Supported input formats: `.csv`, `.xlsx`
- Unsupported in this contract: Google Sheets
- Rule: existing user columns are never removed or reordered
- Rule: missing contract columns are appended at the end in the exact order defined below

## CLI Command Surface
- `agent load`
- `agent index`
- `agent implement`
- `agent issue`

## Design Spec Table Contract

| Column | Required | Added if Missing | Meaning |
|---|---|---|---|
| spec_id | Yes | Yes | Stable deterministic spec identifier (one letter + number, for example `A1001`). |
| title | Yes | No | Human-readable requirement title. |
| requirement | Yes | No | Core requirement statement to be implemented/indexed. |
| acceptance_criteria | No | No | Concrete acceptance criteria for verification. |
| status | No | No | User workflow status for the spec row. |
| mapped_code_symbols | No | Yes | Comma-delimited mapped class/function symbols from indexing. |
| index_status | Yes | Yes | Index result state (`mapped`, `partial`, `unmapped`, `blocked`). |
| index_notes | No | Yes | Agent/executor notes explaining index decisions. |
| last_indexed_at | No | Yes | ISO-8601 UTC timestamp of latest indexing run. |

## Issue Tracking Table Contract

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
