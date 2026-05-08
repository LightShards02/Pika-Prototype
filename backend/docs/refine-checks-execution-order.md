# Refine Command Checks In Execution Order

1. `[v0.0.0][deterministic]` **Normalize Refine Config** (`refine.config_normalization`): Parse and normalize refine configuration (enabled flag, prompt names, decomposition settings, thresholds).
   a. Read config from CLI flags and config files under `commands.refine`.
   b. Fill in defaults for missing values (`quality_auditor` and `spec_editor` prompt names; decomposition enabled/blocking flags).
   c. Clamp `similarity_threshold` and `variance_threshold` to `[0.0, 1.0]`.
   d. Produce one clean config object that every later step uses.
   e. Produces no file.
2. `[v0.0.0][deterministic]` **Resolve Input Design Spec** (`refine.input_resolution`): Resolve and verify the design spec input path.
   a. Resolve `design_spec_path` from config and CLI overrides.
   b. If path is not configured or file does not exist, skip the entire command.
   c. Produces no file.
3. `[v0.0.0][deterministic]` **Load SADS CSV** (`refine.csv_load`): Load design spec workset from CSV or XLSX.
   a. Parse the design spec file via `load_sads_csv_or_xlsx`.
   b. Extract headers and row dicts for downstream steps.
   c. Produces no file.
4. `[v0.0.0][deterministic]` **Validate Required Columns** (`refine.required_column_validation`): Enforce required columns on the loaded design spec.
   a. Check headers for required columns: `spec_id`, `module_tag`, `module_role`, `requirement`. (`acceptance_criteria` is optional on input; refine may add or overwrite it in output.)
   b. Match is case-insensitive.
   c. Stop early with a clear error listing all missing columns if any are absent.
   d. Produces no file.
5. `[v0.0.0][deterministic]` **Setup Run Directory** (`refine.run_dir_setup`): Create the run directory and write initial metadata.
   a. Resolve the run directory under the refine command namespace using the current `run_id`.
   b. Create directory structure including `manual_resolution/` subdirectory.
   c. Write initial `run_meta.json` with `command`, `run_id`, empty `completed_stages`, `resolution_status: running`, and `input_design_spec_path`.
   d. Produces: `run_meta.json`.
6. `[v0.0.0][deterministic]` **Run Decomposition Check** (`refine.decomposition.enabled`): Detect structural issues in specs using NLP sentence embeddings.
   a. Load `all-MiniLM-L6-v2` sentence-transformer model.
   b. **Split candidates**: For each spec, use `requirement` text only, split into sentences, compute pairwise cosine similarity variance across sentence embeddings. Flag specs where variance exceeds `variance_threshold` (default `0.15`), indicating mixed topic responsibilities.
   c. **Merge candidates**: Group specs by `module_tag`, embed requirement text per spec, compute cross-spec pairwise cosine similarity. Flag spec pairs where similarity exceeds `similarity_threshold` (default `0.85`), indicating redundant specs within the same module.
   d. If `decomposition.blocking` is true and any items are found, convert flags to `manual_resolution_items` and block execution. Each item offers `let_agent_edit` (agent splits/merges) or `skip` (keep as-is) options.
   e. Skipped entirely when `decomposition.enabled` is false or the sentence-transformers library is unavailable.
   f. Produces: `decomposition_flags.json`.
   > **Blocking rationale:** Decomposition items offer only `let_agent_edit` and `skip` — no `accept_suggestion` — because structural changes (split/merge) require agent judgment, not a pre-computed text replacement. When blocking is enabled, the user must resolve structural issues via `pika resolve` before agents run, preventing wasted agent calls on specs that will be restructured.
