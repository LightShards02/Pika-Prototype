---
name: implement-problem-sourcing
description: Attribute implement-run findings to their true source (planner vs implementer vs validation gap), map each to deterministic checks by index, and report which checks failed to catch the issue.
---

# Implement Problem Sourcing

Use this when a user asks: "Where did this implement problem come from?" and wants ownership plus missed-check mapping.

## Goal

For each finding, answer two questions deterministically:
1. Which agent is mainly responsible?
2. Which deterministic check (from docs/implement-checks-execution-order.md) should have caught it but did not?

## Required Inputs

- Target run id (or latest run if not provided).
- Explicit list of findings to classify.
- Check index file: `docs/implement-checks-execution-order.md`.

## Evidence Collection (Deterministic)

1. Load run artifacts:
   - `out/agent_runs/implement/<run_id>/batch_plan.json`
   - `out/agent_runs/implement/<run_id>/unified_plan.json`
   - `out/agent_runs/implement/<run_id>/agent_outputs/implement_B*.json`
   - `out/agent_runs/implement/<run_id>/trace/trace.jsonl`
   - Validation outputs (`*_validation.json`)
2. Build a batch/spec ownership map:
   - file path -> diff id -> batch id -> owner_spec_id -> related_spec_ids.
3. Cross-check execution reality:
   - which batches completed,
   - what verification actually ran,
   - whether checks passed, skipped, or blocked.

## Attribution Rules

Use the first matching rule.

1. `Unified Planner Agent` (Check #5) is primary when:
   - dependency/context/contract declarations are incomplete or wrong in `unified_plan.json`, and downstream code follows that bad plan.
2. `Batch Implementer Agent` (Check #19) is primary when:
   - batch brief had enough context, but generated code violates spec intent or introduces local inconsistencies.
3. `Shared Responsibility` when:
   - planner under-specifies contract/dependency boundaries and implementer adds code that amplifies the mismatch.

## Missed-Check Mapping Rules

For each finding, map to checks by index number and id.

1. Mark `Failed-to-catch` only when the check ran and passed/skipped while evidence shows the issue.
2. Mark `Not-covered` when no listed deterministic check enforces that semantic class.
3. Always separate:
   - structural checks (plan/graph/path/shape),
   - semantic contract checks,
   - runtime verification checks.

Typical mappings:
- Contract/provider-consumer drift: #10 `implement.contract_field_consistency_validation.enabled`, #11 `implement.required_field_coverage_validation.enabled`.
- Missing escalation for ambiguous/overlap specs: #7 `implement.planner_manual_resolution_gate.enabled`, #9 `implement.intra_spec_conflict_validation.enabled`, #12 `implement.match_ambiguity_validation.enabled`.
- Behavior regressions not exercised: #23 `implement.verification_command_resolution.enabled`, #26 `implement.verification_execution.enabled`.

## Output Contract

Return one table with columns:
- Finding
- Primary Source Category
- Mainly Responsible Agent
- Evidence (artifact/file)
- Deterministic Check(s) That Should Catch It
- Why It Was Missed (passed/skipped/not-covered)

Then provide:
1. `Systemic gaps`: repeated missed-check patterns.
2. `Immediate hardening`: concrete check/test changes tied to check ids.

## Guardrails

- Do not guess ownership without artifact evidence.
- Do not conflate planner defects with implementer defects.
- If evidence is insufficient, explicitly mark `Insufficient evidence` and list missing artifact.
