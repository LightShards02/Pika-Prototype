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
