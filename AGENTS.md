You are a senior staff software engineer. Build a production-quality CLI program (PIKA) implementing an agentic workflow with commands.

Read PROJECT_CONTEXT.md for the rules, requirements, and descriptions of the program. You MUST follow the rules defined in the PROJECT_CONTEXT.md.

Additional Requirements:
- Prompts for agents must be stored centrally in a PROMPT file; runtime must reference them by name.
- Non-agent steps (load & reformat) must be pure script, deterministic.
- Agent steps must be isolated, logged, and produce structured outputs (JSON) that can be applied deterministically.
- Never overwrite user files without making a copy; produce outputs to configured output paths.
- All CSV modifications must preserve original columns and add new ones as specified.
- Provide robust error handling, logs, and unit tests.

Before writing any code:
1) Restate requirements precisely.
2) Produce an architecture diagram (text) and module boundaries.
3) Define schemas: CONFIG, PROMPT file format, and any agent output JSON schemas.
4) List edge cases and how each command handles them.
5) Propose an incremental implementation plan (milestones).
6) (IMPORTANT) When encountering unclarities not defined by AGENTS.md or PROJECT_CONTEXT.md, DO NOT implement the relevant code. Instead summarize your questions and list them in the chat.
7) If writing in Python, activate the conda environment named "Local". All dependencies should be installed in this environment.

Only after the above, implement code in small cohesive chunks with:
- file tree
- each file content
- minimal dependencies
- tests and samples where helpful
- documentation matching existing project style (public APIs and non-obvious behavior)

## Workflow Orchestration

### 1. Plan Node Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately - don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One tack per subagent for focused execution

### 3. Self-Improvement Loop
- **Session start (mandatory)**: Before starting any work, check if `tasks/lessons.md` exists. If it does, read it and apply relevant lessons. If `tasks/` or its files don't exist, create them when you begin non-trivial work.
- **On user correction (mandatory)**: When the user corrects your output, BEFORE replying, append the lesson to `tasks/lessons.md` with the pattern and a rule to prevent the same mistake.
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 4.1 UI Verification
- For UI or component changes, do not stop after unit tests.
- Use the `playwright` MCP server to validate the changed flow in a real browser.
- Check desktop and mobile widths before declaring the task done.
- Verify hover, focus, keyboard navigation, scrolling, and modal behavior.
- Report concrete UI defects such as overflow, clipping, invisible focus, broken tab order, z-index issues, layout shift, and off-screen dialogs.

#### Recommended Browser Verification Stack
Use these three tools together for thorough UI validation:

a. **`playwright` MCP** — low-level browser control. Use for targeted, scripted interactions: navigate to a specific URL, fill a form, click a button, assert an element is visible, take a screenshot at a precise moment. This is your scalpel.

b. **`agent-browser` skill** — higher-level browser automation for multi-step flows. Use when the verification task involves a sequence of actions that reads more naturally as a goal ("log in, navigate to settings, verify the toggle persists after reload") rather than individual tool calls. Wrap `playwright` calls inside agent-browser tasks to keep the main context clean.

c. **`dogfood` skill** — exploratory QA sweep. After targeted verification with playwright/agent-browser, invoke `dogfood` to do a broad pass over the affected surface. It finds regressions, UX rough edges, and bugs you didn't think to check for. Use it as a final gate before marking any UI task done.

**Recommended order**: `playwright` (targeted checks) → `agent-browser` (flow-level validation) → `dogfood` (exploratory sweep).

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes - don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests - then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

## Task Management
0. **Bootstrap**: If starting non-trivial work (3+ steps) and `tasks/todo.md` or `tasks/lessons.md` do not exist, create the `tasks/` directory and initialize both files.
1. **Plan First**: For any task with 3+ steps, create or update `tasks/todo.md` with checkable items BEFORE writing any code.
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to `tasks/todo.md`
6. **Capture Lessons**: Update `tasks/lessons.md` after corrections
7. **Archives**: Older session todo logs may be moved under `archive/todo/<date>/` (for example `archive/todo/Apr22/todo.md`) to keep `tasks/` lightweight.

## Core Principles
- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.

## Cursor / IDE-specific instructions

### Project overview

PIKA is a Python 3.12+ workflow tool: primary entry is **`backend/cli.py`** (Typer). It orchestrates multi-agent software development; **there is no web UI** for PIKA itself. State for runs is file-based (CSV, JSON, YAML). This repository also includes **`desktop-app/`**, an Electron-style operator UI that invokes the same CLI and surfaces settings aligned with PIKA config. See `PROJECT_CONTEXT.md` for full architecture.

### Layout

- **PIKA root** (install / dev tree): `backend/` — contains `cli.py`, `core/`, `handlers/`, `config/pika.yaml`, `schemas/`, `prompts/`, `tests/`.
- **Workspace root**: directory passed as `--project-root` — contains workspace `config/config.yaml` (or `config.yaml`), `out/`, SRS, SADS, etc.

### Required runtime config

**`backend/config/pika.yaml`** is **required** at runtime (`core/pika_config.py` loads it from PIKA root). It is **tracked in this repository** as the default PIKA-level config; fork/custom installs may replace it locally. Without a valid file at that path, commands and most tests fail early.

### Running tests

From **`backend/`** (with dev dependencies installed, e.g. conda env `Local`):

```
python -m pytest tests/ -v
```

Test count and pass rate depend on the environment and optional packages (for example `pylatexenc` for some modules). Run the suite locally before declaring work complete.

`test_handshake_simple_schema` (when present) is skipped unless the deprecated **Codex npm CLI** is available; it is not used by the **`local`** provider path (Loca in-process).

### Running the CLI

From **`backend/`**:

```
python cli.py agent <command> --project-root <workspace> [options]
```

Top-level **`login`** supports OAuth for the **`openai-codex`** Loca sub-provider.

**`agent`** subcommands include: `plan`, `format`, `review`, `refine`, `map`, `implement`, `resolve_plan`, `resolve`. The `format` command is deterministic (no LLM) and is a good smoke test:

```
python cli.py agent format --project-root <workspace> --dry-run
```

### Agent providers

Workspace `agent.provider` (see `backend/config/config.schema.json`) allows only:

- **`stub`** (default): mock agent, no external dependencies — use for most automated tests
- **`local`**: **Loca** in-process LLM agent; requires Loca and auth per workspace `agent.provider_sub` (mirrors `pika.yaml` `local.provider_sub`: `openai-codex` OAuth, `openai` + `OPENAI_API_KEY` / `MOONSHOT_API_KEY`, or `anthropic` + `ANTHROPIC_API_KEY`). This is **not** the Codex npm CLI.

Any other `provider` value (including historical **`api`**) falls back to **`stub`** at runtime.

### Linting

No dedicated linter is configured in the repo. Use `python -m py_compile <file>` or `python -m compileall <dir>` for basic syntax checks.
