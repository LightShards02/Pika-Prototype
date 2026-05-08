# Long-Term TODO: Implement Resilience Features

Deferred from implement.py code review (issue 11). These items improve robustness and operational efficiency but are not blocking for current functionality.

## Map Command

- [ ] **Parallel subunit agent calls** — Run subunit invocations via `ThreadPoolExecutor` (or similar) instead of sequentially. Requires: optional `--parallel` flag, configurable worker count, careful handling of shared state (`batch_outputs`, `partial_failures`), and consideration of provider rate limits.

## Resilience Features

- [ ] **Resume from last successful batch** — Checkpoint completed batches and allow re-run to continue from the first failed or unexecuted batch instead of starting from scratch.
- [ ] **Progress checkpoint file** — Persist run state (workset, module catalog, anchor plans, link plan, batch plan, completed batch IDs) to a checkpoint file for debugging and potential resume.
- [ ] **Concurrent independent batch execution** — Run batches that have no dependency on each other in parallel (e.g. via `concurrent.futures`) to reduce wall-clock time.
- [ ] **Atomic multi-patch application** — Enhance patch application so that all patches are applied in a single atomic operation (or with full rollback on any failure). Current implementation applies patches sequentially with rollback on failure; consider `git apply` of a combined patch or staging-based atomicity.
- [ ] **Idempotent re-run detection** — Detect when a run is being re-executed (e.g. same run_id, same config hash) and skip or reconcile already-completed work instead of duplicating.
- [ ] **Rollback on partial failure** — When a batch fails after some batches have already modified the codebase, offer or automatically perform rollback of all applied patches from the current run.

## Contract Materialization

- [ ] **TypeScript interface generation** — Extend `contract_materializer.py` to generate `.ts` interface files alongside Python contracts for cross-language projects. Requires: a `type_placement_path_ts` config key or deriving the output path from the consuming UI module's root dir in `module_catalog`, camelCase field normalization, and TS type mapping (`string→string`, `integer→number`, `list[X]→X[]`, etc.).

## Notes

- These features require careful design to avoid race conditions, state corruption, and increased complexity.
- Prioritize based on user feedback and operational pain points.
## Planner Improvement Loop

- [ ] **Automated planner quality loop (block/resume aware)** — Add deterministic telemetry capture and feedback application for `implement` runs:
  - Persist per-run telemetry to `out/agent_runs/implement/<run_id>/planner_telemetry.json` on terminal states (`completed`, `failed`, `blocked`) with: failed checks, mismatch counts by type, manual resolution item counts, and resolution outcomes when available.
  - Maintain deterministic rolling aggregate at `out/state/planner_telemetry_rollup.json` (deduped by `run_id` to avoid double-counting on resume).
  - On new runs, load rollup during implement config normalization and apply deterministic tuning rules (for example threshold nudges and alias allowlist updates) with caps and minimum sample sizes.
  - Record applied tuning decisions in current `run_meta.json` (for auditability and reproducibility).
  - Keep deterministic behavior only: no agent calls in telemetry aggregation/tuning.

## REST API & Run Lifecycle

- [ ] **Run TTL / cleanup policy** — Old `out/agent_runs/<cmd>/<run_id>/` directories accumulate indefinitely. Decide between an admin cleanup endpoint (`DELETE /v1/runs?older_than=...`) and automatic GC after N days. `generate_run_id` already embeds a timestamp, so retention queries are cheap. Out of scope for the initial REST migration; revisit once disk usage becomes a real concern.