7. `[v0.2.0][agent]` **Run Quality Auditor Agents** (`spec_quality_auditor` x N): Invoke N parallel instances of the unified quality auditor agent (default N=4, configurable via `agent_replicas`). Replaces the prior pair of `spec_ambiguity_detector` + `spec_testability_enricher` agents — same N total LLM calls instead of 2N.
   a. Build prompt variables: `project_context`, `design_spec_csv` (minimal projection — `spec_id`, `module_tag`, `subunit`, `requirement` only, to save tokens), `manual_resolution_file`, `run_summary_file`, `output_schema_file`, `appendix_content`, `control_vocab_section`, `enrich_mode` (`full` for instance 0, `triage` for replicas).
   b. Instance 0 uses the `spec_quality_auditor_output` schema and produces `enrichments[]` (per-spec `acceptance_criteria` + non-empty `criteria[]` (each criterion tagged with its own `evidence_type`) + `test_plan` for clean specs), `manual_resolution_items[]` (specs with concerns), and `appendix_recommendations[]` (Stage 1.B dictionary gaps — see §7.1).
   c. Replicas 1..N-1 use the `spec_quality_auditor_triage_output` schema and produce only `manual_resolution_items[]`. They do NOT produce enrichments or appendix recommendations — those come from instance 0 alone.
   d. Send each instance via `invoke_agent_with_schema_retry`; retry per instance on schema validation failure.
   e. All N instances run in parallel via `ThreadPoolExecutor(max_workers=N)`.
   f. Produces: `auditor_output_0.json` through `auditor_output_{N-1}.json`.
   > **Failure semantics:** if any instance fails after exhausting schema retries, the entire refine run fails with the error detail. Per-instance outputs are persisted regardless to support resume.
7.1. `[v0.2.0][agent]` **Concern kinds and Stage 1.B recommendations** (within step 7): Each `manual_resolution_item` carries a `concern_kinds[]` array drawn from five rule families plus `consequence_class` and `worst_case`.
   a. **`vague_language`** — modal verbs, hedge phrases, immeasurable behavior. Populates `vague_phrases[]`.
   b. **`untestable_outcome`** — clear but not testable (negative-only, unbounded universal, deferred oracle). Populates `untestable_reason` and `suggested_test_type`.
   c. **`unresolvable_reference`** — a cross-spec reference is missing or vague, or an appendix entry the spec depends on is duplicate / undefined / type-conflicting.
   d. **`implementation_leak`** — constrains internal design with no external mandate. Suggested rewrite either exposes an observable consequence or proposes relocation to design documentation.
   e. **`legitimate_constraint`** — constrains internal design but is grounded in regulation, security policy, contract, or compliance. Populates `verification_method` (the non-behavioral verification mechanism).
   f. **Stage 1.B (`appendix_recommendations[]`, full mode only)** — when multiple specs needed values that should live in an org-level data dictionary (error code registry, validation format dictionary, input contract registry, etc.) and no such dictionary is supplied in appendix or sibling specs, instance 0 emits one recommendation per missing dictionary kind, listing every affected spec_id.
