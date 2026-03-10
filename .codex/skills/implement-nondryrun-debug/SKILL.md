---
name: implement-nondryrun-debug
description: Debug non-dry-run implement command executions for this project using a fixed reproduction command and deterministic triage. Use when asked to debug `implement` (not dry-run), especially for `dataset/nutrition`, by running the command to completion, then analyzing stderr, run logs, run artifacts, and resulting code changes.
---

# Implement Non-Dry-Run Debug

Use this workflow to debug a real `implement` run for the nutrition dataset.

## Execute First, Analyze After

1. Run the command exactly from repository root:
   - `python cli.py agent implement --project-root dataset/nutrition --codebase-dir src`
2. Wait until the process exits.
3. Do not analyze logs, infer causes, or send intermediate reasoning while the command is running.
4. Capture exit code, stdout, and stderr only after completion.

## Run-Debug-Fix Loop (Hard Cap)

1. For each user request to debug `implement`, run the `implement` command **at most 3 times total**.
2. The cap includes:
   - initial reproduction run,
   - any rerun after a fix,
   - any additional validation rerun.
3. If unresolved after 3 runs, stop rerunning and report unresolved status with:
   - best-known root cause,
   - attempted fixes,
   - recommended next action.

## Collect Deterministic Evidence

After the process exits, inspect:

1. Latest implement run dir:
   - `out/agent_runs/implement/<run_id>/`
   - Required files to check first: `summary.json`, `run_meta.json`
   - If present, inspect `verification/*.log`
2. Latest implement runtime log:
   - `out/logs/implement_<run_id>.log` (or latest `implement_*.log` if run_id is unknown)
3. Command stderr text captured from the just-finished run.

Use these PowerShell locators when needed:
- `Get-ChildItem out/agent_runs/implement -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1`
- `Get-ChildItem out/logs -Filter "implement_*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1`

## Branch by Outcome

### If run result is success

Treat success as potentially flawed output. Do all of the following:

1. Inspect generated/modified code (`git status --porcelain`, `git diff --name-only`, then review changed files).
2. Identify likely implementation problems:
   - incorrect behavior versus spec intent,
   - brittle logic or missing error handling,
   - missing or weak tests,
   - obvious integration gaps.
3. Report each issue with concrete evidence (file path + line and reason).

### If run result is failure

1. Identify the first failure source using this priority:
   - command stderr root error,
   - `summary.json` status/reason/failed stage,
   - verification logs,
   - structured lifecycle events in `out/logs/implement_*.log`.
2. Produce a concrete repair plan with ordered steps.
3. Evaluate follow-up error risk for the plan:
   - risk level: `low`, `medium`, or `high`,
   - likely downstream failure classes,
   - mitigations to prevent cascades.

## Bug + Solution Reporting (Mandatory)

Whenever a bug is encountered during debug/fix attempts, explicitly report:

1. `Bug`: what failed, where, and why (root cause).
2. `Solution`: exact code/config change made to address that bug.
3. `Verification`: what command/log proves the solution impact.

Do this for each bug encountered in the same debug session.

## Response Structure

Return findings using this shape:

1. `Execution Result`: command, exit code, run_id, summary status.
2. `Evidence`: key stderr lines and key log/artifact observations.
3. `Bug and Solution Log`:
   - one entry per encountered bug with `Bug`, `Solution`, `Verification`.
4. `Diagnosis`:
   - success path: generated-code issues found,
   - failure path: current root cause.
5. `Resolution Plan`: ordered remediation steps.
6. `Follow-up Risk`: risk level, possible downstream errors, mitigations.
