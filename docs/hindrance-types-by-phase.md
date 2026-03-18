# Hindrance Types by Phase

Every possible hindrance in the refine and implement pipelines is categorized
into one of six handling types. This document is the single source of truth for
which type applies to each step.

---

## Handling Types


| Type          | Behaviour                                                                                                                                                                                                                                     | User Action                                                                                    |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| **fail-fast** | Pipeline stops immediately with a typed `PikaError` subclass. No agent work is wasted.                                                                                                                                                        | Fix the root cause and re-run. If agent work was cached, `--resume` may skip completed stages. |
| **retry**     | The step is re-attempted (shares the planner/implementer retry counter). Transparent to the user unless retries are exhausted, at which point it becomes fail-fast.                                                                           | None unless retries exhaust.                                                                   |
| **block1**    | Full resolution suite. Options: `accept_suggestion`, `let_agent_edit` (with instruction prompt), `skip`, `manual_edit`. Includes `suggested_improvement` and `spec_amendment_hints`. O (guided agent edit) is **suppressed** for these items. | Run `pika resolve`, pick an option or M for manual edit.                                       |
| **block2**    | Hint-guided manual edit only. Option: `M` (manual spec edit). Includes `spec_amendment_hints` and `blocking_reason`.                                                                                                                          | Run `pika resolve`, press M, enter replacement text.                                           |
| **block3a**   | Structural agent/manual edit. Options: `let_agent_edit` (with instruction prompt), `skip`, `manual_edit`. No `suggested_improvement`, no `spec_amendment_hints`.                                                                              | Run `pika resolve`, pick an option or M.                                                       |
| **block3b**   | Custom agent-defined options (variable per item). Supports free text (O) and `evidence_refs`.                                                                                                                                                 | Run `pika resolve`, pick an option or O for free text.                                         |
| **other**     | Graceful skip, fallback, or informational. Pipeline continues.                                                                                                                                                                                | None.                                                                                          |


---

## Exception Classes


| Class                     | Base                      | Used By                                                           |
| ------------------------- | ------------------------- | ----------------------------------------------------------------- |
| `PikaError`               | `Exception`               | Base for all domain errors                                        |
| `ConfigParseError`        | `PikaError`, `ValueError` | Config normalization (I1, R1)                                     |
| `WorksetValidationError`  | `PikaError`               | CSV/workset schema failures (I2, R3, R4)                          |
| `SafetyPreconditionError` | `PikaError`, `ValueError` | Role/catalog validation (I2, I3)                                  |
| `AgentInvocationError`    | `PikaError`               | Agent call failures — timeout, auth, subprocess (I5, I18, R7, R8) |
| `AgentSchemaError`        | `PikaError`               | Agent output schema validation exhausted (I5, I18, R7, R8)        |
| `PlanValidationError`     | `PikaError`               | Unified plan structural validation non-retryable (I9)             |
| `BatchValidationError`    | `PikaError`               | Batch plan, brief scope, dependency edge validation (I12–I16)     |
| `PatchError`              | `PikaError`               | Patch constraint, normalization, apply, conformance (I21–I25)     |
| `VerificationError`       | `PikaError`               | Post-patch verification command non-zero exit (I26)               |
| `ResumeError`             | `PikaError`               | Resume precondition not met (R-RES, I-RES)                        |


---

## Refine Pipeline

See [refine-checks-execution-order.md](refine-checks-execution-order.md) for
step descriptions.


