# TODO

## Current Task: Annotate Implement Execution Order with Planning Insertions

- [x] Read the current implement execution-order document and map each proposed harness methodology to a concrete insertion point.
- [x] Update `backend/docs/implement-checks-execution-order.md` with explicit `(planning)` insertion flags.
- [x] Review the updated document for coverage and placement clarity.

## Current Task Review: Annotate Implement Execution Order with Planning Insertions

- Updated `backend/docs/implement-checks-execution-order.md` with inline `(planning)` markers at the relevant insertion points in the workflow instead of adding vague future-work notes.
- Mapped runtime insertions to concrete workflow locations:
  - after planner manual-resolution gating: round handoff packet,
  - after dependency-context validation: batch acceptance contract,
  - after verification: batch evaluator gate and failure-class round-control policy.
- Added a separate planning-only section for the two non-runtime harness methodologies so the doc stays honest about execution order:
  - benchmark/ablation lane,
  - evaluator calibration corpus.

## Current Task: Harness Methodology Brainstorm for PIKA

- [x] Read the Anthropic harness design article and extract transferable methodology ideas.
- [x] Inspect PIKA orchestration modules and current harness patterns.
- [x] Produce prioritized recommendations tailored to PIKA with adoption notes.

## Current Task Review: Harness Methodology Brainstorm for PIKA

- Read the Anthropic article and extracted the transferable methodology themes: context resets/clean handoffs, planner-generator-evaluator separation, criteria-driven grading, negotiated contracts before execution, and periodic harness simplification through ablation.
- Reviewed PIKA's active backend orchestration and found strong existing foundations already aligned with the article: central prompt registry, schema-gated agent outputs, manual-resolution blocking, batch-scoped implement briefs, semantic retry, isolated local workspaces, structured run artifacts, and consensus filtering in `refine`.
- Identified the main improvement gap as evaluator methodology rather than basic harness safety: PIKA has strong deterministic guards, but limited first-class evaluator loops with explicit quality rubrics, negotiated acceptance contracts, and systematic "which harness steps are still load-bearing?" measurement.

- [x] Implement verification worktree bootstrap when project-root path is missing inside detached worktree.
- [x] Add regression tests for ignored/untracked subproject roots in detached worktree verification.
- [x] Run targeted tests in `Local` conda env and record outcomes.

## Current Task: Fix Worktree Project-Root Bootstrap for Ignored Subprojects

## Current Task Review: Fix Worktree Project-Root Bootstrap for Ignored Subprojects

- Updated `handlers/implement/execution.py` to bootstrap missing `worktree_project_root` paths instead of failing immediately.
- Added regression coverage in `tests/test_implement_execution.py` to simulate `.gitignore`d `dataset/` subproject roots and verify detached worktree verification succeeds.
- Verification:
  - `conda run -n Local python -m pytest tests/test_implement_execution.py::ImplementExecutionWorktreeBootstrapTests -q` -> `1 passed`
  - `conda run -n Local python -m pytest tests/test_implement_execution.py -q` -> `38 passed`
  - `conda run -n Local python -m pytest tests/test_implement_handler.py -q` -> `53 passed`
- [x] Add `lastMappedAt` state field across extension + webview payload types.
- [x] Persist `lastMappedAt` via VS Code workspace state and restore on activation.
- [x] Update refresh handler to stamp `lastMappedAt` on refresh button execution.
- [x] Render `Last mapped` panel row with `MM-DD HH:MM` formatting fallback.
- [x] Add targeted unit tests and run plugin checks.
- [x] Commit and push branch updates.

## Current Task Review: Plugin Last-Mapped Timestamp Persistence

- Added extension/webview state support for `lastMappedAt` and initialized state from persisted workspace memento.
- Refresh button flow now stamps click-time `Date.now()` and persists it via `designSpecMapper.lastMappedAt`.
- Plugin status panel now renders `Last mapped` using `MM-DD HH:MM` formatting with `Not mapped yet` fallback.
- Added focused `StateStore` tests for hydration, preservation across import updates, and explicit setter updates.
- Verification:
  - `npm run compile` -> pass
  - `npm run typecheck` -> pass
  - `npm test` -> `26 passed`
  - Manual GUI launch blocker: VS Code Extension Development Host crashed with code `5` in this environment.

- [ ] Reproduce current `implement` failure (`dataset/nutrition`, `--codebase-dir src`) and capture exit code/stdout/stderr.
- [ ] Collect deterministic evidence from latest run artifacts (`summary.json`, `run_meta.json`, verification logs, runtime log).
- [ ] Identify root cause and implement minimal fix with robust error handling.
- [ ] Run targeted tests in `Local` conda env and rerun `implement` if run cap allows.
- [ ] Document bug/solution/verification and follow-up risk in final report.

- [x] Implement noise-reduction updates for `implement` execution loop (retry grounding, diff contract simplification, post-planner dir creation, batch path tightening).
- [x] Update prompt/schema/semantic validators to require `diff_plan + diff_refs` output mode.
- [x] Add regression tests for retry pre-attempt workspace resync and conditional shared-contract path prefix.
- [x] Run targeted tests in `Local` conda environment.

## Current Task Review: Implement Noise Reduction Plan (Post-Planner Dir Creation)

- Implemented semantic retry pre-attempt hook support and wired batch retries to resync local shared workspace + refresh retry-sensitive prompt fields.
- Simplified implement output contract to `diff_plan + diff_refs` only:
  - removed legacy per-spec `diffs[]` handling from parser and semantic guard paths,
  - updated prompt instructions and output schema accordingly.
- Updated batch path contract to add `type_placement_path` only when `shared_contracts` are present in the batch.
- Added post-planner, pre-batch module directory creation under `codebase_dir`, with deterministic logging and local-shared-workspace resync before batch execution.
- Verification:
  - `conda run -n Local python -m pytest tests/test_implement_execution.py tests/test_implement_handler.py tests/test_prompt_registry.py -q` -> `89 passed`

- [x] Add short valid/invalid unified-diff and path-scope examples to `implement_from_specs` prompt.
- [x] Add explicit file-state grounding instructions for retry scenarios in implement prompt.
- [x] Run prompt registry tests to verify prompt YAML validity.

## Current Task: Harden Implement Prompt Guidance with Examples

- [x] Run implement debug loop (max 3 runs) for current request and capture deterministic evidence each run.
- [x] For each encountered bug, document `Bug` + `Solution` + `Verification`.
- [x] Apply minimal fixes and run targeted tests.
- [x] Stop at 3 runs max, then report unresolved items and next actions if still failing.

## Current Task: Continue Implement Debug (3-Run Cap)

## Current Task Review: Continue Implement Debug (3-Run Cap)

- Executed exactly 3 implement runs for this request (cap respected):
  - `20260308_234042_m0700`: failed `verification_failed_B0` (`patch does not apply` in `CORE/tests/test_domain_logic.py`).
  - `20260308_235822_m0700`: failed `execute_exception_B1` after semantic retries due non-applicable SHARED patch diffs.
  - `20260309_002313_m0700`: failed `execute_exception_B0` after semantic retries due non-applicable CORE patch diffs.
- Implemented fixes during this loop:
  - Added semantic `git apply --check` validation for diff applicability before patch-apply stage.
  - Added retry diff artifact cleanup + stronger semantic retry guidance to force diff regeneration from current filesystem state.
- Verification:
  - `conda run -n Local python -m pytest tests/test_implement_execution.py::ImplementExecutionHybridSemanticGuardTests tests/test_implement_execution.py::ImplementExecutionPatchApplySemanticGuardTests tests/test_implement_execution.py::ImplementExecutionSemanticRetryHelpersTests -q` -> `7 passed`
  - `conda run -n Local python -m pytest tests/test_implement_execution.py -q` -> `34 passed`

- [x] Update `implement-nondryrun-debug` skill to cap debug reruns to 3 total `implement` executions per request.
- [x] Update skill response contract to require explicit per-bug `Bug` + `Solution` + `Verification` reporting.
- [x] Sync both installed copies of the skill definition and record correction in `tasks/lessons.md`.

## Current Task: Update Implement Debug Skill Loop + Reporting Rules

- [x] Reproduce `implement` failure using nutrition workspace command (`python cli.py agent implement --project-root dataset/nutrition --codebase-dir src`).
- [x] Capture deterministic evidence (`stderr`, latest `summary.json`, `run_meta.json`, `implement_*.log`, verification logs).
- [x] Identify root cause and propose ordered remediation with risk/mitigations.
- [x] If code fix is required, implement minimal patch + targeted tests in conda env `Local`.

## Current Task: Debug `implement` Command (Non-Dry-Run)

## Current Task Review: Debug `implement` Command (Non-Dry-Run)

- Reproduced real non-dry-run failure in `Local` env:
  - `conda run -n Local python cli.py agent implement --project-root dataset/nutrition --codebase-dir src`
  - run_id `20260308_221858_m0700`, failed at `execute_B4` with timeout after 600s.
- Root cause: local provider timeout is hard-resolved from pika defaults (`local.exec_timeout_sec`), with no workspace override; B4 API batch exceeded that ceiling.
- Implemented workspace override support:
  - added `agent.local_exec_timeout_sec` to workspace schema/example and runtime timeout resolution.
  - set `dataset/nutrition/config.yaml` to `agent.local_exec_timeout_sec: 1200`.
- Follow-up rerun (`20260308_230503_m0700`) confirmed timeout regression was bypassed, but surfaced a new root blocker:
  - `verification_failed_B0` with `git apply --check` error `No valid patches in input`.
  - B0 patch artifacts contained malformed bare `@@` hunk markers.
- Hardened semantic validation to pre-check diff payload structure (`diff_path` exists/readable, file headers present, valid unified hunk headers). Invalid hunks now fail semantic validation and trigger deterministic semantic retry instead of failing at patch apply.
- Verification:
  - `conda run -n Local python -m pytest tests/test_lifecycle.py::GetLocalExecTimeoutTests tests/test_lifecycle.py::InvokeAgentLocalIsolationTests::test_invoke_agent_local_passes_workspace_timeout_override -q` -> `4 passed`
  - `conda run -n Local python -m pytest tests/test_config_loader.py -q` -> `6 passed`
  - `conda run -n Local python -m pytest tests/test_implement_execution.py::ImplementExecutionHybridSemanticGuardTests -q` -> `3 passed`

- [x] Reproduce `agent implement` destination bug with `--codebase-dir src` and confirm root cause in patch apply scope.
- [x] Update implement execution so unprefixed patch paths apply under resolved `codebase_dir` (not only project root/repo prefix).
- [x] Add regression tests for codebase-dir destination behavior and ensure existing temp-workspace tests remain green.
- [x] Run targeted test suite in conda env `Local` and record outcomes.

## Current Task: Implement `--codebase-dir` Apply Destination Fix

## Current Task Review: Implement `--codebase-dir` Apply Destination Fix

- Root cause confirmed in `handlers/implement/execution.py`: patch scope selection only considered git repo prefix/project root and ignored nested `codebase_dir`.
- Updated patch scope resolution to support deterministic 3-way scoping:
  - repo-prefixed paths (apply as-is),
  - project-root-relative paths (apply under repo project prefix),
  - codebase-relative paths (apply under repo project prefix + codebase prefix).
- Added existing-file target resolution for create-on-existing patch normalization so codebase-relative paths correctly detect files under nested codebase directories.
- Wired resolved `codebase_dir` from batch execution into `_apply_and_verify` without altering local shared temp workspace lifecycle.
- Added regression tests in `tests/test_implement_execution.py`:
  - unprefixed path lands under nested codebase dir,
  - explicit `src/...` path avoids double-prefixing,
  - mixed project-relative + codebase-relative scope is rejected deterministically.
