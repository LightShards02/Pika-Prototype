# Implement Command Checks In Execution Order

1. `[v0.0.0][deterministic]` **Normalize Implement Config** (`implement.config_normalization`): Parse and normalize implement configuration (roles, policies, thresholds, retries, budgets).
   a. Read config from CLI flags and config files.
   b. Fill in defaults for missing values and normalize types.
   c. Validate preflight constraints (e.g. `budgets.max_files >= pika.implement.min_max_files`).
   d. Produce one clean config object that every later step uses.
   e. Produces no file.

2. `[v0.0.0][deterministic]` **Validate Workset Rows** (`implement.workset_schema_validation.enabled`): Load design spec workset and enforce required columns/values (`spec_id`, `module_tag`, `module_role`).
   a. Load workset rows from the design-spec source.
   b. Check required columns exist and required fields are not empty.
   c. Stop early with clear row-level errors if schema rules fail.
   d. Produces: `workset.json`.

3. `[v0.0.0][deterministic]` **Validate Module Catalog Roles** (`implement.module_catalog_validation.enabled`): Build module catalog and enforce module-role consistency plus allowed role set.
   a. Build a module catalog from available specs/modules.
   b. Verify each module role is valid and consistent across rows.
   c. Reject unknown or conflicting role assignments.
   d. Produces: `module_catalog.json`.

4. `[v0.0.0][deterministic]` **Prepare Planner Path Contract** (`implement.planner_path_contract_prep.enabled`): Build planner path contract and directory snapshot used as path constraints for planning.
   a. Scan the codebase paths that planning is allowed to touch.
   b. Create a path contract describing allowed and blocked locations.
   c. Store a directory snapshot so later checks can compare planner output.
   d. Produces no file.

5. `[v0.0.0][agent]` **Run Unified Planner Agent** (`implement_unified_planner`): Invoke unified planner agent with schema retry loop.
   a. Send normalized inputs and constraints to the planner agent.
   b. Parse the returned JSON against the planner output schema.
   c. Retry agent generation if schema validation fails.
   d. Produces: `unified_plan.json`, `module_plans/{tag}.json`, `spec_issues.json`.

6. `[v0.0.0][deterministic]` **Validate Planner Path Semantics** (`implement.planner_semantic_validation.enabled`): Validate unified planner semantic path constraints on each planner attempt (retry on violation).
   a. Check planned file paths against the prepared path contract.
   b. Ensure path semantics match project rules (scope, ownership, allowed roots).
   c. Trigger a planner retry when semantic violations are found.
   d. Produces no file.

7. `[v0.0.0][deterministic]` **Gate Manual Resolution Items** (`implement.planner_manual_resolution_gate.enabled`): Block on planner-produced `manual_resolution_items` when present.
   a. Inspect planner output for `manual_resolution_items`.
   b. If any are present, stop automatic execution.
   c. Return a clear list so a human can resolve blockers first.
   d. Produces: `manual_resolution/{stage}.json`, `manual_resolution/resolutions.yaml` (when blocked).

   > **Placement rationale:** The planner output schema is `oneOf` — it produces *either* `manual_resolution_items` *or* a valid plan (`module_plans`, `spec_dependencies`, etc.). If the planner chose the manual-resolution branch, no plan object exists and steps 8+ would operate on missing data. This gate must run before any plan-dependent validation.
   >
   > `(planning)` **Insert after step 7 and reuse after any non-successful exit from steps 18-26: Write Round Handoff Packet.** Persist a compact handoff artifact for retries and resumes containing: what changed, what failed, resolved decisions already accepted, strategies that should not be retried, remaining risks, and the next exact objective. This keeps later agent rounds clean-slate and prevents raw-log replay from becoming the only state transfer mechanism.

8. `[v0.0.3][deterministic]` **Gate Spec Consistency Issues** (`implement.spec_issue_escalation.enabled`): Escalate all planner-detected `spec_issues` to blocking `manual_resolution_items`.
   a. Iterate all `spec_issues` from the planner output (kinds: `contradiction`, `overlap`, `dependency_gap`, `ambiguity`, `orphan_reference`).
   b. Convert each issue to a blocking `manual_resolution_item` with a kind-specific `blocking_reason`.
   c. Block execution if any spec issues are present; human must resolve before re-running.
   d. Produces: `manual_resolution/{stage}.json`, `manual_resolution/resolutions.yaml` (when blocked).

9. `[v0.0.3][deterministic]` **Validate Unified Plan Structure** (`implement.unified_plan_validation.enabled`): Run unified plan structural validation with differentiated failure handling.
   a. Check that every workset `spec_id` appears in at least one `planned_anchor` — **retry planner** if not.
   b. Validate `spec_dependencies` form a DAG via spec-level DFS cycle detection — **produce `manual_resolution_items`** with cycle path if cycle found (no suggested fix; human must break the cycle).
   c. Verify all `spec_id`s referenced in `spec_dependencies` exist in the workset — **retry planner** if unknown refs found.
   d. Confirm every module in the catalog has a corresponding `module_plan` — **retry planner** if missing.
   e. Retryable failures (a, c, d) share the planner retry counter with steps 5/6.
   f. Produces: `plan_validation.json`.

