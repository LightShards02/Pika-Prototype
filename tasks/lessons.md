# Lessons

- Session start: no prior lessons recorded.
- Pattern: Wording updates for drafting standards were previously interpreted too narrowly.
  Rule: When the user requests an exact standards sentence change, apply the requested phrasing verbatim to all active copies of that skill definition.
- Pattern: Cross-module interaction specs were not explicitly required to be split by module ownership.
  Rule: For any interaction across two modules, always create paired specs: sender-side trigger/payload spec and receiver-side handling/response spec.
- Pattern: Subunit values were too granular and fragmented across related rows in the same workflow.
  Rule: Use generalized subunit buckets and assign the same subunit value to all rows that belong to one workflow part (for example `user_management`, `history_management`, `export_management`).
- Pattern: User asked to evaluate proposals against specific false-positive classes, but response drifted into broader/adjacent problems.
  Rule: When user scopes proposals to named failure classes, evaluate each proposal directly against those exact classes first, then add side effects second.
- Pattern: Link-style code references were not reliably actionable in the user's environment.
  Rule: When you need to reference a specific place in code, DO NOT output markdown links and DO NOT output any `https://file+.vscode-resource...` URLs. Instead, output a single runnable PowerShell command in this exact form: `cursor -g "<absolute_path_or_path_relative_to_repo_root>:<line>:<col>"`.
  Rule: Use `-g`/`--goto`, always wrap the full `file:line:col` argument in double quotes, and prefer forward slashes in paths (for example `c:/Users/...`).
- Pattern: Python module loading was previously deferred into function bodies without necessity.
  Rule: Prefer explicit top-level imports in Python; avoid lazy imports unless they are required for startup cost, optional dependencies, or cycle resolution.
- Pattern: Brief builder included anchors/contracts based on overlap but passed the full global object without narrowing internal ID lists to batch scope.
  Rule: When filtering shared objects (anchors, contracts) into a batch brief, always narrow the object's internal reference lists (spec_ids, consumed_by_specs) to only the IDs in the current batch. Use `{**obj, "field": sorted(intersection)}` pattern, not bare `append(obj)`.
- Pattern: Matching threshold settings were initially implemented as raw edit-distance integers when user intent required normalized scoring.
  Rule: When a user requests scoring/threshold normalization, represent both score output and config threshold in 0..1 and update schemas/tests/config examples together.
- Pattern: `codebase_dir` fallback semantics were assumed to auto-create missing directories.
  Rule: For `resolve_codebase_dir_path`, use existing explicit/configured directory when valid; otherwise fall back to `project_root` (including missing paths and `.`).
- Pattern: `codebase_dir` creation behavior was recently reverted to fallback-to-root and can block expected bootstrap paths.
  Rule: For CLI/configured `codebase_dir`, when the path does not exist, create it under `project_root` and return the created directory (except when the value is `.`).
- Pattern: Implement patch apply scope treated unprefixed diff paths as project-root relative even when `--codebase-dir` targeted a subdirectory.
  Rule: In implement execution, resolve patch apply directory from both repo-prefix and `codebase_dir` relative path so unprefixed paths land under the effective codebase root.
- Pattern: User corrected debug-loop expectations to require explicit bug/solution reporting and bounded reruns.
  Rule: When debugging `implement`, cap total command runs to 3 per request and always include a per-bug `Bug`, `Solution`, and `Verification` entry in the final report.

- Pattern: User asks for improvements/solutions after analyzing a dataset run, and responses drift into dataset-specific fixes instead of platform fixes.
  Rule: Treat these requests as PIKA architecture/workflow improvements by default (planner, validators, contracts, gates, orchestration), unless the user explicitly asks for dataset-level remediation.

- Pattern: Architectural proposals included vague mechanics and non-existent fields, reducing trust.
  Rule: For PIKA architecture proposals, tie each change to existing pipeline stages/files, define deterministic algorithms and thresholds explicitly, and remove any part that cannot be specified concretely.

