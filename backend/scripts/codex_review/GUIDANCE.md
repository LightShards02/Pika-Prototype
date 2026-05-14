# Codex Reviewer — Plan → Implement → Review Loop Guidance

Read this before running a milestone on the PIKA REST API redesign (or any project that uses the codex reviewer in this directory). It documents the workflow other sessions have converged on and the failure modes worth avoiding.

## TL;DR

You orchestrate. A subagent implements in an isolated worktree. Codex reviews the diff via `review.py`. You triage Codex's verdict and either request another round or merge. Repeat per milestone.

```
brief.md  ──►  implementor subagent  ──►  changes.diff + inventory.md  ──►  codex review.json
                                                                                    │
                                                              accept ◄──┬──► request_changes
                                                                        │
                                                                   merge to main
```

## Roles

| Role | Who | Responsibility |
|---|---|---|
| Orchestrator | You (main session) | Write briefs, dispatch implementor, run Codex, triage, merge |
| Implementor | `general-purpose` subagent in a worktree | Read brief, write code + tests, run tests synchronously, hand back a status report |
| Reviewer | Codex (gpt-5.3-codex via Loca) | Produce structured JSON review against the brief |
| User | The human | Locks architectural decisions, resolves brief-level open questions, approves scope changes |

Never collapse roles. The orchestrator does not implement during a milestone (unless explicitly escalating — see "Escalation"). The implementor does not commit. Codex does not have side effects.

## Directory layout

```
backend/scripts/codex_review/
├── review.py             # CLI + run_codex_review() entry point
├── review_schema.json    # Structured-output schema (verdict, blocking_issues, …)
├── reviewer_prompt.md    # System prompt for Codex
└── GUIDANCE.md           # This file

tasks/milestones/                            # gitignored
├── Mx_brief.md                              # Brief for milestone x
└── Mx/
    ├── round1/
    │   ├── changes.diff
    │   ├── file_inventory.md
    │   └── review.json
    ├── round2/ …
    └── …

.claude/worktrees/agent-<id>/                # ephemeral worktree per implementor dispatch
```

`tasks/milestones/` is gitignored (see commit `eee98b0`). Briefs, diffs, inventories, and review JSON live locally only; the implementation lands on `main` via merge.

## The loop, step by step

### 0. Bootstrap once per session

- Read `tasks/lessons.md` (project-wide) if it exists.
- Read the project memory file at `~/.claude/projects/C--Users-night-Work-Echelondx-Pika/memory/project_rest_api_redesign.md` — this contains locked architectural decisions that `review.py` automatically injects into the Codex prompt. Keep it up-to-date when decisions change.
- Confirm the conda env `Local` is the test runner (`source ~/miniconda3/etc/profile.d/conda.sh && conda activate Local`). Pytest under the wrong interpreter will surface `ModuleNotFoundError: fastapi` and similar.

### 1. Write the brief

Live under `tasks/milestones/Mx_brief.md`. Required sections:

- **Goal** — one paragraph, what changes for the user.
- **Architectural rules (non-negotiable)** — pin the locked decisions this milestone must honor. Quote, don't summarize.
- **Scope** — endpoint signatures, file paths, response shapes. Be specific.
- **Acceptance criteria** — functional + static (compileall, no `from api.*` in `backend/handlers/` or `backend/core/`) + tests by name.
- **Out of scope (do not implement)** — explicit list. Sends Codex a strong signal for the `out_of_scope_changes` field.
- **Open questions** — number them Q1, Q2, …. Resolve them with the user before dispatching the implementor. Mark resolved ones inline so Codex sees the answer too.
- **Handoff format** — what the implementor should report back.

Briefs are the contract. Vague briefs produce churning review rounds.

### 2. Dispatch the implementor

Use `Agent(subagent_type="general-purpose", isolation="worktree", ...)`. The worktree gives the implementor an isolated copy of `main` and a branch named `worktree-agent-<hash>`. Pass the brief verbatim plus:

- The conda activation line (env `Local`).
- "Don't commit. The orchestrator commits after triage."
- "Run pytest **synchronously**, not with `run_in_background`. Background pytest has stalled past sessions; the watchdog kills the agent."
- The expected report structure (status, files changed, test results, decisions, out-of-scope work resisted, open questions).

The implementor returns a textual report. You do not see their tool calls — trust their summary, then verify with `git diff` and `pytest`.

### 3. Generate the round artifacts

From the orchestrator session (not the worktree):

```bash
cd C:/Users/night/Work/Echelondx/Pika/.claude/worktrees/agent-<id>
mkdir -p ../../../tasks/milestones/Mx/roundN
git diff main -- backend/ > ../../../tasks/milestones/Mx/roundN/changes.diff
```

Then write `file_inventory.md`. The inventory is *not* a redundant diff — it explains:

- What the change does in human terms (one paragraph).
- Per-file table of changes and rationale.
- Decisions the implementor made under brief ambiguity.
- Test results (counts from each suite invocation).
- Focus areas for the reviewer (what you want Codex to scrutinize).
- What was deferred / left out of scope.

Round 2+ inventories also include a **"Round-N Codex findings — resolution"** table that maps each prior-round finding to its current disposition.

### 4. Invoke the reviewer

From `backend/` with `Local` active:

```bash
python -m scripts.codex_review.review \
    --brief    ../tasks/milestones/Mx_brief.md \
    --diff     ../tasks/milestones/Mx/roundN/changes.diff \
    --inventory ../tasks/milestones/Mx/roundN/file_inventory.md \
    --out      ../tasks/milestones/Mx/roundN/review.json
```

Defaults: `gpt-5.3-codex` provider `openai-codex`, `reasoning_effort=high`, `max_turns=30`, sandbox `working_dir=repo root`. Codex reads the brief + inventory + diff + locked decisions, then emits JSON conforming to `review_schema.json`. Stderr prints the verdict.

The reviewer's tiered rubric (in `reviewer_prompt.md`):

- **Tier 1 blocking** — correctness, security, or design-rule violations. Must fix.
- **Tier 2 blocking** — significant quality issues (testability, error handling). Must fix unless justified.
- **Non-blocking suggestions** — style, ergonomics, future-polish.

Verdicts: `accept`, `request_changes`, `reject`.

### 5. Triage

For each `blocking_issues` entry, decide one of:

- **Accept and fix** — dispatch a round-N+1 implementor (or fix yourself for trivial changes) with the finding quoted in the brief, ask for a minimal patch.
- **Push back** — write a counter-argument in your next-round inventory under "Round-N Codex findings — resolution" and skip the fix. Codex has accepted pushback in past rounds when the finding misread project scope (see M6 history). Do not push back silently — Codex sees the round-N+1 inventory.
- **Defer** — record in `tasks/long-term-todo.md` if the issue is real but outside this milestone's scope.

For `non_blocking_suggestions`: read them, fix only the ones that are cheap and clearly correct. Document any you defer.

For `missing_tests`: usually add them. The reviewer is good at spotting under-tested branches.

For `out_of_scope_changes`: take seriously. If the implementor crept beyond the brief, decide whether to keep (justify) or remove.

### 6. Next round or merge

If the verdict is `request_changes` or `reject`: loop back to step 2 with a tightened brief addendum referencing the prior-round review.

If the verdict is `accept`: commit in the worktree, fast-forward merge to `main`, remove the worktree.

```bash
# In the worktree:
git add backend/<files>
git commit -m "$(cat <<'EOF'
(feat) Mx: <one-line subject>

<2-3 sentence body explaining the change, the user-visible behavior, and any
defensive decisions worth flagging>.

Codex review: round N accepted; <one line on what prior rounds flagged>.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"

# In main:
git merge --ff-only <commit-sha>
git worktree remove --force .claude/worktrees/agent-<id>
git branch -D worktree-agent-<id>
```

Never commit `tasks/milestones/Mx/` artifacts — they are gitignored. The diff, inventory, and review JSON are local audit trail, not history.

### 7. Update `tasks/todo.md`

Append the milestone with its merge SHA, test count delta, round count, and what each round caught. Future sessions read this to reconstruct the migration arc.

## Escalation

If round 5 has not produced convergence, stop dispatching subagents. The patterns from M1 and M4: a subagent stuck on the same Tier 1 finding after multiple attempts means the brief is wrong, not the implementor. Re-read the finding, the locked decisions, and the failing tests yourself. Often the right move is a small orchestrator-authored patch that breaks the deadlock.

Other escalation triggers:

- Subagent watchdog kills (background pytest, runaway tool use).
- Codex `request_changes` over the same line range for two consecutive rounds with no apparent diff in the implementor's fix attempt.
- A test failure that is not in the new module (likely a regression elsewhere; pause the milestone and fix the regression first).

## Known failure modes

- **Background pytest stalls**: the M4 implementor and one M2b agent both got tangled running pytest with `run_in_background=true`. Always brief implementors to run pytest synchronously.
- **Wrong conda env**: pytest under base Python misses `fastapi`, `pydantic`, etc. Activate `Local` before any test run.
- **Lost worktree files**: `git stash push -u` + `git stash drop` will silently drop untracked files. If you stash during a merge conflict and the worktree contains uncommitted scripts (e.g., a new directory), they go to the void. Commit early.
- **Codex hallucinating absent-from-diff issues**: rare but it happens with low-context briefs. Quote the brief tightly and keep the inventory factual; over-narrating decisions can mislead Codex into flagging non-existent code.
- **Schema retries exhausted**: `max_schema_retries=2`. If Codex emits malformed JSON twice, `review.py` raises. Re-run; do not edit the schema unless the failure repeats.

## What the reviewer does NOT do

- It does not run tests.
- It does not read files outside the brief/diff/inventory you pass.
- It does not know about runtime state, prior reviews, or other milestones unless you put that context in the inventory.
- It does not block the merge — you do.

Treat the JSON as input to your judgment, not a gate.

## Quick reference

| Path | Purpose |
|---|---|
| `backend/scripts/codex_review/review.py` | Driver — invokes Loca's openai-codex with the prompt + schema |
| `backend/scripts/codex_review/reviewer_prompt.md` | System prompt — defines the tiered rubric |
| `backend/scripts/codex_review/review_schema.json` | Structured-output contract |
| `~/.claude/projects/C--Users-night-Work-Echelondx-Pika/memory/project_rest_api_redesign.md` | Locked architectural decisions (auto-injected) |
| `tasks/milestones/Mx_brief.md` | Milestone brief (gitignored, durable across sessions) |
| `tasks/milestones/Mx/roundN/{changes.diff,file_inventory.md,review.json}` | Per-round audit trail |
| `tasks/todo.md` | Migration arc — append each merged milestone here |
