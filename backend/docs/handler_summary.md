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
| **Input** | CLI `--design-spec` or `commands.format.inputs.design_spec_path` → Raw SADS CSV/XLSX content (relative to project root or absolute). No further fallback. |
| **Preprocessing** | 1. If SADS format (SADS ID column + D\\d+\\.\\d+ rows): flatten (forward-fill SRS ID/SRS, filter to SADS rows), derive title/requirement from SADS ID/SADS<br>2. Keyword replacement (many-to-one: replacement → [keywords], or legacy keyword → replacement)<br>3. Append missing contract columns per csv_contracts<br>4. Assign deterministic spec_ids via ID registry (SADS fingerprint or standard) |
| **Agent output** | Optional `design_doc_enricher` (when `commands.format.enrichment.enabled: true`): fills `module_role` only (one per unique `module_tag`). **Does NOT write `acceptance_criteria` or `evidence_type`.** |
| **Schema** | `schemas.enrich_output` → `design_doc_enrich_output.schema.json` (modules[] only) |
| **Translation** | Writes Draft Formatted SADS to `commands.format.outputs.design_spec_path`; backs up existing file to `outputs.backups_dir/format/` if `copy_before_write`; copies to `project.state.design_spec_path` after writing; when SADS format, writes ID mapping to `out/state/sads_id_mapping.json` then copies to `project.state.sads_id_mapping_path` |
| **Output** | Draft Formatted SADS (CSV) with `module_role` populated; `acceptance_criteria` and `evidence_type` remain empty — filled by `refine`. |

**Skipped when:** No input path via CLI or config, or file missing.

**Pipeline ordering note:** `acceptance_criteria` and `evidence_type` are populated by the `spec_testability_enricher` agent during the `refine` stage. Run `pika agent refine` after `format` to get full SADS output. If `refine` is blocked by MR items (vague requirements), resolve them and re-run `pika agent refine --resume` to generate AC for the resolved specs.

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
| **Input** | CLI `--design-spec` or `commands.map.inputs.design_spec_path` or `project.state.design_spec_path` → Formatted SADS; `--codebase-dir` or `inputs.codebase_dir` → codebase path; `--project-context` → project context file (fallback: project root / `inputs.project_context_filename`); `--extra-prompt` → optional extra prompt .md file (fallback: project root / `inputs.extra_prompt_filename` when configured; when both omitted, no file looked for, extra section empty) |
| **Preprocessing** | Writes agent-view CSV to `outputs.agent_view_csv` (slim spec: spec_id, title, requirement, mapping columns only; no SRS/SADS lineage). Overwritten each run. Prompts use this slim content. |
| **Agent output** | `mappings` (spec_id → status, code_refs, assumptions); each code_ref has path, symbol_name, symbol_type, confidence, consistency_score, problems; or `manual_resolution_items` only (blocking) |
| **Schema** | `schemas.map_output` → `index_output.schema.json` |
| **Translation** | Updates mapping columns in Formatted SADS: `mapped_code_symbols`, `map_status`, `map_assumptions` (from mapping.assumptions, nullable), `mapped_at` |
| **Output** | Formatted SADS with mapping columns updated |

**Output paths:** `run_summary` → `out/agent_runs/map/run_summary.jsonl`; `manual_resolution` → `out/agent_runs/map/manual_resolution.csv`; per-subunit outputs → `out/intermediate/map/{run_id}/map_*.json`.

**Skipped when:** No design spec path via CLI or config, or file missing.

---

## implement — Implementer (Phase 1)

| Aspect | Details |
|-------|---------|
| **Input** | CLI `--design-spec` or `commands.implement.inputs.design_spec_path` or `project.state.design_spec_path` → Formatted SADS; `--project-context` → project context file (fallback: project root / `inputs.project_context_filename`) |
| **Preprocessing** | Deterministic workset selection, module catalog build, unified planner run (with semantic retry), unified plan validation, batch planning, batch-plan validation, and brief generation |
| **Agent output** | Unified planner output (`unified_plan.json` with `module_plans`, `spec_dependencies`, `shared_contracts`) and per-batch spec-keyed implement outputs (`{spec_id}.diffs`, mappings); or `manual_resolution_items` only (blocking) |
| **Schema** | `schemas/agent_outputs/implement_unified_planner_output.schema.json`, `schemas/agent_outputs/implement_output.schema.json` |
| **Translation** | Applies validated diffs to code; updates `mapped_code_symbols`/`mapped_test_cases`; writes trace and verification artifacts |
| **Output** | Code changes; Design Spec mapping updates; test spec updates; run artifacts (`unified_plan`, `batch_plan`, `batch_plan_validation`, `batch_briefs`) |

**Output paths:** Run workspace → `out/agent_runs/implement/{run_id}/`; artifacts → `out/agent_artifacts/implement/{run_id}/`; test spec (optional) → `out/state/test_spec.csv`.

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