| Step | #         | Hindrance                         | Type                         | Exception                |
| ---- | --------- | --------------------------------- | ---------------------------- | ------------------------ |
| 1    | R1.1      | Invalid config values             | fail-fast                    | `ConfigParseError`       |
| 2    | R2.1      | `design_spec_path` missing        | other: skip                  | —                        |
| 3    | R3.1      | CSV/XLSX malformed                | fail-fast                    | `WorksetValidationError` |
| 4    | R4.1      | Missing required columns          | fail-fast                    | `WorksetValidationError` |
| 5    | R5.1      | Run dir creation fails            | fail-fast                    | `PikaError`              |
| 6    | R6.1      | sentence-transformers unavailable | fail-fast                    | `PikaError`              |
| 6    | R6.2      | Split candidates (blocking)       | **block3a**                  | —                        |
| 6    | R6.3      | Merge candidates (blocking)       | **block3a**                  | —                        |
| 6    | R6.4      | Decomposition disabled            | other: skip                  | —                        |
| 7    | R7.1      | Local CLI auth unavailable        | fail-fast                    | `AgentInvocationError`   |
| 7    | R7.2      | Agent invocation fails            | fail-fast                    | `AgentInvocationError`   |
| 7    | R7.3      | Agent output fails schema         | retry → fail-fast            | `AgentSchemaError`       |
| 7    | R7.4      | Codex rejects `--output-schema`   | retry                        | —                        |
| 7    | R7.5      | Ambiguity items produced          | **block1**                   | —                        |
| 8    | R8.1–R8.4 | Same as R7.1–R7.4                 | Same as R7                   | Same as R7               |
| 8    | R8.5      | Testability items produced        | **block1**                   | —                        |
| 9    | R9.1      | Items key missing from output     | other: graceful fallback     | —                        |
| 10   | R10.1     | File I/O fails (no items)         | fail-fast                    | `PikaError`              |
| 10   | R10.2     | N > 0 items merged                | block (type per source item) | —                        |
| 10   | R10.3     | Resolution file write fails       | fail-fast                    | `PikaError`              |


### Refine Resume


| #       | Hindrance                    | Type      | Exception                |
| ------- | ---------------------------- | --------- | ------------------------ |
| R-RES.1 | Run dir not found            | fail-fast | `ResumeError`            |
| R-RES.2 | `run_meta.json` unreadable   | fail-fast | `ResumeError`            |
| R-RES.3 | Not resolved, no agent cache | fail-fast | `ResumeError`            |
| R-RES.4 | Restructured CSV missing     | fail-fast | `ResumeError`            |
| R-RES.5 | Restructured CSV bad columns | fail-fast | `WorksetValidationError` |


---

## Implement Pipeline

See [implement-checks-execution-order.md](implement-checks-execution-order.md)
for step descriptions.


| Step | #           | Hindrance                         | Type              | Exception                 |
| ---- | ----------- | --------------------------------- | ----------------- | ------------------------- |
| 1    | I1.1–I1.8   | Config parse errors               | fail-fast         | `ConfigParseError`        |
| 2    | I2.1–I2.2   | Workset schema/field errors       | fail-fast         | `SafetyPreconditionError` |
| 3    | I3.1–I3.2   | Unknown/conflicting roles         | fail-fast         | `SafetyPreconditionError` |
| 4    | I4.1        | Path scan failure                 | fail-fast         | `PikaError`               |
| 5    | I5.1        | Planner invocation fails          | fail-fast         | `AgentInvocationError`    |
| 5    | I5.2        | Planner schema validation fails   | retry → fail-fast | `AgentSchemaError`        |
| 5    | I5.3        | Codex rejects `--output-schema`   | retry             | —                         |
| 6    | I6.1        | Path constraint violations        | retry             | —                         |
| 7    | I7.1        | Planner `manual_resolution_items` | **block3b**       | —                         |
| 8    | I8.1        | Spec issue: contradiction         | **block2**        | —                         |
| 8    | I8.2        | Spec issue: overlap               | **block2**        | —                         |
| 8    | I8.3        | Spec issue: dependencygap         | **block2**        | —                         |
| 8    | I8.4        | Spec issue: ambiguity             | **block2**        | —                         |
| 8    | I8.5        | Spec issue: orphanreference       | **block2**        | —                         |
| 9    | I9.1        | Uncovered specs                   | retry             | —                         |
| 9    | I9.2        | Dependency cycle                  | **block2**        | —                         |
| 9    | I9.3        | Unknown `spec_id` refs            | retry             | —                         |
| 9    | I9.4        | Missing module plans              | retry             | —                         |
| 10   | I10.1       | Duplicate field in contract       | **block2**        | —                         |
| 10   | I10.2       | Missing nullable boolean          | **block2**        | —                         |
| 10   | I10.3       | Field name mismatch               | **block2**        | —                         |
| 10   | I10.4       | Match ambiguity/tie               | **block2**        | —                         |
| 10   | I10.5       | Provider deviation                | **block2**        | —                         |
| 11   | I11.1       | No provider spec                  | **block2**        | —                         |
| 11   | I11.2       | Uncovered required fields         | **block2**        | —                         |
| 12   | I12.1       | Batch construction fails          | fail-fast         | `BatchValidationError`    |
| 13   | I13.1–I13.3 | Batch dependency errors           | fail-fast         | `BatchValidationError`    |
| 14   | I14.1       | Brief assembly failure            | fail-fast         | `BatchValidationError`    |
| 15   | I15.1–I15.2 | Brief scope leakage               | fail-fast         | `BatchValidationError`    |
| 16   | I16.1–I16.2 | Dependency edge mismatch          | fail-fast         | `BatchValidationError`    |
| 17   | I17.1       | Runtime facts failure             | fail-fast         | `PikaError`               |
| 18   | I18.1       | Implementer invocation fails      | fail-fast         | `AgentInvocationError`    |
| 18   | I18.2       | Implementer schema fails          | retry → fail-fast | `AgentSchemaError`        |
| 18   | I18.3       | Codex rejects `--output-schema`   | retry             | —                         |
| 18   | I18.4       | Module dir creation fails         | fail-fast         | `PikaError`               |
| 18   | I18.5       | Concurrent batch exception        | fail-fast         | `PikaError`               |
| 19   | I19.1       | Semantic violations               | retry             | —                         |
| 20   | I20.1       | Missing output structure          | retry             | —                         |
| 21   | I21.1–I21.2 | Patch budget/forbidden path       | fail-fast         | `PatchError`              |
| 22   | I22.1       | No verification commands          | other: fallback   | —                         |
| 23   | I23.1       | Patch conflict unresolvable       | fail-fast         | `PatchError`              |
| 24   | I24.1–I24.2 | `git apply --check` fails         | fail-fast         | `PatchError`              |
| 25   | I25.1–I25.2 | Schema conformance fails          | fail-fast         | `PatchError`              |
| 26   | I26.1       | Verification non-zero exit        | fail-fast         | `VerificationError`       |