- Verification:
  - `conda run -n Local python -m pytest tests/test_implement_execution.py -q` -> `29 passed`
  - `conda run -n Local python -m pytest tests/test_implement_handler.py -q` -> `46 passed`
  - `conda run -n Local python -m pytest tests/test_implement_execution.py tests/test_implement_handler.py -q` -> `75 passed`
  - `conda run -n Local python -m pytest tests/test_lifecycle.py -q` -> `1 failed` (`GetReasoningEffortTests::test_pika_defaults`, unrelated to changed files)

- [x] Add hybrid implement output support with top-level `diff_plan` plus per-spec `diff_refs` (backward compatible with legacy `diffs`).
- [x] Update implement schema and prompt contract for hybrid output and deterministic shared-diff ownership.
- [x] Update execution parser + semantic validation to resolve `diff_refs` through `diff_plan`.
- [x] Add regression tests for shared diff refs, legacy compatibility, and symbol/test mapping precision.
- [x] Run targeted tests in conda env `Local` and record results.

## Current Task Review: Hybrid `diff_plan` + `diff_refs` Support

- Added backward-compatible hybrid implement output support:
  - top-level `diff_plan[]` canonical patch plan,
  - per-spec `diff_refs[]` resolved into effective `diffs[]` during parsing,
  - legacy per-spec `diffs[]` still supported.
- Updated implement schema (`schemas/agent_outputs/implement_output.schema.json`) to allow:
  - optional top-level `diff_plan`,
  - per-spec `diffs[]` or `diff_refs[]` via `anyOf`.
- Updated prompt instructions (`prompts/PROMPT.yaml`) to prefer hybrid mode and shared-diff ownership while keeping legacy mode compatible.
- Updated semantic validation (`handlers/implement/semantic_guard.py`) to:
  - validate `diff_plan` shape/uniqueness,
  - resolve per-spec `diff_refs` to diff-plan entries for touched-path checks,
  - emit explicit violations for missing/unknown refs.
- Added regression tests in `tests/test_implement_execution.py`:
  - hybrid diff_ref resolution,
  - legacy compatibility,
  - unknown diff_ref handling,
  - semantic guard hybrid acceptance/rejection cases.
- Verification:
  - `conda run -n Local python -m pytest tests/test_implement_execution.py -q` -> `19 passed`
  - `conda run -n Local python -m pytest tests/test_implement_handler.py -q` -> `46 passed`
  - `conda run -n Local python -m pytest tests/test_prompt_registry.py -q` -> `6 passed`

- [x] Fix nested-project patch apply scope so unprefixed patch paths apply under project root, not repo root.
- [x] Add path-scope detection (prefixed/unprefixed/mixed) with deterministic conflict handling.
- [x] Add regression tests for nested apply behavior and mixed-scope rejection.
- [x] Run targeted tests in conda env `Local` and record results.

## Current Task Review: Nested Patch Apply Scope + B0 Regression

- Updated `handlers/implement/execution.py` apply/verify flow to use git-top-level apply with deterministic per-patch scope detection:
  - unprefixed project-relative patch paths => apply with `--directory <repo_prefix>`
  - already-prefixed repo-relative patch paths => apply without `--directory`
  - mixed prefixed/unprefixed paths => fail fast (`patch_scope_conflict`)
- Added no-op/skip guards that treat `git apply` “Skipped patch ...” output as failure for worktree and root checks/applies.
- Added regression tests in `tests/test_implement_execution.py`:
  - nested project patch lands under project root (not repo root),
  - mixed path scope patch is rejected deterministically.
- Verification:
  - `conda run -n Local python -m pytest tests/test_implement_execution.py -q` -> `14 passed`
  - `conda run -n Local python -m pytest tests/test_implement_handler.py -q` -> `46 passed`

- [x] Fix implement verification worktree path scoping for subdirectory project roots.
- [x] Add regression test proving verification runs from project root inside worktree (not repo root).
- [x] Run targeted implement execution tests in conda env `Local`.

## Current Task Review: B1 Verification Worktree Scope Fix

- Fixed `handlers/implement/execution.py::_apply_and_verify` to scope worktree operations to the project path inside the detached worktree when `project_root` is a subdirectory of a larger git repository.
- Added regression coverage in `tests/test_implement_execution.py` (`ImplementExecutionWorktreeScopeTests`) to ensure verification commands execute from worktree project root, not repository root.
- Verification:
  - `conda run -n Local python -m pytest tests/test_implement_execution.py -q` -> `13 passed`
  - `conda run -n Local python -m pytest tests/test_implement_handler.py -q` -> `46 passed`

- [x] Add semantic contract validation for implement planner and implementer outputs (path + mapping file checks) before patch apply.
- [x] Add semantic retry loop that feeds violations back into prompt context and retries agent output deterministically.
- [x] Inject deterministic path context into implement prompts (`allowed_paths_json`, `directory_tree_snapshot`, `forbidden_path_patterns_json`, `semantic_retry_context`).
- [x] Enforce mandatory per-batch verification fallback commands when `verification_commands` is empty.
- [x] Harden implement timeout/exception handling so planner and batch invoke exceptions produce failed summaries and still clean local shared workspace.
- [x] Update config schema/example and tests for new implement semantic retry setting and behavior.
- [x] Run targeted + impacted tests in conda env `Local`.

## Current Task Review: Implement Semantic Contract Guardrails (#1-#5)

- Added `handlers/implement/semantic_guard.py`:
  - semantic path validators for unified planner and batch implement outputs,
  - semantic retry wrapper around schema-validated agent calls,
  - deterministic directory-tree snapshot builder,
  - deterministic default batch verification command resolver.
- Updated implement planner invocation:
  - now uses semantic retry (`invoke_with_semantic_retry`) with planner path contract checks,
  - prompt context now includes allowed paths + directory snapshot + forbidden prefixes + semantic retry context,
  - planner invocation exceptions now produce `summary.json` failure (`planner_invoke_failed`) and clean shared temp workspace.
- Updated batch execution:
  - implementer output now goes through semantic retry before patch collection/apply,
  - semantic checks enforce touched path constraints and mapped file references,
  - default verification fallback runs module-scoped `pytest` when available, else `compileall`,
  - logs `lifecycle_verification_fallback_applied` when fallback commands are used.
- Added config support:
  - `commands.implement.semantic_validation_retries` (default `2`) in parser + schema + example config.
- Added/updated tests:
  - planner timeout cleanup + failed status handling,
  - fallback verification command behavior,
  - implement execution and handler tests patched to semantic retry wrapper path.
- Verification:
  - `conda run -n Local python -m pytest tests/test_implement_execution.py tests/test_implement_handler.py tests/test_prompt_registry.py tests/test_config_loader.py -q` -> `70 passed`
  - `conda run -n Local python -m pytest tests/test_lifecycle.py tests/test_cli_prompt_validation.py tests/test_map_handler.py tests/test_plan_handler.py tests/test_resolve_plan_handler.py -q` -> `95 passed`

- [x] Add local-agent workspace override support to lifecycle invoke path (`invoke_agent_local`, `invoke_agent_with_schema_retry`).
- [x] Implement run-scoped shared temp workspace for `implement` (local provider only) and wire planner + batch execution usage.
- [x] Resync shared workspace from real codebase before each implement invocation and switch batch prompt `codebase_dir` to mirrored workspace path.
- [x] Ensure shared workspace cleanup runs on completed/blocked/failed implement return paths and add lifecycle logs for create/resync/cleanup.
- [x] Add/update unit tests for lifecycle override behavior and implement shared-workspace wiring.
- [x] Run targeted tests in conda env `Local`.

## Current Task Review: Implement Shared Temp Workspace for Local Implement Runs

- Added optional `local_workspace_override` support in lifecycle local invoke path.
- Added shared workspace helpers in lifecycle:
  - `create_local_agent_shared_workspace`
  - `sync_local_agent_workspace`
  - `cleanup_local_agent_temp_workspace`
- Implement handler (`run_implement`) now creates one shared temp workspace for local provider runs, reuses it across planner + batches, logs create/resync/cleanup, and cleans it on return paths.
- Batch execution now resyncs the shared workspace before local invocation and sets prompt `codebase_dir` to the mirrored workspace path.
- Verification:
  - `conda run -n Local python -m pytest tests/test_lifecycle.py tests/test_implement_handler.py tests/test_implement_execution.py -q` -> `96 passed`
  - `conda run -n Local python -m pytest tests/test_map_handler.py tests/test_plan_handler.py tests/test_resolve_plan_handler.py -q` -> `46 passed`

- [x] Add runtime file-fact context for implement batches (with required `sha256`) so local mode is file-state aware.
- [x] Update `implement_from_specs` prompt contract/instructions to consume runtime file facts and avoid `new file mode` on existing files.
- [x] Add deterministic patch semantic normalization: skip idempotent create-on-existing, rewrite non-idempotent create-on-existing into modify diffs.
- [x] Add regression tests for semantic normalization behavior and runtime file facts shape.
- [x] Run targeted tests in `Local` conda env and record outcomes.

## Current Task Review: Existing-File New-Mode Verification Failures

- Implemented runtime batch file-state facts in `handlers/implement/execution.py` via `_build_runtime_file_facts`, with required fields per path: `exists`, `is_file`, `sha256` (empty string when unavailable).
- Updated implement prompt contract in `prompts/PROMPT.yaml` to consume `runtime_file_facts_json` and explicitly forbid `new file mode` for paths where `exists=true`.
- Added deterministic semantic normalization in `handlers/implement/execution.py`:
  - `_prepare_patch_files_for_apply` now inspects new-file sections before apply;
  - idempotent create-on-existing sections are skipped (`patch_already_applied_skip`);
  - non-idempotent create-on-existing sections are rewritten to modify diffs (`patch_create_to_modify_rewrite`);
  - unrecoverable forms (for example binary new-file patches) fail with `patch_semantic_conflict`.
- Kept patch application deterministic (`git apply --check` + `git apply`) after normalization; no direct overwrite path added.
- Added regression tests in `tests/test_implement_execution.py`:
  - idempotent skip case,
  - non-idempotent rewrite-and-apply case,
  - unrecoverable binary conflict case,
  - runtime file facts required `sha256` behavior.
- Verification:
  - `conda run -n Local python -m pytest tests/test_implement_execution.py -q` -> `8 passed`
  - `conda run -n Local python -m pytest tests/test_implement_handler.py -q` -> `43 passed`
  - `conda run -n Local python -m pytest tests/test_prompt_registry.py -q` -> `6 passed`

- [x] Reproduce `verification_failed_B0` in implement run `20260306_151444_m0800` and identify root cause from artifacts/logs.
- [x] Fix implement execution to prevent duplicate patch re-application within a batch.
- [x] Audit post-batch-planning implement stages for additional high-confidence failure modes.
- [x] Add/adjust unit tests for dedupe and any additional execution safeguards.
- [x] Run targeted test suite in `Local` conda env and record results.

## Current Task Review: Verification Failure in Implement B0 (20260306_151444_m0800)

- Root cause confirmed: B0 copied/apply-attempted identical patch payloads multiple times (same provider/test/history patch artifacts repeated per spec), so second apply failed with file already exists, returning `verification_failed_B0`.
- Execution hardening added in `handlers/implement/execution.py`:
  - dedupe identical patch payloads by hash before apply,
  - prevent patch filename overwrite when `diff_id` collides by suffixing (`_2`, `_3`, ...),
  - reject empty or non-file `diff_path`,
  - persist failure logs for worktree/patch apply failures under `verification/`.
- Post-batchplanning metadata hardening added in `handlers/implement/impl.py`:
  - write deterministic `completed_stages`,
  - set `failed_at_stage` on failures,
  - clear stale `blocked_at_stage`/`resolution_status` after non-blocking completion/failure.
