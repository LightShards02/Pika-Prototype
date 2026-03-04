# TODO

- [x] Read and codify implement command contract from docs + dataset/CORE/PROJECT_CONTEXT.md.
- [x] Design and implement deterministic implement pipeline (run setup, workset, module catalog, planning, linking, validation, batching, briefs, execution).
- [x] Update prompts and schemas for planner/linker/implementer outputs and manual-resolution item shape.
- [x] Update config schema/example to support implement command optional keys and defaults.
- [x] Add/adjust tests for implement workflow and helper functions.
- [x] Run relevant test suite and verify passing behavior.

## Review

- Implement handler now executes multi-phase planning (workset -> module catalog -> planner/linker -> validation -> batching -> batch briefs -> execution/trace -> mapping translation).
- Added implement planner/linker schemas and updated implement output schema to spec-keyed contract shape.
- Added prompt entries for `implement_anchor_planner` and `implement_anchor_linker`; updated `implement_from_specs` prompt to use batch brief + spec-keyed output expectations.
- Expanded config schema/example with implement options (prompt names, type placement, budgets, verification, role limits, issue/test paths).
- Added focused unit tests for implement selection/catalog/validation + dry-run artifact generation.
- Verified test runs:
  - `conda run -n Local pytest tests/test_implement_handler.py tests/test_lifecycle.py tests/test_prompt_registry.py -q` -> 34 passed
  - `conda run -n Local pytest tests/test_map_handler.py tests/test_command_router.py tests/test_cli_prompt_validation.py -q` -> 57 passed

## Current Task: Nutrition Design Spec Fixture

- [x] Confirm design-spec CSV columns required by contract + implement handler.
- [x] Draft nutrition calculator spec rows for React frontend + FastAPI backend + domain/infra/shared modules.
- [x] Write fixture CSV to workspace with implement-ready defaults.
- [x] Validate required columns and non-empty fields for implement selection.
- [x] Document artifact path and intended test usage.

## Current Task Review: Nutrition Design Spec Fixture

- Added implement-ready design spec fixture at `dataset/design_spec_nutrition_react_fastapi.csv`.
- Included contract columns plus implement-required `module_role` and implement-output target column `mapped_test_cases`.
- Verified `_select_workset` accepts all 14 rows and module partitioning spans `UI`, `API`, `CORE`, `DATA`, `OBS`, `SHARED`.

## Current Task: Spec Drafting Corrections

- [x] Persist user-requested spec drafting rules in `tasks/lessons.md`.
- [x] Rewrite nutrition design spec using EARS statements and atomic spec rows.
- [x] Expand workflow detail for UI and service flows while avoiding vague/negative phrasing.
- [x] Validate revised CSV against implement workset requirements.

## Current Task Review: Spec Drafting Corrections

- Added five durable drafting lessons for future spec runs in `tasks/lessons.md`.
- Rewrote nutrition spec to 34 atomic rows with EARS-style requirements and explicit UI/service behaviors.
- Validated revised CSV: 16 headers, 34 rows selected by `_select_workset`, module coverage `UI/API/CORE/DATA/OBS/SHARED`.

## Current Task: Migrate SADS Drafting Lessons to Skill

- [x] Confirm Codex skill directory and Cursor rule directory targets.
- [x] Create a Codex skill that enforces SADS drafting standards.
- [x] Create a Cursor rule with the same drafting standards.
- [x] Remove migrated drafting lessons from `tasks/lessons.md`.
- [x] Validate created files and summarize usage behavior.

## Current Task Review: Migrate SADS Drafting Lessons to Skill

- Created Codex skill `sads-drafting-standards` in global and workspace-local skill directories.
- Added Cursor rule `.cursor/rules/SADS-Drafting-Standards.mdc` with the same drafting checklist.
- Removed migrated drafting rules from `tasks/lessons.md` so lessons file remains correction-focused.
- Validated both skill copies using `quick_validate.py` and confirmed pass.

## Current Task: Expand Spec Complexity (Login/History/Export)

- [ ] Add atomic SADS rows for user login feature across UI/API/CORE/DATA/SHARED modules.
- [ ] Add atomic SADS rows for history retention feature with sender/receiver split specs.
- [ ] Add atomic SADS rows for result export feature with sender/receiver split specs.
- [ ] Regenerate design spec CSV and sync canonical copy.
- [ ] Validate implement compatibility and EARS/wording checks.

