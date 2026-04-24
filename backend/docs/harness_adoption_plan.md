# Harness Adoption Plan

Inspired by Anthropic's "Harness Design for Long-Running Apps". This document captures the high-level adoptions selected for PIKA. Implementation details for each adoption live in companion plan documents and PR descriptions.

## Framing

Implement is for **prototype feasibility**, not production polish. The evaluator and supporting harnesses exist to catch obvious gaps that would waste a human reviewer's time, not to enforce production code quality.

## Adoptions

### Adoption 1 — Acceptance criteria threading & `evidence_type` awareness
- **Existing state.** The testability enricher emits per-spec `acceptance_criteria` and `evidence_type`. `implement` already reads `acceptance_criteria` from the design CSV.
- **Gap.** `evidence_type` is not threaded to non-CSV consumers. There is no helper that returns the per-spec `(acceptance_criteria, evidence_type)` mapping to downstream stages.
- **Change.** Add `backend/core/spec_acceptance.py::load_spec_acceptance_criteria`. Audit `evidence_type` survival across `implement`'s CSV write paths.
- **Benefit.** Single, reusable source of truth for AC + evidence_type. Required input for the code evaluator.

### Adoption 2 — Harness assumption registry
- **Principle.** Every harness component encodes a model-limitation assumption; document them so they can be stress-tested on model upgrades.
- **Change.** Create `backend/docs/harness_assumptions.md` with `HA-NNN` entries (component, assumed model behavior, stress-test, removal criteria). Annotate sites with inline `# HA-NNN` comments. Stub `pika doctor --check-assumptions` CLI.
- **Status.** Deferred to a follow-up PR.

### Adoption 3 — File-based handoffs for large context in `implement`
- **Principle.** Context resets beat compaction; pass large state via files, not inline content.
- **Gap.** Current PIKA prompts embed full content inline; only metadata paths are passed as path strings.
- **Change.** Above a configurable threshold, write large template vars to `handoff_{phase}_{batch_id}.json` in `run_dir`; agent reads via tool call.
- **Status.** Deferred to a follow-up PR.

### Adoption 4 — Code evaluator sub-agent in `implement`
- **Principle.** Generator–evaluator separation. Agents self-evaluate poorly.
- **Scope.** Lives in `implement` (code quality). Does NOT live in `refine` — spec edits remain human-decided.
- **Change.** New `code_evaluator` prompt + `code_eval_output.schema.json`. After batch execution, the evaluator scores applied diffs against spec-level `acceptance_criteria`, takes `evidence_type` into account, and consumes deterministic harness results (`syntax_check`, `import_smoke`, `unresolved_symbol`, `forbidden_path_violation`, `anchor_preservation`, `diff_size_sanity`). On fail, targeted re-run of failed batches up to `max_eval_cycles`; final fail → block (or warn, configurable).
- **Defaults reflect the prototype framing:** `enabled: false`, `max_eval_cycles: 1`, `fail_action: warn`, `rerun_severity_threshold: blocker`. Only catastrophic failures cycle.
- **Benefit.** Autonomous code-quality cycling; reduces wasted scaffolding that's clearly broken.

## Deterministic harnesses

Six small, deterministic, language-agnostic gates run before each evaluator invocation. Their output is **input to the evaluator**, not a direct lifecycle gate.

| Harness | Purpose |
|---|---|
| `syntax_check` | Per-touched-file parser invocation (Python: `ast.parse`; others: best-effort). |
| `import_smoke` | Best-effort `python -c "import <dotted>"` per touched Python module. |
| `unresolved_symbol` | `ruff check --select F821,F401` over touched Python files. |
| `forbidden_path_violation` | Re-asserts that no applied diff touched a forbidden path. |
| `anchor_preservation` | Confirms every planned anchor exists in the post-implementation file. |
| `diff_size_sanity` | Flags 0-line or runaway diffs (default >2000 lines). |

**No deterministic dispatch by `evidence_type`.** All evidence-type-specific judgment lives in the `code_evaluator` prompt — explicit per-type guidance on what structural patterns to look for, when to default to `minor` severity (visual/hardware types that cannot be verified statically), and when to mark `satisfied=false`.

## Risk acknowledgment

This approach trades determinism for leanness:
- Evaluator's per-type judgment is LLM-based and may vary across runs.
- Visual / hardware evidence types can only be checked structurally.

Mitigations:
- Harnesses catch the worst cases (broken syntax, undefined symbols) deterministically.
- Severity defaults are conservative: `minor` for unverifiable types; `major` for missing structural evidence; `blocker` reserved for code that cannot run.
- The `evidence_summary` field per criterion is human-readable; vague summaries are a smell that surfaces in human review.

## Sequence

1. Adoption 1 (Acceptance criteria threading) — small; lands first.
2. Adoption 4 (Code evaluator) — depends on Adoption 1.
3. Adoptions 2 and 3 — follow-up PRs.