- Pattern: Improvement proposals for PIKA commands suggested API-provider-specific features (e.g. codebase snapshot enhancements for API providers) without knowing that the "api" provider is not supported.
  Rule: All PIKA commands currently only support the "stub" and "local" providers. The "api" provider option is not implemented. Do not propose improvements or flag gaps specific to the "api" provider path.

- Pattern: Planner output analysis revealed that the planner under-declares shared_contracts for secondary workflow boundaries, even though its own spec_dependency rationales name the missing shapes ("paginated envelope contract", "export link response", etc.).
  Rule: When analyzing planner output gaps, check whether spec_dependency rationales contain contract/DTO/envelope keywords that don't correspond to any declared shared_contract entry — this is the primary signal of a contract coverage gap. Three improvements follow from this: (1) a post-planner "contract boundary coverage" validator that scans spec_dependency rationales for contract-language and checks coverage; (2) a planner prompt self-check pass requiring explicit enumeration of every named cross-module data shape; (3) auto-escalation of dependency_gap spec_issues spanning multiple modules into blocking manual_resolution_items.

- Pattern: Implement command work was done without consulting the phase-index doc.
  Rule: For any request touching the implement command (new validators, prompt changes, gate changes, new config flags), always reference docs/implement-checks-execution-order.md phase numbers. Name new phases with their proposed insertion point and [vX.X.X] tag.
- Pattern: User asked for schema-instance links, but I returned two schema files and missed the concrete artifact instance.
  Rule: When asked for schema-instance relationship, always provide one schema definition path and one concrete runtime/document instance path for the same object type, with exact line anchors.
- Pattern: Dataset-planning artifact naming was left ambiguous even though the repo already had an established convention.
  Rule: For dataset packages in this repo, default to the existing `PROJECT_CONTEXT.md` convention unless the user explicitly asks to introduce a new artifact name.
- Pattern: A reusable skill was created in the user-global registry even though the user intended project-scoped reuse across repository tools.
  Rule: For skills derived from a specific repository workflow, default to project-level installation first and mirror them into Claude/Cursor project surfaces when the repo already has those integrations.
- Pattern: New workspace config keys were added to `config.schema.json` without updating `backend/config/config.example.yaml`, leaving discoverability and copy-paste defaults out of sync.
  Rule: Whenever new project (workspace) config is added to `backend/config/config.schema.json`, update `backend/config/config.example.yaml` in the same change so the canonical example stays valid and documents the new fields.
- Pattern: Newly authored SADS datasets used code-style function or class identifiers inside architectural requirements.
  Rule: In SADS rows, keep ownership at the module or workflow-subunit level only. Never include function names, class names, method names, or code-like dotted identifiers in `title`, `requirement`, or `acceptance_criteria`.
- Pattern: Changes around local agent invocation (Loca bridge, lifecycle `invoke_agent_*`, provider config, streaming/schema paths) were treated as done after unit tests alone, while real providers behaved differently (e.g. Codex streaming vs completed payload).
  Rule: Whenever you touch code that affects model invocation, run at least one real PIKA command end-to-end against a workspace (any command that exercises the path—`refine`, `map`, `format` smoke, etc.) before you call the edit finished. Mocks and static review are not a substitute for that run.
- Pattern: A project-level positioning summary described PIKA as only a CLI platform and omitted the existing desktop app surface.
  Rule: When describing PIKA at the product/platform level, verify whether the point is backend-only or product-level. If product-level, include both the CLI orchestration layer and the desktop-app surface when present.
- Pattern: A deck-outline document stayed at presenter-note level when the user needed slide-authoring detail.
  Rule: When asked to draft deck contents, include proposed on-slide text and explicit instructions for where and how visuals should appear, not just high-level slide summaries.
- Pattern: A user-modified derived presentation file was regenerated from source without first preserving the current derived file state.
  Rule: Before running any script that rewrites a presentation or document artifact that already exists, always back up the exact target file first, even if the script also backs up an upstream source file.
