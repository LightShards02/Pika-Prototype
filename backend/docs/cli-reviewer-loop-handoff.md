# CLI Handoff — Reviewer Loop & Multi-Agent Review Architecture

## Status

**Deferred.** This document captures CLI surface changes anticipated by the Phase 4 / Phase 5 reviewer-loop rollout. It is **not** part of that rollout — Phases 1–6 ship without any CLI changes; the reviewer loop is fully config-driven. These flags are runtime overrides for one-off runs and developer ergonomics, to be implemented as a separate handoff after the main rollout stabilizes.

The companion implementation plan lives at `C:\Users\night\.claude\plans\i-want-to-update-sleepy-lagoon.md` (user-local) — refer to it for the architecture and config keys these flags wrap.

## Context

The reviewer-loop refactor introduces:

- A two-tier reviewer (per-spec parallel LLM calls + deterministic synthesis pass).
- A bounded amendment loop with iteration counter, deterministic amendment IDs, stagnation detection, partial-spec lock-in, and typed escalations (`ambiguity`, `scope_conflict`, `loop_limit_exceeded`, `amendment_unsatisfiable`).
- Per-agent provider/model overrides (planner / implementer / reviewer / enricher).
- New artifacts surfaced to the user: `minor_findings[]`, amendment packets, axis findings.
- New verification semantics: timeout per command + demotion-to-evidence when reviewer is enabled.

Every behavior is reachable via `commands.implement.*` and `commands.refine.*` config blocks. The CLI flags below are convenience overrides; they do not unlock new capabilities.

## Proposed flags

### Reviewer enable / control
- `--reviewer` / `--no-reviewer` — override `commands.implement.reviewer.enabled`.
- `--reviewer-max-iterations N` — override `commands.implement.reviewer.max_iterations`.
- `--reviewer-max-parallel-per-spec N` — override `commands.implement.reviewer.max_parallel_per_spec`.
- `--reviewer-per-spec-timeout SECONDS` — override `commands.implement.reviewer.per_spec_max_total_seconds`.

### Per-agent model overrides
Lets a user run different agents on different models per invocation (e.g., reviewer on Opus while implementer runs on Haiku) without editing config:
- `--planner-model MODEL` / `--planner-provider PROVIDER`
- `--implementer-model MODEL` / `--implementer-provider PROVIDER`
- `--reviewer-model MODEL` / `--reviewer-provider PROVIDER`
- `--enricher-model MODEL` / `--enricher-provider PROVIDER`

These map to the per-agent override config keys introduced in Phase 4 (e.g., `commands.implement.reviewer.model`, `commands.implement.reviewer.agent_provider`).

### Verification controls
- `--verification-timeout SECONDS` — override `commands.implement.verification.timeout_seconds`.

### Visibility
- `--no-minor-findings-summary` — suppress the end-of-run minor findings summary printed to stderr (useful in CI environments where stderr is parsed). Default: summary is printed when `summary.json.minor_findings[]` is non-empty.
- `--show-amendment-history` — at run end, print a per-iteration diff of amendment packets (added / removed / persisted amendment IDs). Debugging only.

### Loop debugging
- `--force-reviewer-decision {approve|amend|manual_block}` — force the synthesis-pass `response_kind` for testing the loop's downstream behavior. Honored only when `--debug` is also set; emits a prominent stderr warning. Useful for testing escalation paths without crafting fixtures that naturally trigger them.

## Implementation guidance

CLI flags should resolve to config overrides at `argparse`-parse time using the same mechanism the existing CLI uses for config layering — they should not introduce parallel resolution logic alongside `core/config_loader.py`. Each new flag in `backend/cli.py` becomes one or more `set_config_override(path, value)` calls before the handler dispatches. This keeps flag semantics observable from the same config snapshot the handlers already rely on.

A small flag-to-config mapping table belongs alongside the CLI parser definition:

| Flag | Config path |
|---|---|
| `--reviewer` / `--no-reviewer` | `commands.implement.reviewer.enabled` |
| `--reviewer-max-iterations` | `commands.implement.reviewer.max_iterations` |
| `--reviewer-max-parallel-per-spec` | `commands.implement.reviewer.max_parallel_per_spec` |
| `--reviewer-per-spec-timeout` | `commands.implement.reviewer.per_spec_max_total_seconds` |
| `--reviewer-model` | `commands.implement.reviewer.model` |
| `--reviewer-provider` | `commands.implement.reviewer.agent_provider` |
| `--implementer-model` | `commands.implement.implementer.model` |
| `--implementer-provider` | `commands.implement.implementer.agent_provider` |
| `--planner-model` | `commands.implement.unified_planner.model` |
| `--planner-provider` | `commands.implement.unified_planner.agent_provider` |
| `--enricher-model` | `commands.refine.testability_enricher.model` |
| `--enricher-provider` | `commands.refine.testability_enricher.agent_provider` |
| `--verification-timeout` | `commands.implement.verification.timeout_seconds` |
| `--no-minor-findings-summary` | (CLI-only behavior flag) |
| `--show-amendment-history` | (CLI-only behavior flag) |
| `--force-reviewer-decision` | (CLI-only debug flag) |

## Out of scope

- **CLI commands for resuming specific iterations.** The existing `--resume <run_id>` already covers this; the loop's per-iteration artifacts (`review_loop_{batch}.json`) are read automatically.
- **A separate `pika review <run_id>` subcommand.** The reviewer is part of the implement loop, not a standalone phase. If a user wants to re-run review on a completed batch, the path is `--resume` after invalidating the cached reviewer output.
- **Interactive amendment editing.** Manual edits flow through `pika resolve` (which already handles MR items including the new typed escalations). The CLI does not expose amendment-editing primitives directly.
- **A `pika benchmark` subcommand for the A/B comparison** in the main plan's Long-Term TODOs. That benchmark, when implemented, can run as a script under `backend/benchmark/` rather than a first-class CLI verb.

## Acceptance criteria for this handoff implementation

1. Each flag in the table above maps to its config path with no parallel resolution logic.
2. Help text (`pika agent implement --help`) lists the new flags grouped under "Reviewer loop", "Per-agent overrides", "Verification", and "Debugging".
3. Mutually exclusive flags (`--reviewer` / `--no-reviewer`) reject conflicting combinations.
4. Debug-only flags (`--force-reviewer-decision`) error out without `--debug` rather than silently no-op.
5. Tests under `backend/tests/test_cli_reviewer_flags.py` cover: flag-to-config mapping, conflict detection, debug-flag gating.

## Cross-references

- Main implementation plan: `C:\Users\night\.claude\plans\i-want-to-update-sleepy-lagoon.md`
- Execution-order doc (updated by Phase 6): `backend/docs/implement-checks-execution-order.md`
- Config schema: `backend/config/config.schema.json`
- CLI entry point: `backend/cli.py`
- Per-agent override resolver (introduced in Phase 4): `backend/core/agent_invoker.py::resolve_agent_overrides`