- Verification:
  - `conda run -n Local python -m pytest tests/test_implement_execution.py tests/test_implement_handler.py -q` -> `45 passed`.

## Current Task: Batch Plan Validation Regression (forward provider paths)

- [x] Analyze repeated `batch_plan_validation_failed` in runs `20260306_151444_m0800` and `20260306_165653_m0800`.
- [x] Implement batching fix for forward provider refs across chunked batches.
- [x] Add regression tests for non-cyclic and cyclic-cohort forward dependency scenarios.
- [x] Evaluate fix against historical failing run artifacts.
- [x] Run targeted tests in conda env `Local`.

## Current Task Review: Batch Plan Validation Regression (forward provider paths)

- Root cause: `_build_batches` assigned specs chunk-by-chunk and computed dependencies in the same pass, so provider specs placed in later chunks were invisible when wiring early chunk deps.
- Fix in `handlers/implement/batching.py`:
  - added provider-first dependency-aware ordering of specs using spec-level SCC groups;
  - chunking now preserves SCC group atomicity (never splits a dependency cycle group);
  - switched to two-pass wiring per SCC/module group (assign all `spec_id -> batch_id` first, then compute `depends_on_batches`).
- Added regression coverage in `tests/test_implement_handler.py`:
  - `test_build_batches_orders_forward_provider_refs_across_module_chunks`;
  - `test_build_batches_cyclic_cohort_chunks_keep_provider_paths`.
- Evaluation on historical runs (recomputed batch plans with patched code):
  - `20260306_151444_m0800` -> batch plan dependency validation `passed`;
  - `20260306_165653_m0800` -> batch plan dependency validation `passed`;
  - `20260306_114305_m0800` -> remains `passed`.
- Verification:
  - `conda run -n Local python -m pytest tests/test_implement_handler.py -q` -> `43 passed`
  - `conda run -n Local python -m pytest tests/test_implement_execution.py tests/test_implement_handler.py -q` -> `47 passed`

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

## Current Task: Implement False-Positive Reduction (Implement Command)

- [x] Add implement config schema fields for leaf dependency policy, contract kind definitions, and type-shape match thresholds.
- [x] Extend planner schema to allow `declared_external_dependencies`.
- [x] Update planner/linker prompt templates to pass contract-kind definitions and normalization artifacts.
- [x] Add deterministic normalization module for kind correction, leaf auto-drop, and type-shape candidate scoring.
- [x] Integrate normalization stage into `handlers/implement.py` and persist normalization artifacts.
- [x] Harden link-plan validation with `external_api` semantic checks and richer retry context.
- [x] Add/adjust implement handler tests for new config defaults, linker vars, and semantic violations.
- [x] Add dedicated normalization unit tests.

## Current Task: Local Agent Isolated Temp Workspace

- [x] Isolate local-agent invocation in a disposable temp workspace outside the project tree.
- [x] Add immediate cleanup and stale-temp janitor behavior for isolated workspaces.
- [x] Preserve canonical run artifact `local_output.json` under agent artifacts.
- [x] Update local-provider prompt inputs to include codebase snapshot content in map/implement.
- [x] Add/update tests for isolated local invocation and provider-specific codebase content.

## Current Task Review: Local Agent Isolated Temp Workspace

- Local provider now executes Codex from an isolated temp workspace with per-invocation cleanup and stale-temp cleanup.
- `local_output.json` is copied back to the canonical run artifacts location after successful invocation.
- Map and implement local-provider template vars now include `codebase_content` snapshots (stub remains empty).
- Added lifecycle test coverage for isolated workspace usage/cleanup and updated map handler local-provider snapshot expectations.
- [x] Update implement dependency docs for normalization stage and artifacts.
- [x] Run targeted tests in conda env `Local` and record results.

## Current Task Review: Implement False-Positive Reduction (Implement Command)

- Added implement pre-link normalization pipeline and artifacts:
  - `anchor_plans_normalized/{module}.json`
  - `normalization_report.json`
  - `normalized_intent_catalog.json`
- Added deterministic normalization behaviors:
  - frontend internal API intent kind rewrite (`external_api` -> `api_endpoint`) when endpoint/capability signals internal API calls;
  - leaf role (`infra` etc.) required intents auto-drop with optional tracking as `declared_external_dependencies`;
  - required->provided type/shape candidate scoring and adapter hint scaffolding.
- Extended implement config/schemas/prompts:
  - new config fields for leaf policies, contract kind definitions, and type-shape thresholds;
  - planner schema now supports `declared_external_dependencies`;
  - planner/linker prompt variables include contract kind definitions and normalized intent catalog.
- Hardened validation/retry:
  - semantic failure for `external_api` contracts bound to internal provider modules;
  - added violation codes `external_api_bound_to_internal_provider` and `kind_semantics_violation`;
  - retry context now includes deterministic `type_shape_hints`.
- Added/updated tests:
  - `tests/test_implement_normalization.py` (new) for normalization/scoring behavior;
  - `tests/test_implement_handler.py` coverage for config defaults, linker vars, semantic violations, retry hints, and dry-run artifacts.
- Verification (Local conda env):
  - `conda run -n Local python -m pytest tests/test_implement_normalization.py tests/test_implement_handler.py -q` -> 27 passed
  - `conda run -n Local python -m pytest tests/test_lifecycle.py tests/test_prompt_registry.py tests/test_config_loader.py -q` -> 41 passed
  - `conda run -n Local python -m pytest -q` -> fails in `dataset/CORE/src/tests` due missing optional deps (`numpy`, `pandas`, package-local imports), unrelated to implement handler changes.

## Current Task: Analyze Blocked Linker Items (20260303_222122_m0800)

- [x] Inspect run artifacts for blocked linker items.
- [x] Extract blocked item reasons from manual resolution payload.
- [x] Categorize reasons with counts and affected item IDs.
- [x] Summarize findings for user with clear categories.

## Current Task Review: Analyze Blocked Linker Items (20260303_222122_m0800)

- Confirmed `manual_resolution/linker.json` contains 14 required linker blockers and that linker attempt stopped at `anchor_linker_attempt_1.json` with no retry output.
- Verified runtime block condition in `handlers/implement.py`: `_manual_block(...)` writes manual resolution payload and immediately returns `status=blocked`.
- Categorized blocker causes into 5 buckets:
  - score-threshold gate (8 items),
  - score-threshold + top-ranked semantic mismatch (3 items),
  - aggregate-intent ambiguity (1 item),
  - missing semantically correct provider (1 item),
  - score-threshold + frontend policy explicit selection (1 item).

## Current Task: Diagnose and Improve Normalized Intent Scoring

- [x] Inspect normalization/scoring implementation and weighting logic.
- [x] Quantify score distribution from latest run artifacts.
- [x] Identify root causes for globally low candidate scores.
- [x] Implement scoring improvements with minimal deterministic changes.
- [x] Add/adjust tests to verify improved score behavior.
- [x] Run targeted tests in conda env `Local` and summarize.

## Current Task Review: Diagnose and Improve Normalized Intent Scoring

- Root-cause findings from run `20260303_222122_m0800`:
  - top candidate scores were compressed (`avg_top=0.2066`, `max=0.3243`) versus `min_auto_bind_score=0.7`;
  - `spec_overlap_similarity` biased three API dependency intents toward same-module API providers due shared orchestrator spec IDs;
  - intent-name token similarity was diluted by routing/prefix tokens (`ui`, `req`, `api`, `dep`, etc.), weakening true endpoint/provider matches.
- Implemented scoring redesign in `core/implement_normalization.py`:
  - added module-affinity similarity/penalty signals from required intent routing patterns (`dep.<target>.*`, `api_endpoint` -> `API`);
  - reweighted score to favor capability/IO + intent-local-id semantics and removed spec-overlap from score contribution (kept in breakdown for diagnostics);
  - improved tokenizer with camel-case splitting + aliasing + generic token filtering;
  - added deterministic score rescaling to align score band with configured threshold semantics.
- Added regression coverage in `tests/test_implement_normalization.py`:
  - dependency-target-module preference over same-module spec-overlap candidate;
  - catalog ranking guard against same-module spec-overlap misranking.
- Verification:
  - `conda run -n Local python -m pytest tests/test_implement_normalization.py -q` -> 8 passed
  - `conda run -n Local python -m pytest tests/test_implement_handler.py -q` -> 21 passed
  - recalculated the same run catalog using patched scoring:
    - before: `avg_top=0.2066`, `auto_bind=0/14`;
    - after: `avg_top=0.8614`, `auto_bind=12/14`;
    - remaining non-auto-bind cases are semantically unresolved (`dep.core.token_policy`, aggregate `dep.shared.dto_contracts`).

## Current Task: Audit Dependency Building and Batch Division (20260303_231447_m0800)

- [x] Inspect run artifacts (anchor plans, link plan, batch plan, batch briefs).
- [x] Verify dependency graph correctness and contract coverage.
- [x] Verify batch division topological ordering and isolation.
- [x] Identify concrete issues with evidence paths.
- [x] Summarize risks and suggested fixes.

## Current Task Review: Audit Dependency Building and Batch Division (20260303_231447_m0800)

- Run completed (`summary.json` status `completed`), but artifact audit found structural batching/brief defects not covered by current validators.
- Problem 1: anchor leakage across batch boundaries and duplicate file ownership.
  - `B4` and `B5` both target `API/contracts/response_envelopes.py` and `API/tests/test_auth_history_export.py` with mixed cross-batch spec IDs.
  - `B6` and `B7` both target `UI/src/hooks/useNutritionCalculation.ts`, `UI/src/pages/HistoryPage.tsx`, `UI/src/__tests__/ui_workflows.test.tsx`, again with cross-batch spec IDs.
- Problem 2: over-conservative dependency edges in `batch_plan` due module-level dependency expansion.
  - `B5` depends on `B2`/`B3`, but `B5` brief bindings only require API/CORE/DATA contracts; no OBS/SHARED provider usage appears in the brief.
  - `B6` depends on `B5` although `B6` brief only includes contracts `C012-C014` (calculate/login/session from `B4`) and excludes history/export endpoint contracts `C015/C016`.
- Problem 3: budget mismatch between configured `max_files=10` and planned anchors.
  - `B0` plans 15 unique files; `B6` plans 11 unique files; both exceed configured `max_files`.
- Root-cause in implementation:
  - `_build_batches` computes dependencies by module graph and applies all provider batches to every chunk (`handlers/implement.py` around lines 1229-1231), ignoring per-chunk spec-intent scope.
  - `_build_briefs` includes any anchor with intersecting spec IDs but does not trim anchor `spec_ids` to the batch slice (`handlers/implement.py` around lines 1540-1555), causing multi-batch anchor duplication.
  - `_validate_batch_plan_dependencies` validates reachability/uniqueness but not budget adherence or cross-batch file ownership conflicts.

## Current Task: Unified Planner Redesign

- [x] Write COMMIT-README.md documenting anchor-linker design, limitations, and alternatives.
- [x] Create `archive/anchor-linker-design` branch to preserve current design.
- [x] Design unified planner output JSON schema (`implement_unified_planner_output.schema.json`).
- [x] Draft unified planner prompt in `prompts/PROMPT.yaml`.
- [x] Update `core/implement_types.py`: add SpecDependency, SharedContract, UnifiedPlan; remove RequiredRef, ProvidedRef, LinkBinding.
- [x] Refactor `handlers/implement/impl.py`: replace planner loop + normalization + linker with single unified planner call.
- [x] Refactor `handlers/implement/batching.py`: replace binding-based graph with spec-dependency graph.
- [x] Simplify `handlers/implement/validation.py`: replace link plan validation with DAG + budget validation.
- [x] Remove `core/implement_normalization.py` references from active pipeline (dead code, no imports remain).
- [x] Update `tests/test_implement_handler.py` for new pipeline structure (21 tests, all pass).
- [x] Update `docs/implement_dependency_diagram.md` and `PROJECT_CONTEXT.md`.

