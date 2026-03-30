# Validation Dataset Forecast

Use this project skill when working on validation-use datasets or when forecasting likely `refine` or `implement` behavior before running agents.

## When To Use

Use this file when a task asks you to:
- create or revise a testing dataset package,
- assess whether a dataset is concrete enough,
- predict likely `refine` findings,
- predict likely `implement` blockers or noisy areas,
- do any of the above without reading implementation internals or run artifacts.

## Scope Rules

- Base the analysis on `PROJECT_CONTEXT.md`, design-spec CSVs, appendices, `config.yaml`, and visible folder structure.
- Do not read detailed implementation logic or command run artifacts when the user asks for a forecast-only assessment.
- Separate dataset-caused risk from environment-caused risk.
- Separate hard deterministic blockers from non-blocking quality risks.

## Dataset Creation Checklist

1. Freeze the medical-software user story and operating shape first.
2. Keep module ownership explicit.
3. Use the repo convention:
   - `PROJECT_CONTEXT.md`
   - `config.yaml`
   - `vocab.yaml`
   - `raw-design-spec.csv`
   - `state/DESIGN-SPEC.csv`
   - required appendices for configurable items and error codes
   - optional appendices for data flow, DTO definitions, policy matrices, or external-interface references
4. Keep the SADS roughly within the repo’s validation dataset scale:
   - about 55-70 rows,
   - atomic requirements,
   - generalized subunits,
   - paired sender/receiver rows for cross-module behavior.

## Forecast Workflow

Assess these areas as `strong`, `usable`, or `weak`:
- product shape clarity,
- module boundary clarity,
- shared contract clarity,
- external dependency clarity,
- policy and rule clarity,
- verification grounding.

## Refine Forecast Heuristics

Expect `refine` risk to rise when:
- rows combine validation, orchestration, persistence, and response behavior,
- actor/trigger wording is ambiguous,
- shared contracts are implied but not represented in SHARED specs or appendices,
- policy or rule names exist without actual definitions.

Typical outcomes:
- `likely completed with findings`
- `likely blocked by manual resolution`
- `likely deterministic preflight failure`

## Implement Forecast Heuristics

Expect `implement` risk to rise when:
- the stack is not pinned enough for an empty or near-empty codebase,
- external interfaces are named but not described,
- SHARED contracts do not carry field-level detail,
- CORE rules name codes or statuses without formulas, triggers, or decision tables,
- verification expectations are not grounded.

Typical outcomes:
- `likely completed`
- `likely completed but noisy`
- `likely manual-resolution block`
- `likely deterministic preflight failure`

## Output Format

Return:
1. `Dataset Readiness`
2. `Refine Forecast`
3. `Implement Forecast`
4. `Top Gaps`
5. `Best Next Additions`