8. `[v0.2.0][deterministic]` **Consensus Filtering** (`refine.consensus_filter`): Filter `manual_resolution_items` by cross-instance agreement.
   a. Count how many instances flagged each `spec_id` (deduplicated within each instance).
   b. Keep only items where the `spec_id` count >= `consensus_min_votes` (default 3, clamped to `<= agent_replicas`).
   c. For each surviving `spec_id`, pick the representative item from the first instance that flagged it.
   d. `appendix_recommendations[]` are NOT consensus-filtered — they come from instance 0 alone (replicas don't produce them).
   e. Produces: `auditor_output.json` (consolidated v3 output: consensus items + appendix recommendations), `consensus_meta.json`.
9. `[v0.3.0][deterministic]` **Apply Testability Enrichments** (`refine.enrichment_apply`): Write per-spec `acceptance_criteria` from instance 0's `enrichments[]` onto the working rows; persist structured `criteria[]` (with per-criterion `evidence_type`) + `test_plan` per-spec side-files.
   a. Read `enrichments[]` from instance 0's auditor output.
   b. Skip any enrichment whose `spec_id` also appears in the consensus-filtered `manual_resolution_items` (manual resolution takes priority).
   c. Add `acceptance_criteria` column to headers if missing, then write the AC string onto the matching row in-memory (deferred to step 10's CSV write). The SADS CSV no longer carries an `evidence_type` column — per-criterion evidence_type is written into the per-spec test_plan side-file in step (d).
   d. For each enrichment, write a side-file at `<project_root>/out/state/test_plans/<spec_id>.json` with payload `{spec_id, criteria, test_plan}`. `criteria[]` is non-empty for every enrichable spec; each criterion carries `criterion_id`, `statement`, `observable_signal`, and `evidence_type`. Downstream consumers (implement) load by spec_id via `core.spec_acceptance.load_spec_test_plans`.
   e. Skipped under `--dry-run`.
   f. Produces: `enrichments.json`, plus per-spec `out/state/test_plans/<spec_id>.json` files.
10. `[v0.2.0][deterministic]` **Gate or Complete** (`refine.resolution_gate`): Decide final refine outcome based on consensus item count.
    a. **0 items**: Write the (potentially enriched) rows to the configured output path. Write `summary.json` with `status: completed`, `specs_enriched`, and `appendix_recommendations`. Update `run_meta.json` with `resolution_status: not_needed` and `output_design_spec_path`. Return completed.
    b. **N > 0 items**: Translate each v3 quality_item into a v1-shaped flat item via `_translate_v3_item_to_v2_legacy` (preserving v3 metadata as extra fields), then write `manual_resolution/agent_review.json` (`format_version: 2`, plus `appendix_recommendations[]` when present) and `manual_resolution/resolutions.yaml`. Write `summary.json` with `status: blocked`, `blocking_items`, `severity_breakdown` (e.g. "1 safety_or_clinical, 2 functional_defect"), `appendix_recommendations`, `specs_enriched`, and `input_design_spec_path`. Update `run_meta.json` with `blocked_at_stage: agent_review`. Return blocked.
    c. Produces: `summary.json`, and when blocked: `manual_resolution/agent_review.json`, `manual_resolution/resolutions.yaml`.

> **Desktop-app compatibility (Option A):** the on-disk `agent_review.json` is written in the legacy v2 shape (`format_version: 2`, flat items keyed on either `vague_phrases` or `untestable_reason` to drive the existing v1 transform path) so the desktop app keeps rendering unchanged. Full v3 metadata — `concern_kinds[]`, `consequence_class`, `worst_case`, `verification_method`, `appendix_recommendations[]` — is preserved in `auditor_output.json` and surfaces in `summary.json` and `resolutions.yaml`. Desktop-app v3 support will land in a separate change.

---

## Resume Flow

When invoked with `--resume <run_id>`, the refine command skips the initial pipeline and resumes one of three ways depending on `run_meta.json` state.

- **`blocked_at_stage: agent_review`** (after `pika resolve`): all spec edits were already applied to the output CSV by `_apply_refine_resolutions`. Resume returns `completed` immediately with the output path from `run_meta.json`.
- **`blocked_at_stage: decomposition`** (after `pika resolve`): structural edits (split/merge) were applied and a restructured CSV was written. Resume loads the restructured CSV, re-validates required columns, then runs steps 7–10 (agents → consensus → enrichment apply → gate) on the new spec set.
- **`failed_at_stage: <stage>` with completed agent stages**: a previous run failed after either `decomposition` or `agents` completed. Resume reloads the cached `auditor_output.json` and skips to gate; if only `decomposition` had completed, it re-runs the agents (steps 7–10).

> **Legacy cache rejection:** if a run directory contains pre-consolidation cache files (`ambiguity_output.json` and `testability_output.json`) and no `auditor_output.json`, resume raises `ResumeError` directing the user to start a fresh run. The schema is no longer compatible across the consolidation boundary.

> **Prerequisite (blocked branches):** Resume after a block requires `resolution_status: resolved` in `run_meta.json`. If not resolved, the command fails with a message directing the user to run `pika resolve --run <run_id>` first.