## Current Task Review: Unified Planner Redesign

- Replaced 3-agent anchoring/linking/batching pipeline with single Unified Planner pass.
- Eliminated intent abstraction (provided_intents, required_intents) and its 3 systematic failure classes:
  granularity mismatch (3 items), shape/field mismatch (6 items), cross-boundary field mapping (5 items).
- Pipeline now: workset -> module catalog -> **unified planner (1 call)** -> plan validation -> deterministic batching -> briefs -> execution.
- Agent calls reduced from 7+ (6 planner + 1+ linker) to 1 planning call + N batch calls.
- Dependencies are now spec-to-spec (direct references from design spec text) instead of abstract intent-to-intent matching.
- Shared contracts are declared holistically by the planner instead of matched by the linker.
- Batching remains deterministic (SCC + topological order + budget chunking) but driven by spec dependency graph.
- Verification: `conda run -n Local pytest tests/test_implement_handler.py tests/test_lifecycle.py tests/test_agent_output_schemas.py -q` -> 57 passed.
- Pre-existing failures in `test_codebase_snapshot.py` (tree-sitter parser) are unrelated.

## Current Task: Audit Alignment with Manual Resolution De-Blocking Plan

- [x] Read `C:/Users/night/.cursor/plans/manual_resolution_de-blocking_9be0ef68.plan.md` and extract acceptance criteria.
- [x] Map each criterion to current implementation in handlers/core/config/prompts/schemas/tests.
- [x] Identify missing/partial items with file-level evidence.
- [x] Summarize alignment status and concrete remediation list.

## Current Task Review: Audit Alignment with Manual Resolution De-Blocking Plan

- Core components were found in code (`core/resolution.py`, `handlers/resolve.py`, CLI `resolve` command, RuntimeContext extension), but full plan alignment is not achieved.
- Highest-impact gap: implement resume metadata is overwritten at run start, which breaks stage-aware resume behavior.
- Non-implement commands (`plan`, `map`, `resolve_plan`) still persist manual resolution to shared CSV instead of run-scoped YAML templates and do not inject `resolved_decisions` into prompts.
- Prompt/test coverage is partial: `resolved_decisions` is wired for implement prompts only, and no explicit resume-flow tests were found.

## Current Task: Fix Manual-Resolution Resume Gaps

- [x] Preserve and use existing run_meta resume stage metadata in implement (no overwrite on resume start).
- [x] Enforce strict `--resume` validation in CLI (run exists, resolutions present, all required items resolved).
- [x] Move `plan`/`map`/`resolve_plan` manual-resolution persistence from shared CSV to run-scoped `manual_resolution/{stage}.json` + `resolutions.yaml`.
- [x] Inject `resolved_decisions` into `plan`/`map`/`resolve_plan` template vars and add prompt template variables/sections.
- [x] Propagate deterministic contract resolution patches to downstream implement stages.
- [x] Add/adjust unit tests for resume validation, run-scoped manual resolution artifacts, and patched contract propagation.
- [x] Run targeted tests in conda env `Local` and document results.

## Current Task Review: Fix Manual-Resolution Resume Gaps

- Implement resume now preserves prior `run_meta.json` stage metadata before pipeline start and uses cached stage completion for stage-aware resume decisions.
- CLI `--resume` now validates run existence, `run_meta.json`, `blocked_at_stage`, and fully resolved `manual_resolution/resolutions.yaml` before dispatch.
- `plan`, `map`, and `resolve_plan` now persist manual-resolution blocks into run-scoped artifacts (`manual_resolution/{stage}.json`, `manual_resolution/resolutions.yaml`, and run_meta block fields) instead of shared CSV append-only storage.
- Prompt/handler wiring now includes `resolved_decisions` for `project_designer`, `map_spec_to_code`, and `map_issues_to_specs` flows.
- Implement contract-field resolution outputs now include patched `shared_contracts`, and `run_implement` uses the patched contracts downstream when building briefs.
- Verification (Local conda env):
  - `conda run -n Local pytest tests/test_cli_resume.py tests/test_plan_handler.py tests/test_resolve_plan_handler.py tests/test_map_handler.py tests/test_implement_handler.py tests/test_lifecycle.py tests/test_prompt_registry.py tests/test_cli_prompt_validation.py -q` -> 128 passed
  - `conda run -n Local pytest tests/test_command_router.py tests/test_resolution.py tests/test_resolve_handler.py tests/test_agent_output_schemas.py tests/test_lifecycle.py -q` -> 62 passed

## Current Task: Remove Deterministic Contract-Resolution Path for Validation Items

- [x] Remove deterministic contract patching from contract field consistency validation.
- [x] Switch validation mismatch/deviation items to no-option `edit_spec` resolution flow.
- [x] Add resolve CLI support for edit-spec acknowledgements via `DONE` while preserving agent option/free-text handling.
- [x] Update resolution validation rules to accept `acknowledged=true` for validation edit-spec items.
- [x] Add/adjust tests for validation, resolve handler interaction, implement contract consistency, and CLI resume checks.
- [x] Run targeted and integration tests in conda env `Local`.

## Current Task Review: Remove Deterministic Contract-Resolution Path for Validation Items

- Contract-field validation no longer applies `align_contract`/provider deterministic patches from manual resolutions.
- Validation-originated mismatch items are now guidance-only (`resolution_mode: edit_spec`, `options: []`) and carry spec amendment hints.
- `agent resolve` now supports `DONE` for edit-spec items and records `acknowledged: true`; `validate_resolutions` enforces this state for required edit-spec validation items.
- Resume validation accepts acknowledged edit-spec validation items and continues to enforce fully resolved state.
- Verification:
  - `conda run -n Local pytest tests/test_resolution.py tests/test_resolve_handler.py tests/test_cli_resume.py tests/test_implement_handler.py::ContractFieldConsistencyTests -q` -> `23 passed`
  - `conda run -n Local pytest tests/test_implement_handler.py -q` -> `33 passed`

## Current Task: Resume Warning for DONE Items

- [x] Emit CLI warning on `--resume` when acknowledged validation (`DONE`) items exist.
- [x] Add/adjust test coverage for warning emission.
- [x] Run targeted tests in conda env `Local`.

## Current Task Review: Resume Warning for DONE Items

- Updated resume path in `cli.py` to detect acknowledged validation items and emit a yellow warning before dispatch.
- Warning clarifies that resume re-validates and may block again if spec edits were not actually applied.
- Verification: `conda run -n Local pytest tests/test_cli_resume.py -q` -> `3 passed`.

## Current Task: Resume Log Collision Fix

- [x] Identify root cause for `--resume` failure on existing run log file.
- [x] Update run logger initialization to append on resume when the log file already exists.
- [x] Preserve existing collision safety for non-resume runs (exclusive create remains default).
- [x] Add/adjust unit tests for resume append and non-resume collision behavior.
- [x] Run targeted tests in conda env `Local` and verify pass.

## Current Task Review: Resume Log Collision Fix

- Root cause confirmed: resume reuses run_id while logger previously always opened `out/logs/{command}_{run_id}.log` using exclusive mode `x`.
- Implemented resume-aware behavior in `core/logger.py`: if `ctx.resume_run_id == ctx.run_id` and log exists, logger opens in append mode; otherwise it still uses exclusive create mode.
- Prevented duplicate meta header insertion when appending to non-empty existing logs.
- Added tests in `tests/test_logger.py`:
  - append succeeds for existing log during resume;
  - non-resume collision continues to fail with clear `RuntimeError`.
- Verification:
  - `$env:PYTHONPATH='.'; conda run -n Local pytest tests/test_logger.py tests/test_cli_resume.py -q` -> `11 passed`.

## Current Task: Analyze Local OSS Model Backend Enablement

- [x] Read current project/provider/runtime contracts for agent invocation.
- [x] Trace provider selection, local/api execution adapters, and schema-validation flow.
- [x] Identify assumptions that are currently Codex-specific in the `local` path.
- [x] Summarize exact model-side changes required for a locally deployed OSS backend.
- [x] List unresolved design questions that need a product/engineering decision before implementation.

## Current Task Review: Analyze Local OSS Model Backend Enablement

- Confirmed `agent.provider=local` is currently a Codex CLI adapter, not a generic local-model backend.
- Identified current coupling points:
  - config schema only distinguishes `stub | api | local`;
  - local execution always uses Codex `exec` flags and schema handling;
  - map/implement handlers treat `local` as having direct filesystem access and therefore skip codebase snapshot injection.
- Derived required work for a new locally deployed OSS backend:
  - add a backend/transport distinction under agent config;
  - implement a non-Codex local adapter with its own request/response and structured-output handling;
  - preserve existing deterministic schema validation/manual-resolution behavior above the adapter layer.
- Open decisions remain around transport (`OpenAI`-compatible HTTP vs dedicated backend such as Ollama/vLLM/llama.cpp), filesystem access semantics, and whether the existing `local` value should remain Codex-only or become a family of local backends.

## Current Task: Distance-Based Contract Field Matching

- [x] Replace near-miss and provider-deviation matching with split/sort/join + Damerau-Levenshtein pair scoring.
- [x] Emit manual resolution items only when matched pairs are within a configurable threshold.
- [x] Update question text to list only high-match word pairs.
- [x] Add implement config key for matching threshold and wire through runtime validator call.
- [x] Update config schema/examples and add test coverage.
- [x] Run targeted tests in conda env `Local`.

## Current Task Review: Distance-Based Contract Field Matching

- Updated `handlers/implement/validation.py`:
  - Added camel/snake/kebab word splitting, deterministic normalized word representation, and Damerau-Levenshtein distance computation.
  - Consumer near-miss now compares every spec word against contract fields and emits only high-match pairs within threshold.
  - Provider deviation now compares missing contract fields against provider spec words and emits only when high-match pairs exist.
  - Question text now lists only matched word pairs and threshold context; no large token dumps.
- Added implement config support:
  - New `commands.implement.field_match_distance_threshold` (default `2`) in `handlers/implement/config.py`.
  - Wired into implement runtime call path in `handlers/implement/impl.py`.
  - Added schema support in `config/config.schema.json`.
  - Added examples in `config/config.example.yaml` and active value in `dataset/nutrition/config.yaml`.
- Added/updated tests:
  - `tests/test_implement_handler.py`: config parsing, threshold-gated non-issue behavior, high-match question text, existing mismatch tests adapted to explicit threshold.
  - `tests/test_config_loader.py`: schema acceptance/rejection tests for the new threshold key.
- Verification:
  - `$env:PYTHONPATH='.'; conda run -n Local pytest tests/test_implement_handler.py tests/test_config_loader.py -q` -> `41 passed`
  - `$env:PYTHONPATH='.'; conda run -n Local pytest tests/test_resolution.py tests/test_resolve_handler.py -q` -> `18 passed`
  - Re-evaluated run artifact `dataset/nutrition/out/agent_runs/implement/20260305_231240_m0800`: threshold `2` -> `0` items, threshold `5` -> `0` items.

## Current Task: Normalize Field-Match Scoring to 0..1

- [x] Convert contract field matching from raw Damerau-Levenshtein distance threshold to normalized score threshold.
- [x] Update implement config key and parser to use normalized score range [0,1].
- [x] Keep backward-compatible alias handling for previous distance-threshold key.
- [x] Update schema, example config, and dataset config to normalized score semantics.
- [x] Update tests and run targeted suites in conda env `Local`.

## Current Task Review: Normalize Field-Match Scoring to 0..1

