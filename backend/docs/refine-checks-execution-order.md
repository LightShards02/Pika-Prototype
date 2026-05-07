# Refine Command Checks In Execution Order

1. `[v0.0.0][deterministic]` **Normalize Refine Config** (`refine.config_normalization`): Parse and normalize refine configuration (enabled flag, prompt names, decomposition settings, thresholds).
  a. Read config from CLI flags and config files under `commands.refine`.
   b. Fill in defaults for missing values (`ambiguity_detector`, `testability_auditor`, `spec_editor` prompt names; decomposition enabled/blocking flags).
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
7. `[v0.1.0][agent]` **Run Ambiguity Detector Agents** (`spec_ambiguity_detector` x N): Invoke N parallel instances of the ambiguity detector agent (default N=4, configurable via `agent_replicas`).
  a. Build prompt variables: `project_context`, `design_spec_csv` (minimal projection — `spec_id`, `module_tag`, `subunit`, `requirement` only, to save tokens), `manual_resolution_file`, `run_summary_file`, `output_schema_file`, `appendix_content`, `control_vocab_section`.
   b. Send each instance to the ambiguity detector agent via `invoke_agent_with_schema_retry`.
   c. Parse returned JSON against the `spec_ambiguity_detector_output` schema.
   d. Retry agent generation per instance if schema validation fails.
   e. All N instances run in parallel with step 8's N instances.
   f. Produces: `ambiguity_output_0.json` through `ambiguity_output_{N-1}.json`.
8. `[v0.1.0][agent]` **Run Testability Enricher Agents** (`spec_testability_enricher` x N): Invoke N parallel instances of the testability enricher agent (default N=4, configurable via `agent_replicas`). Instance 0 runs in **full** mode; replicas 1..N-1 run in **triage** mode.
  a. Build prompt variables: `project_context`, `design_spec_csv` (same minimal projection as step 7), `manual_resolution_file`, `run_summary_file`, `output_schema_file`, `appendix_content`, `control_vocab_section`, `enrich_mode` (`full` for instance 0, `triage` otherwise).
   b. Instance 0 uses the `spec_testability_enricher_output` schema and returns both `enrichments[]` (per-spec `acceptance_criteria` + `evidence_type` writes) and `manual_resolution_items`.
   c. Replicas use the `spec_testability_triage_output` schema and return `manual_resolution_items` only (no AC writing — saves output tokens).
   d. Send each instance via `invoke_agent_with_schema_retry`; retry per instance on schema failure.
   e. All N instances run in parallel with step 7's N instances.
   f. Produces: `testability_output_0.json` through `testability_output_{N-1}.json`.
  > **Parallelism note:** Steps 7 and 8 execute concurrently via `ThreadPoolExecutor(max_workers=N*2)`. All 2N instances must complete (or fail) before the pipeline continues. If any instance fails (after exhausting schema validation retries), the entire refine run fails with the error detail.
8b. `[v0.1.0][deterministic]` **Consensus Filtering** (`refine.consensus_filter`): Filter agent `manual_resolution_items` by cross-instance agreement.
  a. For each agent type independently, count how many instances flagged each `spec_id` (deduplicated within each instance).
   b. Keep only items where the `spec_id` count >= `consensus_min_votes` (default 3, clamped to `<= agent_replicas`).
   c. For each surviving `spec_id`, pick the representative item from the first instance that flagged it.
   d. Produces: `ambiguity_output.json`, `testability_output.json` (consensus-filtered), `consensus_meta.json`.
8c. `[v0.1.0][deterministic]` **Apply Testability Enrichments** (`refine.enrichment_apply`): Write per-spec `acceptance_criteria` + `evidence_type` from instance 0's `enrichments[]` onto the working rows; persist structured `criteria[]` + `test_plan` per-spec side-files.
  a. Read `enrichments[]` from instance 0's testability output (full mode only).
   b. Skip any enrichment whose `spec_id` also appears in the consensus-filtered testability `manual_resolution_items` (manual resolution takes priority).
   c. Add `acceptance_criteria` / `evidence_type` columns to headers if missing, then write enrichment values onto the matching rows in-memory (deferred to step 10's CSV write).
   d. For each enrichment carrying `criteria` and/or `test_plan` (P2 — both currently optional in the schema), write a side-file at `<project_root>/out/state/test_plans/<spec_id>.json` with payload `{spec_id, criteria?, test_plan?}`. Downstream consumers (implement) load by spec_id via `core.spec_acceptance.load_spec_test_plans`.
   e. Skipped under `--dry-run`.
   f. Produces: `enrichments.json`, plus per-spec `out/state/test_plans/<spec_id>.json` files when structured criteria/test_plan are present.
9. `[v0.0.0][deterministic]` **Merge Manual Resolution Items** (`refine.item_merge`): Combine consensus-filtered items into a unified blocking list.
  a. Group ambiguity + testability items by `spec_id`. When both agents flag the same `spec_id`, emit a single **compound** item with `concerns[]` (one per agent type) and item-level `options` (`accept_ambiguity`, `accept_testability`, `accept_both_improvements`, `let_agent_edit`, `skip`).
   b. When only one agent flags a `spec_id`, emit a single non-compound item carrying that agent's original `options`.
   c. Prepend decomposition items unchanged (empty if step 6 was non-blocking).
   d. Final order: decomposition items, then merged spec items sorted by `spec_id`.
   e. Produces no file.
10. `[v0.0.0][deterministic]` **Gate or Complete** (`refine.resolution_gate`): Decide final refine outcome based on merged item count.
  a. **0 items**: Write the (potentially enriched) rows to the configured output path via `rows_to_csv(headers, rows)` — preserving original columns and adding `acceptance_criteria` / `evidence_type` when step 8c produced enrichments. Write `summary.json` with `status: completed` and `specs_enriched`. Update `run_meta.json` with `resolution_status: not_needed` and `output_design_spec_path`. Return completed.
    b. **N > 0 items**: Write `manual_resolution/agent_review.json` and `manual_resolution/resolutions.yaml` with all blocking items. Write `summary.json` with `status: blocked`, `blocking_items`, `ambiguity_items`, `testability_items`, `specs_enriched`, and `input_design_spec_path`. Update `run_meta.json` with `blocked_at_stage: agent_review`. Return blocked.
    c. Produces: `summary.json`, and when blocked: `manual_resolution/agent_review.json`, `manual_resolution/resolutions.yaml`.

---

## Resume Flow

When invoked with `--resume <run_id>`, the refine command skips the initial pipeline and resumes one of three ways depending on `run_meta.json` state.

- **`blocked_at_stage: agent_review`** (after `pika resolve`): all spec edits were already applied to the output CSV by `_apply_refine_resolutions`. Resume returns `completed` immediately with the output path from `run_meta.json`.
- **`blocked_at_stage: decomposition`** (after `pika resolve`): structural edits (split/merge) were applied and a restructured CSV was written. Resume loads the restructured CSV, re-validates required columns, then runs steps 7–10 (agents → consensus → enrichment apply → merge → gate) on the new spec set.
- **`failed_at_stage: <stage>` with completed agent stages**: a previous run failed after either `decomposition` or `agents` completed. Resume reloads cached agent outputs (`ambiguity_output.json`, `testability_output.json`) and skips to merge/gate; if only `decomposition` had completed, it re-runs the agents (steps 7–10).

> **Prerequisite (blocked branches):** Resume after a block requires `resolution_status: resolved` in `run_meta.json`. If not resolved, the command fails with a message directing the user to run `pika resolve --run <run_id>` first.

