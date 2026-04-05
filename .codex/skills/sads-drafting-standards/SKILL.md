---
name: sads-drafting-standards
description: Draft and revise SADS design specification rows with strict EARS wording, atomic scope, concrete UI/service workflows, and deterministic acceptance criteria. Use whenever creating or editing SADS/design_spec CSV content or requirement/acceptance text for design rows.
---

# SADS Drafting Standards

Follow this skill whenever drafting or revising SADS rows.

## Rules

1. Write each `requirement` in EARS form: `When the user/system [trigger], the [module] shall [observable behavior].`
2. Keep every row atomic. Split multi-step flows, branching logic, and complex processing into separate rows.
3. Describe concrete workflow behavior, not implementation internals.
4. Never include function names, class names, method names, dotted identifiers, or other code-style symbols in `title`, `requirement`, or `acceptance_criteria`.
5. Replace vague terms (`robust`, `flexible`, `optimized`, `user-friendly`) with observable outcomes.
6. Use positive expected behavior statements. Avoid `shall not` phrasing.
7. For any interaction spanning two modules, define separate specs per module: one spec for the sender module trigger and request contents, and one spec for the receiver module handling workflow and outcomes.
8. Use generalized subunit names and keep subunit shared across the same workflow part; avoid fragmenting one workflow into many narrow subunits.

## Workflow Detail Requirements

For UI rows, include:
- Layout placement (where each component appears on the page).
- User interactions (click, submit, select, open/close dialog, retry).
- State transitions (initial, loading, success, validation error, service error).

For service rows, include:
- Startup or dependency handshake/verification behavior when relevant.
- Request parsing and normalization flow.
- Response shaping (fields and status outcomes).
- Edge and error handling paths as explicit positive outcomes.

## Acceptance Criteria Rules

1. Keep `acceptance_criteria` testable and deterministic.
2. Reference exact response states/fields/statuses or UI outcomes.
3. Match one primary behavior per row.
4. Avoid broad criteria that combine unrelated behaviors.

## Drafting Checklist (Run Before Finalizing)

- Every requirement uses `When/If the user`, `When/If the system`, or `When/If the {module}` for conditional design specs; uses `the system` or `the {module}` for non-conditional specs; and includes `shall` for all specs.
- No requirement, title, or acceptance criteria includes function names, class names, method names, or dotted code identifiers.
- No row combines multiple independent workflows.
- Use generalized subunits, and assign one shared subunit to all rows in the same workflow part.
- UI rows contain layout + interaction + state behavior.
- Service rows contain request/response + edge/error behavior.
- No vague quality adjectives.
- No `shall not` statements.