- Updated validator scoring in `handlers/implement/validation.py`:
  - still computes Damerau-Levenshtein distance after split/sort/join normalization,
  - now derives normalized score `1 - distance/max_len`,
  - high-match gating now uses `match_score_threshold` in `[0,1]`.
- Updated implement config parsing in `handlers/implement/config.py`:
  - new normalized key `field_match_score_threshold` (default `0.80`),
  - deprecated alias `field_match_distance_threshold` is still read for compatibility.
- Updated runtime wiring in `handlers/implement/impl.py` to pass `match_score_threshold`.
- Updated schema/examples/config:
  - `config/config.schema.json`: added `field_match_score_threshold` (`number`, `0..1`), kept deprecated alias as `0..1`.
  - `config/config.example.yaml`: switched to `field_match_score_threshold: 0.80`.
  - `dataset/nutrition/config.yaml`: switched to `field_match_score_threshold: 0.80`.
- Verification:
  - `$env:PYTHONPATH='.'; conda run -n Local pytest tests/test_implement_handler.py tests/test_config_loader.py tests/test_resolution.py tests/test_resolve_handler.py -q` -> `60 passed`.

## Current Task: Global One-to-One Match Pruning (Contract Field Validation)

- [x] Confirm root cause in latest nutrition implement run artifacts and validator logic.
- [x] Implement global one-to-one pruning so each contract/spec token participates in at most one fuzzy match.
- [x] Reserve exact token matches before fuzzy assignment to prevent overshadow false positives.
- [x] Add regression tests for A1060-style `artifact` vs `artifact_id` behavior.
- [x] Run targeted tests in conda env `Local`.

## Current Task Review: Global One-to-One Match Pruning (Contract Field Validation)

- Updated `handlers/implement/validation.py`:
  - added deterministic global candidate ranking helper (`_match_sort_key`);
  - replaced per-token best-match logic with global one-to-one greedy assignment (`_global_high_matches_one_to_one`);
  - reserved exact token intersections (`spec_words ∩ contract_fields`) before fuzzy matching so exact matches cannot be reused by near-miss tokens.
- Consumer mismatch behavior now prunes duplicate mappings to the same contract field and removes overshadow false positives like `artifact -> artifact_id` when `artifact_id` already appears exactly.
- Provider deviation matching now uses the same one-to-one pruning and exact-token reservation behavior for symmetry.
- Added regression tests in `tests/test_implement_handler.py`:
  - `test_consumer_match_does_not_use_exactly_matched_contract_field`
  - `test_consumer_matches_are_pruned_to_one_to_one_assignment`
- Verification:
  - `$env:PYTHONPATH='.'; conda run -n Local pytest tests/test_implement_handler.py -q` -> `38 passed`
  - `$env:PYTHONPATH='.'; conda run -n Local python -c "<validator replay on run 20260306_110555_m0800 inputs>"` -> `total_items 0`, `export_items 0` (no `export_artifact_metadata_dto` / `export_link_response` mismatch items).

## Current Task: codebase_dir Fallback Semantics

- [x] Update `resolve_codebase_dir_path` to match explicit/config/default/missing fallback behavior.
- [x] Update lifecycle tests for missing-path fallback (no auto-create).
- [x] Run targeted tests in conda env `Local`.

## Current Task Review: codebase_dir Fallback Semantics

- Updated `core/lifecycle.py::resolve_codebase_dir_path` behavior:
  - explicit/configured existing directory -> use it,
  - configured `"."` or unset -> `project_root`,
  - configured missing/non-directory path -> `project_root` (no directory creation).
- Updated `tests/test_lifecycle.py` resolve-codebase tests to reflect the fallback matrix, including explicit existing path, command-input `src`, dot, and missing-path fallback.
- Verification:
  - `conda run -n Local python -m pytest tests/test_lifecycle.py -q` -> `44 passed`
  - `conda run -n Local python -m pytest tests/test_map_handler.py tests/test_plan_handler.py tests/test_implement_handler.py tests/test_safety.py -q` -> `97 passed`

## Current Task: Create Implement Debug Skill

- [x] Define skill behavior and trigger conditions for non-dry-run implement debugging.
- [x] Create workspace-local skill files (`SKILL.md`, `agents/openai.yaml`).
- [x] Validate the new skill with `quick_validate.py`.
- [x] Document review results in this TODO file.

## Current Task Review: Create Implement Debug Skill

- Added workspace-local skill `implement-nondryrun-debug` at `.codex/skills/implement-nondryrun-debug`.
- Mirrored the same skill to global Codex skills at `C:/Users/night/.codex/skills/implement-nondryrun-debug`.
- Implemented strict workflow requirements in `SKILL.md`:
  - exact non-dry-run implement command,
  - wait-until-complete without intermediate analysis,
  - deterministic stderr/log/run-artifact triage,
  - success-path generated-code issue review,
  - failure-path root cause + repair plan + follow-up error risk assessment.
- Updated UI metadata in `agents/openai.yaml` to reflect the fixed command and behavior.
- Verification:
  - `conda run -n Local python C:/Users/night/.codex/skills/.system/skill-creator/scripts/quick_validate.py .codex/skills/implement-nondryrun-debug` -> `Skill is valid!`
  - `conda run -n Local python C:/Users/night/.codex/skills/.system/skill-creator/scripts/quick_validate.py C:/Users/night/.codex/skills/implement-nondryrun-debug` -> `Skill is valid!`
## Current Task: Debug `implement` Non-Dry-Run (dataset/nutrition)

- [ ] Reproduce with exact command: `python cli.py agent implement --project-root dataset/nutrition --codebase-dir src`.
- [ ] Capture exit code, stdout, stderr, and identify latest run_id.
- [ ] Triage `summary.json`, `run_meta.json`, verification logs, and runtime log.
- [ ] If failure is due to code defect, implement deterministic fix + tests.
- [ ] Re-run validation and document outcome/risk.
## Current Task Review: Debug `implement` Non-Dry-Run (dataset/nutrition)

- [x] Reproduce with exact command: `python cli.py agent implement --project-root dataset/nutrition --codebase-dir src` (run in conda env `Local`).
- [x] Capture exit code, stdout, stderr, and run artifacts for repeated failing runs.
- [x] Triage first-failure sources across stderr, `summary.json`, verification logs, and lifecycle logs.
- [x] Implement deterministic hardening for malformed patch variants and verification fallback target selection.
- [x] Re-run targeted tests and non-dry-run command to verify behavior change.

### Verification Results

- `conda run -n Local python -m pytest tests/test_implement_execution.py -q` -> `26 passed`
- `conda run -n Local python -m pytest tests/test_implement_handler.py -q` -> `46 passed`
- Latest non-dry-run implement run: `20260308_133253_m0700` -> `status: blocked` at `implement_B0` (manual resolution), not `verification_failed_B0/B1`.

## Current Task: VS Code Plugin MVP (React)

- [x] Scaffold VS Code extension + React webview build pipeline.
- [x] Implement design spec import (CSV) and table preview in webview.
- [x] Implement placeholder spec->code mapping with deterministic dummy data.
- [x] Implement code->spec mapping view on active code file context with dummy data.
- [x] Add focused unit tests for parser/mapping services.
- [x] Run targeted checks (`npm run compile`, `npm test`) and package validation.

## Current Task: VS Code Plugin UX + Real-Time Mapping Enhancements

- [x] Show imported design spec as its own file-tab document with mapping hyperlinks to code symbols.
- [x] Replace import/refresh text buttons with icon-sized buttons and tooltips.
- [x] Add real-time cursor-to-spec mapping in left panel for current function/class context.
- [x] Add/adjust focused tests for new placeholder mapping helpers.
- [x] Run targeted checks and complete manual GUI walkthrough with demo artifact.

## Current Task Review: VS Code Plugin UX + Real-Time Mapping Enhancements

- Simplified plugin panel to only title, imported filenames, icon controls, and real-time cursor mapping output.
- Removed editor top-bar/codelens mapping UI and command contributions for in-editor mapping banners.
- Updated spec preview generation to open rendered markdown table tabs and emit function/class hyperlinks in `file/symbol` format.
- Fixed invalid-link root and line-targeting bugs by resolving mapping roots from imported CSV location and finding symbol declaration lines via deterministic filesystem scan.
- Verification:
  - `npm run compile` -> pass
  - `npm run typecheck` -> pass
  - `npm test` -> `8 passed`
  - Manual GUI walkthrough with recording + screenshot confirmed all five requested behaviors.

## Current Task: Fix desktop-app dependency startup failure

- [x] Reproduce the dependency/startup error in `desktop-app`.
- [x] Identify the smallest viable dependency/config change to fix startup.
- [x] Apply minimal patch and avoid unrelated code changes.
- [x] Reinstall/sync dependencies and run desktop app until startup succeeds.
- [x] Document root cause, fix, and verification.

## Current Task Review: Fix desktop-app dependency startup failure

- Root causes found:
  - `@vitejs/plugin-react@6` is incompatible with `vite@6` and caused `ERR_PACKAGE_PATH_NOT_EXPORTED`.
  - Electron startup scripts were treated as ESM under `"type": "module"` and initially failed on CommonJS `require`.
  - Shell-level `ELECTRON_RUN_AS_NODE=1` forced Electron to run as Node, causing `app.whenReady` to be undefined.
  - CSS import ordering triggered a Vite/PostCSS startup error.
- Minimal fixes applied in `desktop-app`:
  - Pinned `@vitejs/plugin-react` to `^5.1.0` (compatible with `vite@6`).
  - Switched Electron entry files to CommonJS (`main.cjs`, `preload.cjs`) and updated references.
  - Added `scripts/electron-dev.cjs` to spawn Electron with `ELECTRON_RUN_AS_NODE` removed from env.
  - Reordered imports in `src/index.css` so Google Fonts `@import` precedes Tailwind import.
- Verification:
  - `npm install` completed successfully and lockfile updated.
  - `npm run electron:dev` stays running with Vite ready and no prior dependency/runtime startup errors; run was intentionally terminated after verification window.
## Current Task: Implement Step Titles + Toggleable Deterministic Checks

- [x] Add human-readable summary titles to every item in `docs/implement-checks-execution-order.md`.
- [x] Add step-level deterministic check toggles to implement config parsing with backward compatibility defaults.
- [x] Reorganize step-specific implement config fields to `implement.{step_title}.{field_name}` structure where applicable.
- [x] Update schema/example/workspace config and adjust tests.
- [x] Run targeted tests in conda env `Local` and report results.

## Current Task Review: Implement Step Titles + Toggleable Deterministic Checks

- Updated `docs/implement-checks-execution-order.md` with short summary titles and explicit `implement.{step_title}.enabled` keys for execution-order steps (including v0.0.1 planned checks).
- Added deterministic step-toggle parsing in `handlers/implement/config.py` under `impl["steps"]` with defaults enabled and backward-compatible fallback to flat keys.
- Wired runtime gating in implement orchestration/execution:
  - workset + module catalog validation toggles with deterministic relaxed fallback paths;
  - planner/implement semantic validation toggles and step-scoped retry values;
  - plan/contract/batch/brief validation toggles;
  - patch constraints, verification command resolution, patch normalization, patch apply gate, and verification execution toggles.
- Reorganized one-step fields into step-scoped config (while keeping flat aliases):
  - `implement.contract_field_consistency_validation.field_match_score_threshold`
  - `implement.planner_semantic_validation.semantic_validation_retries`
  - `implement.implement_semantic_validation.semantic_validation_retries`
- Updated config files and schema:
  - `config/config.schema.json`
  - `config/config.example.yaml`
  - `dataset/nutrition/config.yaml`
