---
name: validation-dataset-forecast
description: "Design or review validation-use software datasets and predict likely refine or implement behavior from PROJECT_CONTEXT, design specs, appendices, and config. Use when Codex needs to: (1) create a new testing dataset package, (2) judge whether specs are concrete enough before running agents, or (3) forecast likely manual-resolution, ambiguity, or planner/implementer problems without reading code implementation details or run artifacts."
---

# Validation Dataset Forecast

Use this skill for pre-run dataset authoring and risk assessment.

The key constraint is scope discipline:
- Base predictions on `PROJECT_CONTEXT.md`, design-spec CSVs, appendices, config, and visible folder structure.
- Do not read implementation code internals or run artifacts when the user asks for a forecast-only assessment.
- Separate dataset-caused risk from environment-caused risk.

## Required Inputs

- Dataset package root.
- `PROJECT_CONTEXT.md`.
- `raw-design-spec.csv` or `state/DESIGN-SPEC.csv`.
- `config.yaml`.
- Any appendix files referenced by `commands.refine.inputs.appendices` or `commands.implement.inputs.appendices`.

## Dataset Creation Workflow

1. Freeze the product shape first.
   - State the medical-software user story.
   - State the modules and module roles.
   - State whether the dataset is UI-facing, API-facing, worker-only, CLI-only, or data-facing.
2. Build the package in the repo's existing convention.
   - Use `PROJECT_CONTEXT.md`.
   - Add `config.yaml`, `vocab.yaml`, `raw-design-spec.csv`, and `state/`.
   - Add required appendices for configurable items and error codes.
   - Add optional appendices for data flow, DTO definitions, policy matrices, or external-interface references when the main spec would otherwise become vague.
3. Keep the SADS scale close to the repo's validation datasets.
   - Target roughly 55-70 atomic rows.
   - Use generalized subunits shared across the same workflow part.
   - Split cross-module behavior into sender and receiver rows.
4. Prefer concreteness over breadth.
   - Name fields, statuses, payload shapes, and error outcomes.
   - Avoid relying on implied external behavior that is not documented anywhere in the package.

## Concreteness Assessment Workflow

Score each area as `strong`, `usable`, or `weak`.

1. Product shape clarity
   - Is the product type explicit?
   - Is the primary user story explicit?
   - Is the runtime shape explicit enough for implementation choices?
2. Module boundary clarity
   - Are responsibilities cleanly separated across UI/API/CORE/DATA/SHARED/OBS or other allowed roles?
   - Are cross-module interactions split into paired specs?
3. Shared contract clarity
   - Are named DTOs, envelopes, and error shapes represented in SHARED specs or appendices?
   - Do spec rows name exact fields instead of vague payloads?
4. External dependency clarity
   - Are third-party or device boundaries described concretely enough to stub or implement safely?
   - If not, is the ambiguity explicitly treated as an external dependency rather than hidden inside CORE or DATA?
5. Policy and rule clarity
   - Are named rule codes, blocker codes, role rules, and thresholds backed by appendices or config proposals?
   - If algorithm names are present, is the trigger logic actually defined somewhere?
6. Verification grounding
   - Is there enough stack or codebase structure to predict what `implement` will generate?
   - Is an empty codebase intentional and acknowledged, or is the dataset pretending existing structure exists?

## Prediction Rules

Use these rules before making any forecast.

1. Distinguish `hard blockers` from `quality risks`.
   - `Hard blocker`: missing required input, malformed CSV, unsupported config shape, absent appendix path, or another deterministic preflight failure.
   - `Quality risk`: the command may run, but agent output is likely to be weak, divergent, or manual-resolution-heavy.
2. Distinguish `dataset blockers` from `environment blockers`.
   - Dataset blockers come from the package itself.
   - Environment blockers come from local auth, provider setup, missing binaries, or unrelated runtime state.
3. Do not promote a likely quality issue into a hard blocker without deterministic evidence.

## Refine Forecast Heuristics

Expect `refine` to focus on:
- multi-behavior rows,
- ambiguous actor/trigger wording,
- vague error handling,
- implied shared contracts not represented in SHARED specs,
- appendix-dependent logic that is not actually defined in any appendix.

Typical `refine` outcomes:
- `likely completed with findings`: package is structurally valid, but some rows will be flagged for ambiguity or decomposition.
- `likely blocked by manual resolution`: core policy or contract gaps are large enough that agent reviewers would need user decisions.
- `likely deterministic preflight failure`: required inputs or appendix files are missing or malformed.

Refine-specific warning signs:
- one row both validates, orchestrates, persists, and responds;
- named statuses or blocker codes appear in UI/API rows but not in SHARED or appendices;
- rule names exist without trigger logic anywhere in the package.

## Implement Forecast Heuristics

Expect `implement` risk to increase when any of these are true:
- the tech stack is not pinned enough for an empty codebase;
- the codebase root is empty and no module layout or starter shape is given;
- external system interfaces are named but not described;
- specs mention DTOs or envelopes without enough field-level detail;
- policy/rule codes exist without decision logic;
- verification expectations are unclear.

Typical `implement` outcomes:
- `likely completed`: stack, contracts, and boundary details are concrete enough to scaffold and verify.
- `likely completed but noisy`: the package is valid, but planner/implementer drift is likely because contracts or boundaries are underspecified.
- `likely manual-resolution block`: implementation requires choices the dataset has not fixed, such as stack, external protocol, or policy semantics.
- `likely deterministic preflight failure`: config/input path issues or malformed appendix/design files.

Implement-specific warning signs:
- empty `src/` with no language or framework anchor;
- DATA integration specs that name an external source but do not define protocol or payload;
- SHARED rows naming a contract while appendices omit concrete fields;
- CORE rules naming codes or policies without formulas, trigger rules, or decision tables.

## Output Format

Return these sections in order:

1. `Dataset Readiness`
   - one short verdict for the package as a whole.
2. `Refine Forecast`
   - expected outcome,
   - likely blockers if any,
   - likely non-blocking findings.
3. `Implement Forecast`
   - expected outcome,
   - likely blockers if any,
   - likely noisy areas even if the command runs.
4. `Top Gaps`
   - the 3-5 most important missing details.
5. `Best Next Additions`
   - the smallest dataset changes that would improve forecast confidence.

## Guardrails

- Do not claim a run blocked unless the package itself shows a deterministic reason.
- Do not read or cite run artifacts when the user asks for a forecast-only assessment.
- Do not read or cite detailed implementation logic when the user asks for a spec-concreteness prediction.
- If you infer a risk from the specs, label it as an expectation, not an observed failure.
