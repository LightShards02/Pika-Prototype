# Handler Input/Translation/Output Summary

This document summarizes the input, translation, and output mechanism of each command handler implemented in Phase 3.e.

---

## Lifecycle Template (All Commands)

1. **Create/validate run workspace** — Safety preflight checks (cli, before dispatch)
2. **Load config, prompts, context** — Done in cli, passed to handler
3. **Load required inputs** — Handler-specific
4. **(Optional) Deterministic preprocessing** — Handler-specific
5. **Invoke agent** — Stub (LLM integration deferred)
6. **Validate output schema** — Agent commands only
7. **Manual-resolution loop** — If `manual_resolution_items` non-empty (blocking)
8. **Translate output** — Dry-run aware; apply changes to docs/code

---

## plan — Project Designer (Phase 0.a)

| Aspect | Details |
|-------|---------|
| **Input** | CLI `[SRS]` or `inputs.srs_path` → SRS; `--project-context` → project context file (fallback: project root / `inputs.project_context_filename`) |
| **Preprocessing** | None |
| **Agent output** | **proposed_sads_outline_path** (path to SADS CSV in agent_artifacts_dir), milestones; or `manual_resolution_items` only (blocking) |
| **Schema** | `schemas.plan_output` → `plan_output.schema.json` |
| **Translation** | Writes `plan_milestones.json`, `plan_proposed_sads.csv` to `outputs.agent_runs_dir` |
| **Output** | SADS-compatible CSV; milestones JSON |

**Output is directly compatible with Design Spec (SADS) columns** per csv_contracts.md. Detailed design (unit logic, feature logic, edge cases, error handling, class/helper descriptions) is **embedded in requirement and acceptance_criteria text**, not as separate fields.

**Skipped when:** No SRS path via CLI or config, or file missing.

---

## format — SADS Formatter (Phase 0.b; deterministic; no LLM)

| Aspect | Details |
|-------|---------|
| **Input** | CLI `--input` or `inputs.raw_sads_path` / `inputs.design_spec_path` → Raw SADS CSV/XLSX content (relative to project root or absolute) |
| **Preprocessing** | 1. If SADS format (SADS ID column + D\\d+\\.\\d+ rows): flatten (forward-fill SRS ID/SRS, filter to SADS rows), derive title/requirement from SADS ID/SADS<br>2. Keyword replacement (many-to-one: replacement → [keywords], or legacy keyword → replacement)<br>3. Append missing contract columns per csv_contracts<br>4. Assign deterministic spec_ids via ID registry (SADS fingerprint or standard) |
| **Agent output** | None (no agent) |
| **Schema** | None |
| **Translation** | Writes Draft Formatted SADS to `outputs.normalized_dir/formatted_{original_stem}.csv`; backs up existing file to `outputs.backups_dir/format/` if `copy_before_write`; when SADS format, writes ID mapping to `out/state/sads_id_mapping.json` (or `commands.format.sads_id_mapping_path`) |
| **Output** | Draft Formatted SADS (CSV); format logs (source_path, input_rows, sads_format, keyword_replacements, columns_appended, ids_assigned, ids_preserved); SADS ID mapping (by_sads_id, by_srs_id) when SADS format |

**Skipped when:** No input path via CLI or config, or file missing.

---

## review — Design Reviewer (Design gate)

| Aspect | Details |
|-------|---------|
| **Input** | CLI `--design-spec` and `--srs` (optional), or config → SRS + Draft Formatted SADS (paths relative to project root or absolute) |
| **Preprocessing** | None |
| **Agent output** | Design Issue records; or `manual_resolution_items` only (blocking) |
| **Schema** | `schemas.review_output` (optional; not in example config) |
| **Translation** | Updates Design Issue Tracker per contract; persists review artifacts |
| **Output** | Design Issue Tracker updates; review artifacts |

**Skipped when:** No design spec path via CLI or config, or file missing.

---

## map — SADS Mapper (Phase 2)

| Aspect | Details |
|-------|---------|
| **Input** | CLI `--design-spec` or `inputs.design_spec_path` → Formatted SADS (relative to project root or absolute); `--codebase-dir` or `inputs.codebase_dir` → codebase path; `--project-context` → project context file (fallback: project root / `inputs.project_context_filename`); `--extra-prompt` → optional extra prompt .md file (fallback: project root / `inputs.extra_prompt_filename` when configured; when both omitted, no file looked for, extra section empty) |
| **Preprocessing** | Writes agent-view CSV to `outputs.agent_view_csv` (slim spec: spec_id, title, requirement, mapping columns only; no SRS/SADS lineage). Overwritten each run. Prompts use this slim content. |
| **Agent output** | `mappings` (spec_id → status, code_refs, assumptions); each code_ref has path, symbol_name, symbol_type, confidence, consistency_score, problems; or `manual_resolution_items` only (blocking) |
| **Schema** | `schemas.map_output` → `index_output.schema.json` |
| **Translation** | Updates mapping columns in Formatted SADS: `mapped_code_symbols`, `index_status`, `assumptions` (from mapping.assumptions, nullable), `last_indexed_at` |
| **Output** | Formatted SADS with mapping columns updated |

**Skipped when:** No design spec path via CLI or config, or file missing.

---

## implement — Implementer (Phase 1)

| Aspect | Details |
|-------|---------|
| **Input** | CLI `--design-spec` or `inputs.design_spec_path` → Formatted SADS (relative to project root or absolute); `--project-context` → project context file (fallback: project root / `inputs.project_context_filename`) |
| **Preprocessing** | Writes agent-view CSV to `outputs.agent_view_csv` (slim spec: spec_id, title, requirement, mapping columns only; no SRS/SADS lineage). Overwritten each run. Prompts use this slim content. |
| **Agent output** | `diffs` (unified patches), `unclarities`; or `manual_resolution_items` only (blocking) |
| **Schema** | `schemas.implement_output` → `implement_output.schema.json` |
| **Translation** | Applies diffs to code; updates implementation-status columns in SADS/issue tracker |
| **Output** | Code changes; SADS/issue tracker updates |

**Skipped when:** No design spec path via CLI or config, or file missing.

---

## resolve_plan — Resolution Organizer (Phase 2/4)

| Aspect | Details |
|-------|---------|
| **Input** | CLI `--issue-tracking` and `--design-spec`, or config → Issue Tracker + Formatted SADS (paths relative to project root or absolute) |
| **Preprocessing** | None |
| **Agent output** | Map phase: `mappings` (issue_id → spec_ids, notes); Resolve phase: `diffs`, `follow_up_uncertainties`, `issue_notes`; or `manual_resolution_items` only (blocking) |
| **Schema** | `schemas.resolve_plan_map_output`, `schemas.resolve_plan_output` |
| **Translation** | Updates Issue Tracker: `mapped_spec_ids`, `issue_notes`, `follow_up_uncertainties`, `last_resolved_at`; persists resolution packets |
| **Output** | Issue Tracker planning columns; resolution packets |

**Skipped when:** No issue tracking path via CLI or config, or file missing.

---

## Status and Exit Codes

| Status | Meaning |
|--------|---------|
| `completed` | Lifecycle finished; translation applied (or skipped in dry-run) |
| `blocked` | Manual resolution required; items appended to `manual_resolution_file` |
| `skipped` | Required inputs missing; handler did not run |
| `failed` | Error during execution |

Exit codes: `0` (success), `4` (blocked), `5` (skipped), `3` (handler error).