10. `[v0.0.3][deterministic]` **Validate Contract Field Naming Alignment** (`implement.contract_field_consistency_validation.enabled`): Run naming-alignment and alias-ambiguity validation between all consumed spec text and shared contract fields. No provider/consumer distinction — every consumed spec is checked uniformly.
    a. Read shared contracts and all consumed spec text together.
    b. For each consumed spec, verify field names align using fuzzy matching (Damerau-Levenshtein, threshold configurable). Emit blocking `manual_resolution_items` for near-miss field name mismatches.
    c. Check structural metadata: duplicate field names and missing `nullable` booleans.
    d. Detect near-equal candidate ties: when two spec words score within 0.03 of each other against the same contract field, emit blocking `manual_resolution_items` for human clarification.
    e. Produces: `contract_field_validation.json`.

11. `[v0.0.3][deterministic]` **Check Required Contract Coverage** (`implement.required_field_coverage_validation.enabled`): Enforce explicit or alias-resolved field coverage for consumed contract fields. Provider-only: only specs listed in `provider_spec_ids` are checked.
    a. For each shared contract, read `provider_spec_ids` — the explicit list of spec IDs (including APX-prefixed appendix IDs) that define/own this contract.
    b. If a provider is an APX ID, verify it exists in loaded appendices; if valid, trust it as an authoritative provider (skip field-by-field check).
    c. If no provider spec exists, emit `manual_resolution_items` (always manual_block).
    d. If provider text contains canonical contract/DTO declaration, treat coverage as satisfied.
    e. Otherwise check field-by-field coverage (exact, normalized, part matching). Emit `manual_resolution_items` for uncovered fields listing which fields are missing from which provider spec.
    f. Produces: `required_field_coverage_validation.json`.

    > **Distinction from step 10:** Step 10 checks *naming alignment* (are field names consistent between contract and spec text?) across all consumed specs uniformly. Step 11 checks *coverage completeness* (does the provider spec reference every field it's supposed to define?) against provider specs only.

12. `[v0.0.0][deterministic]` **Construct Batch Plan** (`implement.batch_plan_construction.enabled`): Build graph-aware batch plan from spec dependencies and budgets.
    a. Use dependency order to group specs into execution batches.
    b. Respect configured budgets and retry/resource limits.
    c. Output an ordered batch plan for downstream execution.
    d. Produces: `batch_plan.json`.

13. `[v0.0.0][deterministic]` **Validate Batch Dependencies** (`implement.batch_plan_dependency_validation.enabled`): Validate batch plan dependencies (known dependency IDs, unique spec assignment, reachable provider paths).
    a. Confirm dependency IDs in batches are known and valid.
    b. Ensure each spec appears in exactly one batch assignment.
    c. Verify provider/runtime paths needed by each batch are reachable.
    d. Produces: `batch_plan_validation.json`.

14. `[v0.0.0][deterministic]` **Build Batch Briefs** (`implement.batch_brief_build.enabled`): Build batch briefs (`spec_rows`, `planned_anchors`, `shared_contracts`, `spec_dependency_context`, `constraints`).
    a. Assemble concise execution context for each batch.
    b. Include only needed specs, anchors, contracts, and constraints.
    c. Produce deterministic brief payloads for the implementer agent.
    d. Produces: `batch_briefs/B{n}.json`.

15. `[v0.0.0][deterministic]` **Validate Brief Scope** (`implement.batch_brief_scope_validation.enabled`): Validate brief scoping (no out-of-batch `spec_ids` or `consumed_by_specs` leakage).
    a. Inspect every brief object for cross-batch leakage.
    b. Confirm `spec_ids` and `consumed_by_specs` stay in batch scope.
    c. Fail fast if any out-of-batch references are detected.
    d. Produces: `brief_validation.json`.

16. `[v0.0.1][deterministic]` **Check Dependency Context Edges** (`implement.dependency_context_edge_validation.enabled`): Validate that brief dependency-context edges exactly match planner dependencies.
    a. Compare brief dependency edges with planner-approved dependencies.
    b. Ensure no missing edges and no extra edges exist.
    c. Stop if dependency context drifts from the plan contract.
    d. Produces: `dependency_context_edge_validation.json`.

    > `(planning)` **Insert after step 16: Construct Batch Acceptance Contract.** Before runtime-path prep and batch code generation, materialize a deterministic batch-local "definition of done" artifact from the validated brief. It should capture the expected behaviors, boundary contracts, verification scenarios, and explicit non-goals that the implementer and any later evaluator must use as the batch completion contract.

17. `[v0.0.0][deterministic]` **Prepare Batch Runtime Path Context** (`implement.batch_runtime_path_contract_prep.enabled`): Build batch path contract and runtime file facts for execution prompt context.
    a. Build per-batch path constraints for execution-time safety.
    b. Gather runtime file facts needed by the implementer prompt.
    c. Package this context in deterministic form for the agent.
    d. Produces no file.

18. `[v0.0.0][agent]` **Run Batch Implementer Agent** (`implement_from_specs`): Invoke implementer agent with schema retry loop.
    a. Send the batch brief and runtime context to the implementer agent.
    b. Validate returned JSON against the implement output schema.
    c. Retry generation when output is invalid or incomplete.
    d. Produces: `implement_{batch_id}.json` (in agent_outputs).

19. `[v0.0.0][deterministic]` **Validate Implement Output Semantics** (`implement.implement_semantic_validation.enabled`): Validate implement output semantic/path constraints on each implementer attempt (retry on violation).
    a. Validate that proposed changes respect semantic and path rules.
    b. Check that file targets and intent match batch constraints.
    c. Retry agent output when semantic violations are found.
    d. Produces no file.

20. `[v0.0.0][deterministic]` **Validate Implement Output Structure** (`implement.implement_output_structure_validation.enabled`): Validate implement output structure (`run_summary`, `diff_plan`, spec keys, `diff_refs`).
    a. Verify required top-level sections are present.
    b. Check required per-spec keys and `diff_refs` completeness.
    c. Reject structurally invalid outputs before any patch handling.
    d. Produces no file.

21. `[v0.0.0][deterministic]` **Validate Patch Constraints** (`implement.patch_constraints_validation.enabled`): Collect/copy patch files and enforce patch budgets/forbidden-path constraints.
    a. Collect patch payloads from agent output into a controlled location.
    b. Enforce size/count budgets and forbidden-path policies.
    c. Block patches that exceed limits or touch restricted files.
    d. Produces: `patches/*.diff`.

22. `[v0.0.0][deterministic]` **Resolve Verification Commands** (`implement.verification_command_resolution.enabled`): Select verification commands (configured commands, else deterministic fallback).
    a. Load verification commands from config when provided.
    b. If missing, choose deterministic fallback commands.
    c. Produce the exact command list that this batch will execute.
    d. Produces no file.

23. `[v0.0.0][deterministic]` **Normalize Patch Payloads** (`implement.patch_normalization.enabled`): Normalize and prepare patches (hunk/newline normalization, create-vs-existing conflict handling).
    a. Normalize patch hunks and newline formatting for stable apply behavior.
    b. Resolve create-vs-existing file conflicts deterministically.
    c. Emit clean patch payloads ready for safety checks.
    d. Produces no file.

24. `[v0.0.0][deterministic]` **Apply Patch Safety Gates** (`implement.patch_apply_gate.enabled`): Run worktree/root `git apply --check` and apply gates.
    a. Run `git apply --check` in required scopes before writing changes.
    b. Enforce additional apply gates for policy and path safety.
    c. Only allow apply when all safety checks pass.
    d. Produces no file.

25. `[v0.0.3][deterministic]` **Check Contract Schema Conformance** (`implement.contract_schema_conformance_check.enabled`): After patch apply, verify touched shared-contract JSON Schema files satisfy the required-all + nullable contract policy.
    a. For each shared contract in the brief whose `planned_file_path` exists under the worktree root, load the JSON Schema file.
    b. Assert that every declared `properties` key is listed in `required`.
    c. Assert that fields with `nullable: true` in the brief allow null in their schema type; fields with `nullable: false` do not.
    d. Produces: `contract_schema_conformance_{batch_id}.json` (in the batch run directory).

26. `[v0.0.0][deterministic]` **Run Verification Commands** (`implement.verification_execution.enabled`): Run verification commands and fail batch on non-zero exits.
    a. Execute resolved verification commands after patch application.
    b. Capture exit codes and logs for traceability.
    c. Mark batch failed if any command exits non-zero.
    d. Produces: verification logs (e.g. `trace/trace.jsonl`).

    > `(planning)` **Insert after step 26: Run Batch Evaluator Gate.** Add a first-class evaluator phase that consumes the batch acceptance contract, touched-file summary, verification logs, runtime evidence, and relevant contract artifacts. It should score completeness, contract fidelity, behavioral correctness, and test sufficiency with hard thresholds. The evaluator must prefer executed evidence over diff plausibility; if evidence and claimed completion disagree, the evidence wins.
    >
    > `(planning)` **Insert after the future evaluator gate: Apply Failure-Class Round Control Policy.** Do not treat all failures as "retry implementer once more." Route the next action by failure class: schema/path/semantic failures regenerate the same batch; evaluator or verification misses trigger a repair round; repeated conceptual misses trigger re-planning for the affected batch/spec set; repeated stagnant scores or unchanged failure modes trigger block/escalation.

## Planning-Only Harness Engineering Loops

- `(planning)` **Out-of-band benchmark + ablation lane (not a per-run phase):** Maintain a representative implement benchmark suite and periodically re-run it while disabling or simplifying individual steps in this document. Use the measured impact on cost, latency, block rate, verification outcomes, and downstream issue rate to decide which harness components are still load-bearing.

- `(planning)` **Out-of-band evaluator calibration corpus (fed by blocked/failed/evaluated runs):** After runs that block, fail, or receive low evaluator scores, persist labeled artifacts into a harness-improvement corpus. Use those cases to tune evaluator prompts, refine acceptance-contract structure, and decide where deterministic checks should be added versus removed.