- Added tests for new config shape and parser behavior:
  - `tests/test_config_loader.py`
  - `tests/test_implement_handler.py`
- Verification:
  - `$env:PYTHONPATH='.'; conda run -n Local python -m pytest tests/test_config_loader.py tests/test_implement_handler.py tests/test_implement_execution.py -q` -> `92 passed`

## Current Task: Agent-Scoped Implement Config Fields

- [x] Move single-agent implement fields under `implement.unified_planner.*` and `implement.implementer.*` with compatibility fallback.
- [x] Update implement config parser and keep downstream runtime behavior unchanged.
- [x] Update config schema and example/dataset configs for new agent-scoped structure.
- [x] Add/adjust tests for parser + schema validation.
- [x] Run targeted tests in conda env `Local` and record results.

## Current Task Review: Agent-Scoped Implement Config Fields

- Added agent-scoped implement config support:
  - `commands.implement.implementer.prompt_name`
  - `commands.implement.unified_planner.prompt_name`
  - planner-only policy fields under `commands.implement.unified_planner.*`:
    - `disallowed_link_kinds_by_required_role`
    - `leaf_dependency_roles`
    - `leaf_dependency_policy`
    - `contract_kind_definitions`
    - `type_shape_match`
    - `min_confidence_threshold`
- Kept backward compatibility in parser:
  - top-level `prompt_name`, `unified_planner_prompt_name`, and planner-policy flat keys still work as fallback aliases.
- Updated schema/configs:
  - `config/config.schema.json`
  - `config/config.example.yaml`
  - `dataset/nutrition/config.yaml`
- Added/updated tests:
  - `tests/test_config_loader.py` (agent-scoped schema validation)
  - `tests/test_implement_handler.py` (agent-scoped parser behavior)
- Verification:
  - `$env:PYTHONPATH='.'; conda run -n Local python -m pytest tests/test_config_loader.py tests/test_implement_handler.py tests/test_implement_execution.py -q` -> `94 passed`

## Current Task: Implement v0.0.1 Checks and Enable Them

- [x] Implement intra-spec behavior conflict validation.
- [x] Implement required-field coverage validation.
- [x] Implement match ambiguity/tie validation with manual-resolution blocking.
- [x] Implement dependency-context edge consistency validation.
- [x] Wire the checks into `run_implement` in execution order and keep them enabled by default.
- [x] Add/adjust tests and run targeted suites in conda env `Local`.

## Current Task Review: Implement v0.0.1 Checks and Enable Them

- Implemented new deterministic validations in `handlers/implement/validation.py`:
  - `_validate_intra_spec_behavior_conflicts`
  - `_validate_required_field_coverage`
  - `_validate_match_ambiguity`
  - `_validate_dependency_context_edges`
- Updated `run_implement` orchestration (`handlers/implement/impl.py`) so v0.0.1 checks run in order with active gating:
  - intra-spec conflict: fail run on conflict
  - required field coverage: fail run on missing explicit/alias coverage
  - match ambiguity: create manual-resolution block items
  - dependency-context edge check: fail run on context mismatch
- Kept checks enabled by default via step toggles (`implement.<step>.enabled` defaults true) and retained explicit `enabled: true` in dataset config.
- Updated exports and docs:
  - `handlers/implement/__init__.py`
  - `docs/implement-checks-execution-order.md` (v0.0.1 items no longer marked planned)
  - `config/config.example.yaml` comments updated to active state.
- Verification:
  - `$env:PYTHONPATH='.'; conda run -n Local python -m pytest tests/test_implement_handler.py tests/test_implement_execution.py tests/test_config_loader.py -q` -> `98 passed`

## Current Task: Reduce Semantic Violations from Blank-Context Diff Hunks

- [x] Add deterministic patch normalizer that strips whitespace-only context lines in unified hunks and rewrites hunk counts.
- [x] Wire fallback normalization into semantic apply-check so semantic retries are avoided when patch is fixable.
- [x] Add regression tests for blank-context mismatch acceptance and non-applicable patch rejection stability.
- [x] Run targeted tests in conda env `Local`.
- [x] Run non-dry-run implement debug loop (`dataset/nutrition`, `--codebase-dir src`) and capture outcome.

## Current Task: Planner Missed Intentional date_range Mismatch (Nutrition Implement)

- [ ] Reproduce recent `implement` run behavior for `dataset/nutrition` and capture planner artifacts.
- [ ] Inspect unified planner input context (spec rows, links, contracts) for `A1049` and `A1057`.
- [ ] Identify exact stage where mismatch should be surfaced and why it currently is not.
- [ ] Validate root cause with code-path and run evidence.
- [ ] Document bug, solution options, and verification in review notes.


## Current Task Review: Reduce Semantic Violations from Blank-Context Diff Hunks

- Implemented deterministic semantic apply-check recovery in `handlers/implement/semantic_guard.py`:
  - strips whitespace-only hunk context lines and recomputes hunk counts,
  - retries apply-check with additional one-sided context trims (`leading`/`trailing`) when needed,
  - persists normalized patch only when `git apply --check` passes.
- Added regression coverage in `tests/test_implement_execution.py`:
  - `test_semantic_guard_normalizes_blank_context_hunk_mismatch`.
- Verification:
  - `conda run -n Local python -m pytest tests/test_implement_execution.py::ImplementExecutionPatchApplySemanticGuardTests -q` -> `3 passed`
  - `conda run -n Local python -m pytest tests/test_implement_execution.py -q` -> `39 passed`
  - `conda run -n Local python -m pytest tests/test_implement_handler.py -q` -> `53 passed`
- Non-dry-run debug loop run:
  - `conda run -n Local python cli.py agent implement --project-root dataset/nutrition --codebase-dir src`
  - run_id `20260312_225137_m0700` -> `failed`, reason `execute_exception_B0`.
  - B2 semantic retries recovered and completed; B0/B1 still exhausted semantic retries with non-applicable OBS patch hunks (`metrics_recorder.py`, `structured_logger.py`, `test_telemetry.py`).

## Current Task: Continue Implement Debug Loop (Semantic Apply Whitespace Mismatch)

- [x] Add deterministic semantic/apply fallback for whitespace-only context mismatches (`git apply --check --ignore-space-change`).
- [x] Ensure actual apply path uses same fallback semantics so semantic-pass patches do not fail later at apply.
- [x] Add regression tests for whitespace-mismatch patch applicability in semantic guard and apply pipeline.
- [x] Run targeted tests in conda env `Local`.
- [x] Run next non-dry-run implement debug iteration and capture run status + artifacts.

## Current Task Review: Continue Implement Debug Loop (Semantic Apply Whitespace Mismatch)

- Implemented additional semantic/apply resilience:
  - `handlers/implement/semantic_guard.py`: semantic apply-check now accepts already-applied diffs via reverse-check fallback and supports whitespace fallback in check helper.
  - `handlers/implement/execution.py`: `_apply_and_verify` now skips already-applied patches (worktree/root check) instead of failing, with explicit `patch_already_applied_skip` records.
  - `handlers/implement/impl.py`: parallel execute failure path now persists `details` into `summary.json`.
- Added regression tests:
  - `tests/test_implement_execution.py::ImplementExecutionPatchApplySemanticGuardTests::test_semantic_guard_accepts_patch_when_change_is_already_applied`
  - `tests/test_implement_execution.py::ImplementExecutionWorktreeScopeTests::test_apply_and_verify_skips_patch_when_change_is_already_applied`
- Verification:
  - `conda run -n Local python -m pytest tests/test_implement_execution.py::ImplementExecutionPatchApplySemanticGuardTests -q` -> `5 passed`
  - `conda run -n Local python -m pytest tests/test_implement_execution.py::ImplementExecutionWorktreeScopeTests -q` -> `8 passed`
  - `conda run -n Local python -m pytest tests/test_implement_handler.py -q` -> `53 passed`
- Debug-loop runs (cap reached: 3):
  - `20260313_113031_m0700`: failed `execute_exception_B4` (post-whitespace fix, B0 recovered).
  - `20260313_123100_m0700`: failed `execute_exception_B1`, stderr showed semantic retry exhaustion for B1.
  - `20260313_125309_m0700`: failed `execute_exception_B1` with explicit details: local provider `http 429 usage_limit_reached` (external quota blocker).

## Current Task: Debug Implement (User Request 2026-03-13)

- [x] Reproduce `implement` failure with required non-dry-run command.
- [x] Collect deterministic evidence (stderr, summary.json, run_meta.json, implement log).
- [x] Identify root cause and implement minimal fix.
- [x] Verify with targeted tests and one rerun (within run cap).
- [x] Document bug/solution/verification in task review.

## Current Task Review: Debug Implement (User Request 2026-03-13)

- Reproduced failures:
  - `python cli.py agent implement --project-root dataset/nutrition --codebase-dir src` failed immediately outside `Local` env (`ModuleNotFoundError: click`).
  - `conda run -n Local python cli.py agent implement --project-root dataset/nutrition --codebase-dir src` failed on config schema validation (`csv_contracts.design_spec.add_if_missing` missing `map_run_id`).
  - After config fix, rerun reached planner then failed with temp workspace ACL (`[WinError 5] Access is denied` for `%LOCALAPPDATA%\\Temp\\pika-local-agent-*`).
- Implemented fixes:
  - Added missing `map_run_id` contract column to `dataset/nutrition/config.yaml`.
  - Aligned fallback defaults in `config/pika.yaml` to include `map_run_id`.
  - Hardened `core/lifecycle.py` local temp workspace creation:
    - added access probe for created temp workspace,
    - added project-local fallback base `out/local_agent_temp` when primary temp base is inaccessible,
    - cleans up failed workspace candidates before fallback.
  - Added regression tests:
    - `tests/test_config_loader.py::ConfigLoaderImplementPolicyTests::test_nutrition_workspace_config_passes_schema_validation`
    - `tests/test_lifecycle.py::LocalAgentTempWorkspaceFallbackTests::test_create_workspace_falls_back_to_project_local_base_when_primary_inaccessible`
- Verification:
  - `conda run -n Local python -m pytest tests/test_lifecycle.py::LocalAgentTempWorkspaceFallbackTests::test_create_workspace_falls_back_to_project_local_base_when_primary_inaccessible tests/test_config_loader.py::ConfigLoaderImplementPolicyTests::test_nutrition_workspace_config_passes_schema_validation -q` -> `2 passed`
  - `conda run -n Local python -m py_compile core/lifecycle.py tests/test_lifecycle.py tests/test_config_loader.py` -> success
  - Implement rerun (3rd and final allowed in this cycle): run_id `20260313_204739_m0700` advanced past load/catalog into planner, then failed on temp workspace ACL before agent invocation.

## Current Task Review: Continue Debug Implement (User Request Follow-up 2026-03-13)

- Debug loop runs (cap 3 for this follow-up request):
  - `20260313_205501_m0700`: failed before planner invoke with ACL on fallback temp workspace directory (`out/local_agent_temp/...`).
  - `20260313_213357_m0700`: progressed to planner start; failed on unreadable source entry `src/.pytest_cache` during local workspace sync.
  - `20260313_213535_m0700`: progressed through local shared workspace creation + resync and reached `implement_unified_planner` local agent invoke; failed in external Codex runtime with session permission error (`C:\Users\CodexSandboxOffline\.codex\sessions`).

- Implemented platform fixes:
  - `core/lifecycle.py`:
    - Replaced temp workspace creation path with ACL-safe inherited directory creation (`Path.mkdir`) and retained fallback base selection.
    - Added explicit workspace access probe.
    - Hardened local workspace sync to skip unreadable source entries (warn + continue), preserving deterministic ordering.
  - Added tests:
    - `LocalAgentTempWorkspaceFallbackTests::test_create_workspace_falls_back_to_project_local_base_when_primary_inaccessible`
    - `SyncLocalAgentWorkspaceTests::test_sync_skips_unreadable_source_entry_and_copies_readable_entries`