### Implement Post-Pipeline


| #        | Hindrance             | Type      | Exception   |
| -------- | --------------------- | --------- | ----------- |
| I-POST.1 | Spec update exception | fail-fast | `PikaError` |


### Implement Resume


| #       | Hindrance                          | Type           | Exception     |
| ------- | ---------------------------------- | -------------- | ------------- |
| I-RES.1 | Run dir not found                  | fail-fast      | `ResumeError` |
| I-RES.2 | No agent work to recover           | fail-fast      | `ResumeError` |
| I-RES.3 | Config hash changed (warning only) | other: warning | —             |


---

## Resolve Command


| #     | Hindrance                                  | Type                            | Exception     |
| ----- | ------------------------------------------ | ------------------------------- | ------------- |
| RES.1 | No `run_id`, no recent blocked run         | fail-fast                       | `ResumeError` |
| RES.2 | Run directory not found                    | fail-fast                       | `ResumeError` |
| RES.3 | `resolutions.yaml` missing + no stage JSON | fail-fast                       | `ResumeError` |
| RES.4 | `spec_editor` agent fails                  | other: non-destructive retry    | —             |
| RES.5 | User rejects editor preview                | other: non-destructive continue | —             |
| RES.6 | Empty free text / manual edit input        | other: re-prompt                | —             |
| RES.7 | Resolution validation fails                | fail-fast                       | `PikaError`   |
| RES.8 | `_apply_*_resolutions()` fails             | fail-fast                       | `PikaError`   |


---

## Block Subtype Summary


| Subtype     | Options                                                      | Extra Fields                                    | Items                                     |
| ----------- | ------------------------------------------------------------ | ----------------------------------------------- | ----------------------------------------- |
| **block1**  | `accept_suggestion`, `let_agent_edit`, `skip`, `manual_edit` | `suggested_improvement`, `spec_amendment_hints` | R7.5, R8.5                                |
| **block2**  | `M` (manual spec edit)                                       | `spec_amendment_hints`, `blocking_reason`       | I8.1–I8.5, I9.2, I10.1–I10.5, I11.1–I11.2 |
| **block3a** | `let_agent_edit`, `skip`, `manual_edit`                      | —                                               | R6.2, R6.3                                |
| **block3b** | Custom agent-defined (variable)                              | free text (O), `evidence_refs`                  | I7.1                                      |