## Current Task Review: Expand Spec Complexity (Login/History/Export)

- [x] Add atomic SADS rows for user login feature across UI/API/CORE/DATA/SHARED modules.
- [x] Add atomic SADS rows for history retention feature with sender/receiver split specs.
- [x] Add atomic SADS rows for result export feature with sender/receiver split specs.
- [x] Regenerate design spec CSV and sync canonical copy.
- [x] Validate implement compatibility and EARS/wording checks.

- Regenerated spec file: `dataset/nutrition/design_spec_nutrition_react_fastapi_v3.csv` (63 rows total).
- Synced canonical copy: `dataset/design_spec_nutrition_react_fastapi.csv`.
- `dataset/nutrition/design_spec_nutrition_react_fastapi_v2.csv` remained file-locked during this run and could not be overwritten.

## Current Task: Normalize Subunit Granularity

- [x] Define generalized subunit buckets for each workflow domain.
- [x] Regenerate design spec with normalized shared subunit values.
- [x] Validate implement compatibility and subunit consistency.
- [x] Sync canonical design spec copy and report paths.

## Current Task Review: Normalize Subunit Granularity

- Regenerated spec file: `dataset/nutrition/design_spec_nutrition_react_fastapi_v4.csv`.
- Normalized subunits into generalized buckets (`user_management`, `history_management`, `export_management`, etc.) and removed fragmented row-specific subunit names.
- Verified feature-group consistency:
  - `A1035-A1047` -> `user_management`
  - `A1048-A1054` -> `history_management`
  - `A1055-A1062` -> `export_management`
- Validated implement compatibility with `_select_workset` (63 rows selected).

## Current Task: Config Refactor (normalized_dir removal, project.state, commands structure)

- [x] Remove normalized_dir; rename formatted_design_spec → design_spec_path under commands.format.outputs.
- [x] Add project.state (design_spec_path, id_registry_path, sads_id_mapping_path).
- [x] Format: write to commands.format.outputs.design_spec_path, then copy to project.state.design_spec_path.
- [x] id_registry, sads_id_mapping: write to out/state first, then copy to project.state paths.
- [x] Refactor resolution: CLI override > commands.<cmd>.inputs > project.state for design_spec_path.
- [x] Update config.schema.json, config.example.yaml, pika.yaml, dataset configs, handlers, tests.
- [x] Run tests: 198 passed (2 codebase_snapshot tests deselected due to pre-existing parser issue).

## Current Task: Config Refactor (normalized_dir removal, command-scoped inputs/outputs/schemas)

- [x] Remove normalized_dir references (docs/handler_summary.md).
- [x] Rename formatted_design_spec → design_spec_path in test docstrings.
- [x] Add project.state (design_spec_path, id_registry_path, sads_id_mapping_path) — already in schema.
- [x] Format command: copy to project.state.design_spec_path after writing — already implemented.
- [x] id_registry, sads_id_mapping: write to out/state first, then copy to project.state — already in format_sads.py.
- [x] Refactor config: add commands.<cmd>.inputs, commands.<cmd>.outputs, commands.<cmd>.schemas (optional).
- [x] Update lifecycle resolution: _get_effective_inputs, _get_effective_outputs, _get_effective_schemas merge top-level with command-specific.
- [x] Update safety.py: use merged inputs/outputs, pass command to _iter_output_specs.
- [x] Fix review handler: replace undefined _get_schema_path with resolve_output_schema_path.
- [x] Run tests: 96 passed (config/lifecycle/handler tests).

## Current Task: Nutrition Dataset Config + Context

- [x] Create `dataset/nutrition/config.yaml` with command and path settings for nutrition design spec runs.
- [x] Create `dataset/nutrition/PROJECT_CONTEXT.md` describing architecture and workflows (calculator, login, history, export).
- [x] Validate YAML readability and verify required fields for runtime config loading.
- [x] Summarize paths and suggested command usage.

## Current Task Review: Nutrition Dataset Config + Context