- Verification:
  - `conda run -n Local python -m pytest tests/test_lifecycle.py::LocalAgentTempWorkspaceFallbackTests::test_create_workspace_falls_back_to_project_local_base_when_primary_inaccessible tests/test_lifecycle.py::SyncLocalAgentWorkspaceTests::test_sync_skips_unreadable_source_entry_and_copies_readable_entries -q` -> `2 passed`
  - `conda run -n Local python -m py_compile core/lifecycle.py tests/test_lifecycle.py` -> success

- Current blocker after fixes:
  - External local-provider runtime environment permissions for Codex session files (`C:\Users\CodexSandboxOffline\.codex\sessions`) and outbound model fetch errors (network/credentials/runtime), outside PIKA implement orchestration logic.
- Additional hardening (post-cap, not rerun yet in this cycle):
  - `core/agent_invoker.py`: local subprocess environment now sets `CODEX_HOME` to a writable directory under each local workspace (`<workspace>/.codex_home`) before invoking Codex.
  - Added regression test: `tests/test_agent_invoker.py::RunLocalExecSubprocessDecodeTests::test_non_stream_sets_writable_codex_home_env`.
  - Verification: `conda run -n Local python -m pytest tests/test_agent_invoker.py::RunLocalExecSubprocessDecodeTests::test_non_stream_sets_writable_codex_home_env tests/test_lifecycle.py::LocalAgentTempWorkspaceFallbackTests::test_create_workspace_falls_back_to_project_local_base_when_primary_inaccessible tests/test_lifecycle.py::SyncLocalAgentWorkspaceTests::test_sync_skips_unreadable_source_entry_and_copies_readable_entries -q` -> `3 passed`.

## Current Task Review: Continue Debug Implement (User Request Follow-up 2026-03-13, Cycle 2)

- Debug loop runs (cap 3 for this cycle):
  - `20260313_214002_m0700`: failed at unified planner local invoke due network disconnect errors to `api.openai.com`.
  - `20260313_214216_m0700` (escalated): failed at unified planner local invoke with explicit `401 Unauthorized` / missing bearer auth for models + responses endpoints.
  - `20260313_214416_m0700`: after fast-fail auth guard, run failed immediately with actionable auth message before long local-agent retries.

- Implemented fixes and hardening:
  - `core/lifecycle.py`:
    - Added fast-fail local auth precheck (`check_local_available(local_cmd)`) before local agent execution.
    - Emits deterministic actionable error: run `codex login status` / `codex login`.
  - `core/agent_invoker.py`:
    - Added `_build_local_exec_env` and set `CODEX_HOME=<workspace>/.codex_home` for local subprocesses to avoid host-home permission dependencies.
  - Existing cycle-1 hardening retained and verified:
    - ACL-safe local temp workspace creation.
    - Skip unreadable source entries during local workspace sync.

- Added/updated regression tests:
  - `tests/test_lifecycle.py::InvokeAgentLocalIsolationTests::test_invoke_agent_local_fails_fast_when_local_auth_unavailable`
  - `tests/test_agent_invoker.py::RunLocalExecSubprocessDecodeTests::test_non_stream_sets_writable_codex_home_env`
  - `tests/test_lifecycle.py::LocalAgentTempWorkspaceFallbackTests::test_create_workspace_falls_back_to_project_local_base_when_primary_inaccessible`
  - `tests/test_lifecycle.py::SyncLocalAgentWorkspaceTests::test_sync_skips_unreadable_source_entry_and_copies_readable_entries`

- Verification:
  - `conda run -n Local python -m pytest tests/test_lifecycle.py::InvokeAgentLocalIsolationTests::test_invoke_agent_local_fails_fast_when_local_auth_unavailable tests/test_agent_invoker.py::RunLocalExecSubprocessDecodeTests::test_non_stream_sets_writable_codex_home_env tests/test_lifecycle.py::SyncLocalAgentWorkspaceTests::test_sync_skips_unreadable_source_entry_and_copies_readable_entries -q` -> `3 passed`
  - `conda run -n Local python -m py_compile core/lifecycle.py core/agent_invoker.py tests/test_lifecycle.py tests/test_agent_invoker.py` -> success

- Current blocker:
  - External local-provider authentication state is missing (`codex login` not active for this environment), which blocks live planner/implement agent calls even after PIKA-side hardening.

## Current Task: Continue Debug Implement (User Request Follow-up 2026-03-13, Cycle 3)

- [x] Reproduce non-dry-run `implement` failure in Local env.
- [x] Collect run evidence (summary, run_meta, logs, stderr).
- [x] Implement minimal fix for first blocking root cause.
- [x] Verify with targeted tests.
- [x] Rerun implement within cycle cap and report Bug/Solution/Verification.

## Current Task Review: Continue Debug Implement (User Request Follow-up 2026-03-13, Cycle 3)

- Debug loop runs (cap 3 for this cycle):
  - raw shell reproduction: `python cli.py agent implement --project-root dataset/nutrition --codebase-dir src` failed pre-start with `ModuleNotFoundError: jsonschema` (base interpreter dependency gap).
  - Local env run: `conda run -n Local python cli.py agent implement --project-root dataset/nutrition --codebase-dir src` reached execution and failed `execute_exception_B0` due semantic patch apply invalidation.
  - Post-fix Local env run: advanced through many batches (`lifecycle_batch_executed` events for B0..B6) with no early `execute_exception_B0`; run was externally interrupted by shell timeout before final summary write.

- Implemented fix:
  - `handlers/implement/execution.py` now resolves `agent_artifacts_dir` per batch (`.../<run_id>/<batch_id>/`) instead of shared run-level dir during `_execute_batch`.
  - This removes cross-batch diff cleanup/overwrite interference during parallel semantic retry.

- Added regression coverage:
  - `tests/test_implement_execution.py::ImplementExecutionLocalWorkspaceTests::test_execute_batch_local_workspace_override_sets_prompt_codebase_dir`
    now asserts `template_vars["agent_artifacts_dir"]` is batch-scoped (`.../implement/<run_id>/B0`).

- Verification:
  - `conda run -n Local python -m pytest tests/test_implement_execution.py::ImplementExecutionLocalWorkspaceTests -q` -> `2 passed`
  - `conda run -n Local python -m pytest tests/test_implement_execution.py -q` -> `43 passed`
  - `conda run -n Local python -m py_compile handlers/implement/execution.py tests/test_implement_execution.py` -> success
  - Runtime evidence from `dataset/nutrition/out/logs/implement_20260313_224238_m0700.log` confirms deeper batch progression post-fix (multiple `lifecycle_batch_executed`) before timeout interruption.

## Current Task: Categorize Implement Findings by Problem Source + Add Skill

- [x] Map each previously reported artifact finding to owning batch/spec and responsible agent.
- [x] Cross-reference deterministic checks using `docs/implement-checks-execution-order.md` and identify misses.
- [x] Create new skill `implement-problem-sourcing` in local and user skill registries.

## Current Task Review: Categorize Implement Findings by Problem Source + Add Skill

- Built source attribution from run `20260313_224238_m0700` artifacts (`batch_plan.json`, `unified_plan.json`, `agent_outputs/implement_B*.json`, `trace/trace.jsonl`, validation json outputs).
- Mapped failures to primary sources: planner contract modeling vs batch implementer behavior, with explicit check-index references for misses.
- Added skill `implement-problem-sourcing` at:
  - `.codex/skills/implement-problem-sourcing/SKILL.md`
  - `%USERPROFILE%/.codex/skills/implement-problem-sourcing/SKILL.md`

## Current Task: Fix preflight support for `refine`

- [x] Reproduce and locate preflight command support failure for `refine`.
- [x] Apply minimal safety validation updates to support `refine`.
- [x] Add regression test coverage for `refine` preflight support.
- [x] Run targeted tests and verify `agent refine` no longer fails preflight with unsupported-command error.
- [x] Document root cause, fix, and verification.

## Current Task Review: Fix preflight support for `refine`

- Root cause: `refine` existed in CLI/dispatch but was missing from `core/safety.py` supported-command gate (`_run_step_7_unsupported_command`), which caused deterministic preflight failure before execution.
- Minimal fix:
  - Added `refine` to preflight supported commands.
  - Included `refine` in safety input-path resolution and design-spec CSV contract validation paths.
  - Included `refine` in project-context preflight contract scope to align with `run_refine` runtime behavior.
- Regression coverage:
  - Added `test_preflight_refine_command_is_supported` to `tests/test_command_router.py`.
- Verification:
  - `conda run -n Local python -m pytest tests/test_command_router.py -q` -> `13 passed`.
  - CLI smoke run no longer reports `Unsupported command for safety validation: refine`; next validation now proceeds to actual config requirements.

## Current Task: Make `dataset/nutrition/config.yaml` pass refine preflight

- [x] Add minimal `commands.refine` config block with required inputs.
- [x] Ensure block matches config schema for refine outputs.
- [x] Validate preflight directly via `validate_command_preconditions`.
- [x] Validate via CLI run that no preflight error is raised.

## Current Task Review: Make `dataset/nutrition/config.yaml` pass refine preflight

- Added `commands.refine` with:
  - `inputs.design_spec_path: state/DESIGN-SPEC.csv`
  - `inputs.project_context_filename: PROJECT_CONTEXT.md`
  - schema-valid `outputs` keys only (`root_dir`, `agent_runs_dir`, `design_spec_path`).
- Verification:
  - `conda run -n Local python -c "... validate_command_preconditions('refine', ...) ..."` -> `PREFLIGHT_OK`.
  - `conda run -n Local python cli.py agent refine --project-root dataset/nutrition --config config.yaml --dry-run` -> command executed and returned `status: blocked` (no preflight failure).
## Current Task: Plugin Codex Executable Detection + Readiness UI

- [x] Add plugin runtime state/schema for Codex executable readiness and path source.
- [x] Implement startup auto-detection of `codex` executable (configured path first, PATH/common locations fallback).
- [x] Add manual configure action from webview (button -> file picker -> save path -> re-validate).
- [x] Render panel readiness indicator (`ready` vs `not configured`) and conditional configure button.
- [x] Add targeted unit tests for executable detection helper and run plugin checks.
- [x] Commit and push the feature branch changes.

## Current Task Review: Plugin Codex Executable Detection + Readiness UI

- Added deterministic Codex executable detection helper for configured path validation plus auto-scan across `PATH` and common install directories.
- Extended extension state and webview payload contracts with `codexRuntime` readiness metadata and wired launch-time refresh.
- Added panel UI readiness badge, codex details text, and conditional `Configure Codex Path` button when runtime is missing.
- Added manual path-configuration flow in extension host (file picker -> settings update -> runtime re-validation -> panel refresh).
- Verification:
  - `npm run compile` -> pass
  - `npm run typecheck` -> pass
  - `npm test` -> `16 passed`
  - Manual GUI walkthrough recorded: `plugin_codex_detection_ready_transition.mp4` (Not ready + configure button -> Ready after selecting `/tmp/codex-demo/codex`).

## Current Task: Plugin Mapping In-Progress Indicator + Mock Async Delay

- [x] Add extension/webview state fields representing mapping run-in-progress status.
- [x] Add fixed async delay in extension mapping execution path to simulate running state.
- [x] Render UI indicator while mapping is running and disable conflicting actions.
- [x] Add/adjust tests for mapping-running state helpers where feasible.
- [x] Run plugin compile/typecheck/tests and manual GUI walkthrough with recording.
- [ ] Commit and push branch updates.

## Current Task Review: Plugin Mapping In-Progress Indicator + Mock Async Delay

