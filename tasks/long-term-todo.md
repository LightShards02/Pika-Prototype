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

## Notes

- These features require careful design to avoid race conditions, state corruption, and increased complexity.
- Prioritize based on user feedback and operational pain points.