- Added nutrition dataset workspace config at `dataset/nutrition/config.yaml` with design spec input defaulted to `design_spec_nutrition_react_fastapi_v4.csv`.
- Added nutrition dataset context at `dataset/nutrition/PROJECT_CONTEXT.md` with module architecture and key workflows (auth, calculation, history, export, observability).
- Validated config against `config/config.schema.json` using `load_and_validate_config` in the `Local` conda env.

## Current Task: Codex-Compatible Output Schema Fix

- [x] Identify schema compatibility gap for local Codex `--output-schema`/response_format requirements.
- [x] Patch affected agent output schemas to satisfy top-level object requirement without breaking existing validation logic.
- [x] Add deterministic validation guard so incompatible schemas fail fast in contract checks/tests.
- [x] Run targeted tests and reproduce command-path validation.

## Current Task Review: Codex-Compatible Output Schema Fix

- Added root `type: object` to all agent output schemas that previously used top-level `oneOf` only.
- Added contract validator guard: agent output schemas now fail contract checks when top-level `type` is not `object`.
- Added schema compatibility tests to ensure all `schemas/agent_outputs/*.json` and all prompt-referenced output schemas declare top-level `type: object`.
- Implemented local Codex schema compatibility adapter + fallback:
  - Normalize schema copy for Codex (`required` includes all property keys; object nodes enforce `additionalProperties: false` where needed).
  - If Codex rejects response_format schema (`invalid_json_schema`), retry once without `--output-schema`; PIKA still performs deterministic post-run jsonschema validation against original schema.
- Verification:
  - `conda run -n Local pytest tests/test_agent_invoker.py tests/test_agent_output_schemas.py tests/test_implement_handler.py tests/test_lifecycle.py -q` -> 59 passed
  - Re-ran `python cli.py agent implement --project-root dataset/nutrition --codebase-dir src --dry-run`; no immediate `type: None`/startup schema 400 halt, and planner artifacts were produced (`anchor_planner_API.json`, `anchor_planner_CORE.json`, `anchor_planner_DATA.json`) before command timeout in this tool session.

## Current Task: Implement Planner SCC/Phase Refactor + Deterministic Phase Signal

- [x] Add required `anchor_materialization_kind` enum to implement anchor planner schema.
- [x] Update implement anchor planner prompt to require deterministic `anchor_materialization_kind` values.
- [x] Refactor `_build_batches` to deterministic graph-aware planning (SCC + provider-first topological ordering) and remove order-dependent dependency loss.
- [x] Refine `_build_briefs` to batch-scope bindings/contracts/anchors only.
- [x] Add deterministic post-batch dependency validation and fail fast on violations.
- [x] Add unit tests for provider dependency propagation and brief scoping.
- [x] Run targeted tests in conda env `Local` and document results.


## Current Task Review: Implement Planner SCC/Phase Refactor + Deterministic Phase Signal

- Added required `anchor_materialization_kind` enum to anchor planner schema and updated planner prompt instructions with deterministic enum-only guidance.
- Replaced `_build_batches` with graph-aware deterministic planning:
  - consumer->provider graph extraction
  - deterministic Tarjan SCC detection
  - SCC topological ordering
  - acyclic provider-first batching and cyclic SCC cohort batching
- Added `_validate_batch_plan_dependencies` and integrated fail-fast `batch_plan_validation.json` generation in `run_implement`.
- Refined `_build_briefs` scoping:
  - bindings filtered by batch spec-linked intents
  - anchors filtered by batch spec_id intersection
  - contracts derived from scoped bindings
- Added regression tests for provider dependency propagation, cycle handling, dependency validation failures, brief scoping, and dry-run artifact emission.
- Verification:
  - `$env:PYTHONPATH='.'; conda run -n Local pytest tests/test_implement_handler.py tests/test_prompt_registry.py tests/test_agent_output_schemas.py -q` -> 22 passed
  - `$env:PYTHONPATH='.'; conda run -n Local pytest tests/test_lifecycle.py tests/test_agent_invoker.py -q` -> 57 passed

## Current Task: Implement Docs Sync After Planner Refactor

- [x] Update PROJECT_CONTEXT implement section to reflect multi-batch planner/linker workflow.
- [x] Update docs/handler_summary.md implement row for current preprocessing/output/translation behavior.
- [x] Update docs/implement_dependency_diagram.md for batch_plan_validation and scoped brief filtering.
- [x] Update docs/implement_appendix_examples.md planned_anchors to include anchor_materialization_kind and schema-valid anchor_kind values.
- [x] Run doc consistency grep and summarize changes.