- Added `mappingRuntime` state contract and store support so extension host can publish mapping progress (`isRunning`, message, lastStartedAt) to webview.
- Added deterministic mock mapping delay (`MOCK_MAPPING_EXEC_DELAY_MS=5000`) and wrapped import/refresh execution in `runMappingWithRuntime` so panel status transitions `Idle -> Running... -> Idle`.
- Added panel mapping status badge/details and disabled import/refresh buttons while mapping is running.
- Added unit tests for runtime delay helper behavior using fake timers.
- Verification:
  - `npm run compile` -> pass
  - `npm run typecheck` -> pass
  - `npm test` -> `17 passed`
  - Manual GUI walkthrough recorded: `plugin_mapping_running_status_refresh.mp4` (refresh shows `Running...` then returns to `Idle`).

## Current Task: Codex Validation Status + Readiness-Gated Refresh

- [x] Add codex validation runtime state contract (`isValidating`, progress message) in extension/webview.
- [x] Add stubbed handshake validation flow with real-time progress updates and stale-run protection.
- [x] Gate readiness so `ready` is set only after validation pass; hide validation status when idle.
- [x] Disable refresh button when agent is not ready and enforce host-side guard.
- [x] Add/adjust targeted tests and run compile/typecheck/tests.
- [x] Run manual GUI walkthrough recording proving validation progress + refresh disable behavior.
- [ ] Commit and push changes.

## Current Task Review: Codex Validation Status + Readiness-Gated Refresh

- Added `codexValidationRuntime` state contract and propagation in extension/webview payloads to represent active handshake progress.
- Implemented stubbed validation module with deterministic progress steps and stale-run protection in `refreshCodexRuntimeStatus`.
- Updated readiness flow so runtime remains not-ready during validation and transitions to ready only on validation pass; validation row is rendered only while validating.
- Disabled refresh button when agent is not ready and added host-side guard in `refreshMappings` to reject non-ready runs.
- Added unit tests for validation step progress helper and re-ran plugin checks.
- Verification:
  - `npm run compile` -> pass
  - `npm run typecheck` -> pass
  - `npm test` -> `18 passed`
  - Manual GUI walkthrough recorded: `plugin_codex_validation_and_readiness_gating.mp4` (not-ready refresh disabled -> validation progress shown -> ready after pass).

## Current Task: Code Directory Configure Button + Workspace-Scoped Selection

- [x] Add extension/webview state for effective code directory path.
- [x] Add settings + runtime resolution so default code directory is workspace root.
- [x] Add `Configure Code Directory` button and current path display in panel.
- [x] Implement folder picker flow that only accepts directories inside workspace root.
- [x] Add targeted helper tests for workspace path scoping and default resolution.
- [x] Run plugin compile/typecheck/tests and manual GUI walkthrough recording.
- [x] Commit and push changes.

## Current Task Review: Code Directory Configure Button + Workspace-Scoped Selection

- Added workspace-scoped code directory resolver helpers with inside-parent checks and workspace-root fallback defaults.
- Added `designSpecMapper.codeDirectory` config setting and extension runtime/state propagation for effective code directory.
- Added `Configure Code Directory` panel button and `Code directory` display, including folder-picker flow and inside-workspace guardrails.
- Updated mapping root resolution to use effective code directory and kept preview output files under workspace root.
- Added unit tests for code-directory normalization/containment/default resolution and re-ran plugin checks.
- Verification:
  - `npm run compile` -> pass
  - `npm run typecheck` -> pass
  - `npm test` -> `23 passed`
  - Manual GUI walkthrough recorded showing default root and update to inside-workspace directory.

## Current Task: Document Import Column + Double-Click Quick Open

- [x] Replace prior design-spec-only import affordance with a 3-row document import column.
- [x] Add rows for Design Spec, Issue Tracking Sheet, and Testing Plan, each with right-side Import button.
- [x] Add double-click quick-open action on each row bar when the document is imported.
- [x] Add extension host message handlers and state fields for issue/testing document paths.
- [x] Run compile/typecheck/tests and manual GUI walkthrough recording.
- [x] Commit and push changes.

## Current Task Review: Document Import Column + Double-Click Quick Open

- Added a dedicated `Documents` column in plugin panel with three rows (`Design Spec`, `Issue Tracking Sheet`, `Testing Plan`) and per-row `Import` buttons.
- Added webview/extension message flow for importing issue/testing documents and double-click quick-open actions for all three document rows.
- Extended extension/webview state contracts and state store to carry imported issue/testing file paths.
- Kept mapping refresh control in toolbar while removing the old top-level design-spec import button from the header.
- Verification:
  - `npm run compile` -> pass
  - `npm run typecheck` -> pass
  - `npm test` -> `23 passed`
  - Manual GUI walkthrough recorded: `plugin_document_column_import_and_quick_open.mp4`.

## Current Task: Adaptive Document Row Layout for Narrow Panel Width

- [x] Add left icons on each document bar in Documents column.
- [x] Add responsive layout breakpoint that hides document labels/path text when panel width is narrow.
- [x] Keep document bar and import button usable in compact mode.
- [x] Run plugin compile/typecheck/tests.
- [x] Run manual GUI walkthrough recording demonstrating compact behavior.
- [ ] Commit and push changes.

## Current Task Review: Adaptive Document Row Layout for Narrow Panel Width

- Added left document icons (`DS`, `IT`, `TP`) inside each document bar and grouped text into a label container.
- Added responsive compact breakpoint for document rows so label/path text collapses while icon + Import button remain visible.
- Preserved document row quick-open and Import button interactions in both regular and compact states.
- Verification:
  - `npm run compile` -> pass
  - `npm run typecheck` -> pass
  - `npm test` -> `23 passed`
  - Manual GUI walkthrough recorded for wide/narrow panel behavior.

## Current Task: Plan Validation-Use Dataset Construction

- [x] Read project-level rules, prior lessons, and the SADS drafting skill.
- [x] Inspect the nutrition dataset package structure, design-spec scale, and appendix usage.
- [x] Draft a reusable plan for new medical-software validation datasets, including required artifacts, schemas, edge cases, and milestones.
- [x] Call out open questions where the repo conventions or request leave dataset construction details ambiguous.

## Current Task Review: Plan Validation-Use Dataset Construction

- Established the nutrition dataset baseline to mirror:
  - `PROJECT_CONTEXT.md` as the dataset-level project brief.
  - `state/DESIGN-SPEC.csv` as a 19-column SADS contract with 63 rows across `UI`, `API`, `CORE`, `DATA`, `SHARED`, and `OBS`.
  - `appendix_config_proposals.csv` as the existing appendix example with 29 configurable-item rows.
- Drafted a reusable construction plan for future validation datasets that keeps the same scale and drafting style while expanding appendix coverage to include configurable items, error-code dictionaries, optional data-flow diagrams, optional DTO definitions, and other domain-heavy references.
- Identified the main ambiguity to confirm before actual dataset authoring:
  - whether the new artifact should be named `project.md` or follow the existing repo convention `PROJECT_CONTEXT.md`.

## Current Task: Select Dataset Batch + Draft Per-Dataset Plans

- [x] Incorporate user clarifications on artifact naming and allowed architecture diversity.
- [x] Select a small dataset batch sized for nutrition-level quality within current context limits.
- [x] Draft a slightly more detailed plan for each selected dataset before dataset generation starts.

## Current Task Review: Select Dataset Batch + Draft Per-Dataset Plans

- Chose a three-dataset first batch as the quality-safe scope for this turn series:
  - one UI-facing medical workflow dataset,
  - one non-UI / non-REST integration dataset,
  - one data-facing batch-processing dataset.
- Locked the naming convention to the repo-standard `PROJECT_CONTEXT.md`.
- Drafted per-dataset plans with concrete user stories, module roles, workflow buckets, expected row budgets, and appendix sets before any dataset generation begins.

## Current Task: Create `qc_run_release` Validation Dataset

- [x] Scaffold the new dataset directory in the existing dataset package shape.
- [x] Author `PROJECT_CONTEXT.md`, `vocab.yaml`, `config.yaml`, and appendix files.
- [x] Author a nutrition-scale raw design spec for the QC run review and release workflow.
- [x] Run deterministic `format` in the `Local` conda environment to generate canonical state artifacts.
- [x] Verify appendix loading through the backend appendix loader and fix malformed CSV rows.

## Current Task Review: Create `qc_run_release` Validation Dataset

- Created `dataset/qc_run_release` with:
  - `PROJECT_CONTEXT.md`
  - `vocab.yaml`
  - `config.yaml`
  - `raw-design-spec.csv`
  - `appendix_config_proposals.csv`
  - `appendix_error_codes.csv`
  - `appendix_dto_definitions.csv`
  - `appendix_data_flow.md`
  - `state/DESIGN-SPEC.csv`
  - `state/id_registry.json`
- Authored 64 SADS rows for a laboratory QC run review/release product spanning `UI`, `API`, `CORE`, `DATA`, `SHARED`, and `OBS`.
- Verification:
  - `conda run -n Local python .\\cli.py agent format --project-root ..\\dataset\\qc_run_release --config config.yaml` -> `status: completed`
  - PowerShell CSV import checks confirmed `64` raw and canonical design-spec rows, `29` config appendix rows, and `15` error-code appendix rows.
  - Backend appendix loader resolved `55` appendix entries for `implement` after fixing malformed CSV notes fields.

## Current Task: Add Validation Dataset Forecast Skill

- [x] Review project lessons and the `skill-creator` guidance.
- [x] Scaffold a new reusable skill in the default user skill registry.
- [x] Author the skill so it covers dataset creation and agent-output prediction from spec concreteness without run artifacts.
- [x] Validate the skill folder and record the result.

## Current Task Review: Add Validation Dataset Forecast Skill

- Created a new user-global skill at `C:\Users\night\.codex\skills\validation-dataset-forecast`.
- Wrote the skill to cover:
  - validation dataset package creation,
  - spec-concreteness assessment,
  - refine forecast heuristics,
  - implement forecast heuristics,
  - guardrails against using implementation details or run artifacts for forecast-only requests.
- Corrected the generated `agents/openai.yaml` default prompt and fixed quoted YAML frontmatter in `SKILL.md`.
- Verification:
  - `C:\Users\night\miniconda3\envs\Local\python.exe C:\Users\night\.codex\skills\.system\skill-creator\scripts\quick_validate.py C:\Users\night\.codex\skills\validation-dataset-forecast` -> `Skill is valid!`

## Current Task: Move Validation Dataset Forecast Skill To Project Scope

- [x] Record the correction that repo-derived skills should default to project scope.
- [x] Copy the validated skill into project-level `.codex/skills`.
- [x] Add project-level Claude and Cursor equivalents.
- [x] Remove the user-global copy and validate the repo-level Codex skill.

## Current Task Review: Move Validation Dataset Forecast Skill To Project Scope

- Moved the skill into the repository at `.codex/skills/validation-dataset-forecast`.
- Added Claude project guidance at:
  - `.claude/skills/validation-dataset-forecast.md`
  - `.claude/CLAUDE.md` project-skills reference
- Added Cursor project guidance at:
  - `.cursor/skills/validation-dataset-forecast/SKILL.md`
  - `.cursor/rules/Validation-Dataset-Forecast.mdc`
- Removed the user-global copy from `C:\Users\night\.codex\skills\validation-dataset-forecast`.
- Verification:
  - `C:\Users\night\miniconda3\envs\Local\python.exe C:\Users\night\.codex\skills\.system\skill-creator\scripts\quick_validate.py .\.codex\skills\validation-dataset-forecast` -> `Skill is valid!`
  - Presence check confirmed the project-level Codex, Claude, and Cursor files exist and the user-global copy is absent.
