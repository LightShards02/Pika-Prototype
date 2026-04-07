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
  a. Build prompt variables: `project_context`, `design_spec_csv`, `manual_resolution_file`, `run_summary_file`, `output_schema_file`.
   b. Send each instance to the ambiguity detector agent via `invoke_agent_with_schema_retry`.
   c. Parse returned JSON against the `spec_ambiguity_detector_output` schema.
   d. Retry agent generation per instance if schema validation fails.
   e. All N instances run in parallel with step 8's N instances.
   f. Produces: `ambiguity_output_0.json` through `ambiguity_output_{N-1}.json`.
8. `[v0.1.0][agent]` **Run Testability Auditor Agents** (`spec_testability_auditor` x N): Invoke N parallel instances of the testability auditor agent (default N=4, configurable via `agent_replicas`).
  a. Build prompt variables: `project_context`, `design_spec_csv`, `manual_resolution_file`, `run_summary_file`, `output_schema_file`.
   b. Send each instance to the testability auditor agent via `invoke_agent_with_schema_retry`.
   c. Parse returned JSON against the `spec_testability_auditor_output` schema.
   d. Retry agent generation per instance if schema validation fails.
   e. All N instances run in parallel with step 7's N instances.
   f. Produces: `testability_output_0.json` through `testability_output_{N-1}.json`.
  > **Parallelism note:** Steps 7 and 8 execute concurrently via `ThreadPoolExecutor(max_workers=N*2)`. All 2N instances must complete (or fail) before the pipeline continues. If any instance fails (after exhausting schema validation retries), the entire refine run fails with the error detail.
8b. `[v0.1.0][deterministic]` **Consensus Filtering** (`refine.consensus_filter`): Filter agent results by cross-instance agreement.
  a. For each agent type independently, count how many instances flagged each `spec_id` (deduplicated within each instance).
   b. Keep only items where the `spec_id` count >= `consensus_min_votes` (default 3).
   c. For each surviving `spec_id`, pick the representative item from the first instance that flagged it.
   d. Produces: `ambiguity_output.json`, `testability_output.json` (consensus-filtered), `consensus_meta.json`.
9. `[v0.0.0][deterministic]` **Merge Manual Resolution Items** (`refine.item_merge`): Combine consensus-filtered `manual_resolution_items` from all sources in order.
  a. Collect consensus-filtered items from ambiguity detector output (`manual_resolution_items` key).
   b. Collect consensus-filtered items from testability auditor output (`manual_resolution_items` key).
   c. Concatenate in order: decomposition items (empty if step 6 was non-blocking), ambiguity items, testability items.
   d. Produces no file.
10. `[v0.0.0][deterministic]` **Gate or Complete** (`refine.resolution_gate`): Decide final refine outcome based on merged item count.
  a. **0 items**: Copy input design spec to configured output path. Write `summary.json` with `status: completed`. Update `run_meta.json` with `resolution_status: not_needed` and `output_design_spec_path`. Return completed.
    b. **N > 0 items**: Write `manual_resolution/{stage}.json` and `resolutions.yaml` with all blocking items. Write `summary.json` with `status: blocked` and item counts (total, ambiguity, testability). Update `run_meta.json` with `blocked_at_stage: agent_review`. Return blocked.
    c. Produces: `summary.json`, and when blocked: `manual_resolution/agent_review.json`, `manual_resolution/resolutions.yaml`.

---

## Resume Flow

When invoked with `--resume <run_id>`, the refine command skips the initial pipeline and resumes from the blocked stage after `pika resolve` has applied resolutions.

- `**blocked_at_stage: agent_review`**: `pika resolve` already applied all spec edits via `_apply_refine_resolutions`. Resume returns `completed` immediately with the output path from `run_meta.json`.
- `**blocked_at_stage: decomposition**`: `pika resolve` applied structural edits (split/merge) and wrote a restructured CSV. Resume loads the restructured CSV, re-validates required columns, then runs steps 7–10 (agents → merge → gate) on the new spec set.

> **Prerequisite:** Resume requires `resolution_status: resolved` in `run_meta.json`. If not resolved, the command fails with a message directing the user to run `pika resolve --run <run_id>` first.