## Current Task Review: Implement Docs Sync After Planner Refactor

- Updated `PROJECT_CONTEXT.md` implement phase and command section to reflect multi-batch planning/linking and spec-keyed per-batch execution.
- Updated `docs/handler_summary.md` implement table rows for current preprocessing, schemas, outputs, and translation behavior.
- Updated `docs/implement_dependency_diagram.md` with `batch_plan_validation.json`, SCC/topological batch derivation wording, and batch-scoped brief filtering semantics.
- Updated `docs/implement_appendix_examples.md` to include required `anchor_materialization_kind` in planned anchors and replaced invalid `anchor_kind` examples (`function`, `class`) with schema-valid values.
- Verified consistency with grep against stale phrases and new artifacts.

## Current Task: Linker Retry + Manual Resolution Escalation

- [x] Add implement linker retry configuration and deterministic retry loop.
- [x] Surface unbound required intent details from link-plan validation output.
- [x] Pass retry context into linker prompt so unresolved intents are either bound or emitted as manual resolution items.
- [x] Add/adjust unit tests for retry behavior and validation payload.
- [x] Run targeted tests in conda env `Local`.

## Current Task Review: Linker Retry + Manual Resolution Escalation

- Added `linker_max_attempts` support (default `2`) in implement config resolution and run metadata.
- Replaced single linker invocation with a deterministic retry loop that only retries when validation reports unbound required intents.
- Extended link-plan validation output with `unbound_required_refs` so retries are data-driven and auditable.
- Added linker retry context payload and prompt variable (`linker_retry_context_json`) instructing the linker to either bind each unbound required intent or emit `manual_resolution_items`.
- Added unit tests for:
  - retry-context payload generation and sorting,
  - validation emission of unbound required refs,
  - linker retry path that resolves on second attempt,
  - linker retry path that returns manual resolution items when no valid link exists.
- Verification:
  - `conda run -n Local pytest tests/test_implement_handler.py tests/test_prompt_registry.py tests/test_cli_prompt_validation.py -q` -> 27 passed
  - `conda run -n Local pytest tests/test_lifecycle.py tests/test_command_router.py -q` -> 44 passed

## Current Task: Config-Driven Disallowed Link Rules

- [x] Add `commands.implement.disallowed_link_kinds_by_required_role` to config schema and examples.
- [x] Parse and normalize disallowed role->kind policy in implement handler with compatibility defaults.
- [x] Refactor link-plan validator to use config-driven policy (remove hardcoded role rules).
- [x] Pass disallowed policy into linker prompt variables and persist effective policy in run metadata.
- [x] Update retry context to include role-based validation violations from config-driven checks.
- [x] Add/adjust tests for schema validation, parser defaults/overrides, validator behavior, and linker prompt wiring.
- [x] Run targeted tests in conda env `Local`.

## Current Task Review: Config-Driven Disallowed Link Rules

- Added `commands.implement.disallowed_link_kinds_by_required_role` to `config/config.schema.json` with strict role keys and contract-kind enums.
- Updated `config/config.example.yaml` and `dataset/nutrition/config.yaml` to show/configure role-based disallowed linking policy.
- Removed hardcoded frontend/domain link-kind bans from `_validate_link_plan`; policy is now resolved from implement config with backward-compatible defaults.
- Added run-level traceability by writing effective `disallowed_link_kinds_by_required_role` into implement `run_meta.json`.
- Wired linker prompt with policy payload variable `disallowed_link_kinds_by_required_role_json` and explicit instructions not to emit disallowed bindings.
- Extended linker retry context to include `validation_violations` and changed retry reason to `link_plan_validation_failed`.
- Added/updated tests:
  - new schema validation tests in `tests/test_config_loader.py`,
  - implement policy parser/default override tests,
  - config-driven validator behavior tests,
  - linker template-var wiring and run metadata assertions.
- Verification:
  - `conda run -n Local pytest tests/test_implement_handler.py tests/test_config_loader.py tests/test_prompt_registry.py tests/test_cli_prompt_validation.py -q` -> 33 passed
  - `conda run -n Local pytest tests/test_lifecycle.py tests/test_command_router.py -q` -> 44 passed
