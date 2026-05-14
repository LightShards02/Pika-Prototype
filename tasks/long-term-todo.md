# Long-Term TODO

Deferred improvements from earlier reviews. Not blocking for current functionality.

## Resilience Features

- [ ] **Idempotent re-run detection** — Detect when a run is being re-executed (e.g. same run_id, same config hash) and skip or reconcile already-completed work instead of duplicating.
- [ ] **Rollback on partial failure** — When a batch fails after some batches have already modified the codebase, offer or automatically perform rollback of all applied patches from the current run.

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

## Regulatory (21 CFR Part 11)

- [ ] **Electronic signatures under 21 CFR Part 11** — Long-term, PIKA should grow first-class support for regulated electronic signatures: identity-bound signing events, non-repudiation and intent capture, audit trails that tie signatures to the exact artifact version and workflow step, and operator controls that align with Part 11 expectations (access control, record integrity, and validation evidence). Treat this as a product capability to design deliberately alongside run logs, workspace artifacts, and any future approval gates—not a bolt-on UI checkbox.
