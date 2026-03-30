# validation-dataset-forecast

Use this project skill for validation dataset authoring and forecast-only command assessment.

## When to use

Use this skill when the task is to:
- create or revise a validation-use dataset package,
- assess spec concreteness,
- predict likely `refine` output,
- predict likely `implement` output,
- do any of the above without using implementation internals or run artifacts.

## Inputs

- dataset root
- `PROJECT_CONTEXT.md`
- `raw-design-spec.csv` or `state/DESIGN-SPEC.csv`
- `config.yaml`
- any configured appendices

## Rules

- Use only package-level artifacts for forecast-only assessment.
- Do not read implementation logic or run artifacts unless the user explicitly changes the scope.
- Separate:
  - hard blockers vs quality risks
  - dataset blockers vs environment blockers

## Dataset authoring checklist

1. Freeze the product type and primary medical-software user story.
2. Make module ownership explicit.
3. Use the repo package convention:
   - `PROJECT_CONTEXT.md`
   - `config.yaml`
   - `vocab.yaml`
   - `raw-design-spec.csv`
   - `state/`
4. Include required appendices for:
   - configurable items
   - error codes
5. Add optional appendices when needed:
   - data flow
   - DTO definitions
   - policy matrix
   - external interface references
6. Keep the SADS at validation-dataset scale:
   - roughly 55-70 rows
   - atomic requirements
   - generalized subunits
   - paired sender/receiver specs for cross-module behavior

## Forecast checklist

Score these as `strong`, `usable`, or `weak`:
- product shape clarity
- module boundary clarity
- shared contract clarity
- external dependency clarity
- policy and rule clarity
- verification grounding

## Refine warning signs

- one row mixes multiple behaviors
- vague actor or trigger wording
- implied contracts missing from SHARED specs or appendices
- named rule codes or statuses with no actual definitions

## Implement warning signs

- empty `src/` with no stack anchor
- external source named but no protocol or payload shape
- DTOs named without field-level detail
- policy codes named without trigger logic or decision rules

## Response format

Return:
1. Dataset Readiness
2. Refine Forecast
3. Implement Forecast
4. Top Gaps
5. Best Next Additions
