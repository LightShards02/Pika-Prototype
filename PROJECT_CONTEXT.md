## PROJECT_CONTEXT.md

### Purpose

PIKA is a contract-first, schema-driven CLI that centrally orchestrates multiple agents and documents to deliver a software project from requirements → design → implementation → review → issue resolution.

The workflow is multi-agent and document-centric:

- **Agents (black boxes)** perform bounded reasoning and generate **schema-validated output files**.
- **Documents (white boxes)** are the durable sources of truth and audit trail.
- **PIKA is the only component that applies changes** to documents and code, by translating agent outputs into deterministic edits.

PIKA’s job is to:
1) load/normalize documents deterministically,  
2) invoke the right agent with the right context,  
3) validate agent outputs against JSON Schemas,  
4) translate validated outputs into deterministic document/code changes,  
5) persist logs and run artifacts for auditability.

---

### Critical Rule: Agents Never Directly Modify Documents or Code

**None of the agents make direct changes to any document or artifact shown in the diagram**, including (but not limited to):
- SRS
- Raw SADS / Draft Formatted SADS / Formatted SADS
- Design Issue Tracker
- Implementation Issue Tracker
- Code repository

Instead:
- Each agent **only produces output files** (typically JSON) that **must validate against a strict schema**.
- The **PIKA program** is solely responsible for:
  - validating the output against schema,
  - applying the permitted transformations,
  - writing updates to the target documents (CSV updates) and/or code (diff application),
  - recording the applied changes and logs.

This separation is mandatory for safety, determinism, auditability, and reproducibility.

---

### Critical Rule: Manual Resolution Is Blocking and Interactive

Some situations require human decisions. These are emitted as **manual_resolution_items**.

**Blocking rule**
- If an agent determines that **any** manual_resolution_items are required, the agent must output **only** manual_resolution_items and **must not** output anything else (no diffs, no mappings, no tracker updates, no “partial” results).

**Resolution workflow**
- PIKA must resolve manual_resolution_items **before** proceeding with any agent output application.
- PIKA resolves them interactively via CLI:
  1) Present **one** manual_resolution_item at a time (in a deterministic order).
  2) Ask the user for the required decision/input.
  3) Record the user’s answer in a persistent, structured artifact (the “manual resolution log”).
  4) Continue until **all** manual_resolution_items are resolved.

**After resolution**
- Once there are no manual_resolution_items (or all have been resolved), PIKA re-invokes the agent(s).
- The agent(s) then produce normal schema outputs (e.g., mappings, diffs, issue updates) and PIKA proceeds with translation/application.

---

### Workflow Overview

#### Documents
- **SRS (Only human editable)**: the authoritative requirements.
- **Raw SADS**: an unnormalized design spec source that may be incomplete or inconsistent.
- **Draft Formatted SADS**: a normalized, structured draft produced before human sign-off.
- **Formatted SADS**: the canonical design spec table used for implementation and traceability.
- **Design Issue Tracker**: tracks design-time issues found during drafting/review.
- **Code Repository**: source code + tests.
- **Implementation Issue Tracker**: tracks implementation-time issues, bugs, regressions, and follow-ups.

#### Phases (as defined by the diagram)
- **Phase 0.a (Optional): Project Planning**
  - Inputs: SRS (human-only)
  - Agent: Project Designer
  - Outputs: **proposed_sads_outline_path** (path to SADS-compatible CSV written by agent in agent_artifacts_dir), milestones; PIKA copies to agent_runs_dir

- **Phase 0.b (Optional): Project Planning / Formatting**
  - Inputs: Raw SADS
  - Agent/Process: SADS Formatter (deterministic only; no LLM)
  - Outputs: Draft Formatted SADS (contract-compliant draft)

- **Human Review Gate (Design Approval)**
  - Inputs: Draft Formatted SADS + Design Issue Tracker
  - Output: Formatted SADS (approved canonical spec)

- **Phase 1: Project Implementation**
  - Inputs: Formatted SADS
  - Agent: Implementer
  - Outputs: planner/linker artifacts, deterministic batch plans/briefs, and per-batch spec-keyed diff plans; PIKA applies validated patches to Code and mapping updates to tables
  - **Implement loop (future):** Each `implement` run can trigger: implement → test → issue tracking update → implement. On verification failure, PIKA adds rows to Implementation Issue Tracker; subsequent runs may consume those issues. Current implementation executes multiple deterministic batches per run.

- **Phase 2: Design Backtracing**
  - Inputs: Formatted SADS + Code + Implementation Issue Tracker
  - Agents: SADS Mapper
  - Outputs: mapping/backtrace code to design plans; PIKA translates these into table updates (and optional follow-up work)

- **Phase 3: Human Review**
  - Inputs: Code & Product review findings
  - Output: new/updated items in Implementation Issue Tracker (human-authored)

- **Phase 4: Issue Resolving**
  - Inputs: Implementation Issue Tracker
  - Agent: Resolution Organizer, Implementer
  - Output: resolution plans and human-resolution artifacts; PIKA translates validated outputs into updates and handoffs

---

### Command Surface (One Command per Agent)

Each agent is invoked by exactly one PIKA command. Each command:
- produces schema-validated output files (no direct edits),
- has deterministic translation rules for PIKA to apply updates to documents/code,
- obeys the blocking manual_resolution_items rule.

#### `plan` — Project Designer (Phase 0.a)

**Goal:** produce a project plan and a **detailed design** from the SRS. The output is **directly compatible with the Design Spec (SADS) table columns** per csv_contracts.md. The detailed design (unit logic, feature logic, edge cases, error handling, class and helper descriptions) is **embedded in the requirement and acceptance_criteria text** of each spec row, not as separate fields.

Inputs:
- SRS (read-only)
- constraints from config (repo info, tech stack, non-functional requirements)

Agent outputs (schema-validated files):
- If manual resolution is required: **manual_resolution_items only**
- Otherwise:
  - **proposed_sads_outline_path** (required): path to SADS-compatible CSV file written by the agent in agent_artifacts_dir. The file contains rows with spec_id, title, requirement, acceptance_criteria, status. Each row's requirement and acceptance_criteria embed the detailed design:
    - unit/module logic and responsibilities
    - feature logic and flows
    - edge cases and handling
    - error handling strategy
    - class and major helper descriptions
  - project plan milestones (optional)

PIKA translation:
- copies proposed_sads_outline from agent-written path to agent_runs_dir
- writes milestones JSON if present

---

#### `format` — SADS Formatter (Phase 0.b; deterministic only; no LLM)

**Goal:** normalize Raw SADS into Draft Formatted SADS under a strict table contract.

Inputs:
- Raw SADS (CSV/XLSX)
- config: sensitive keyword dictionary, required columns, ID rules

Outputs:
- Draft Formatted SADS (CSV)
- updated ID registry (if used)
- logs

PIKA translation:
- direct deterministic transformation (no agent output schema required)

---

#### `review` — Design Reviewer (Design gate support; Optional)

**Goal:** review Draft Formatted SADS for gaps, contradictions, ambiguities, and testability.

Inputs:
- SRS (read-only)
- Draft Formatted SADS

Agent outputs (schema-validated files):
- If manual resolution is required: **manual_resolution_items only**
- Otherwise:
  - Design Issue records to add/update
  - per-spec review notes (optional)

PIKA translation:
- updates Design Issue Tracker per contract-defined column rules
- persists review artifacts as run outputs

---

#### `map` — SADS Mapper (Phase 2)

**Goal:** produce traceability mappings from each spec to code symbols (or “NA” if unmapped).

Inputs:
- Formatted SADS
- repo code context / index

Agent outputs (schema-validated files):
- If manual resolution is required: **manual_resolution_items only**
- Otherwise:
  - per-`spec_id` mapping results (`mapped_code_symbols`, statuses, `assumptions`)

PIKA translation:
- updates only mapping-related columns in Formatted SADS (contract-defined)

---

#### `implement` — Implementer (Phase 1)

**Goal:** implement Formatted SADS requirements through deterministic planning + batch execution with `spec_id` traceability.

Inputs:
- Formatted SADS
- repo context

Agent outputs (schema-validated files):
- If manual resolution is required: **manual_resolution_items only**
- Otherwise:
  - module-local anchor plans (`planned_anchors`, `provided_intents`, `required_intents`)
  - global link plan (`contracts`, `bindings`, optional `integration_actions`)
  - per-batch implement output keyed by `spec_id`, including `diffs[].diff_path` (agent writes unified diff files to `agent_artifacts_dir`)

PIKA translation:
- validates link plan and batch plan dependency integrity
- builds deterministic batch briefs and executes batches in dependency order
- applies diffs safely to the Code repository
- updates mapped columns in Design Spec and deduplicated test mappings in test spec output

---

#### `resolve_plan` — Resolution Organizer (Phase 2 and Phase 4)

**Goal:** produce issue→spec mapping, prioritization, and resolution plans (no code diffs).

Inputs:
- Implementation Issue Tracker
- Formatted SADS
- repo context as needed

Agent outputs (schema-validated files):
- If manual resolution is required: **manual_resolution_items only**
- Otherwise:
  - per-issue `mapped_spec_ids`
  - suspected root cause summary
  - priority/severity recommendation
  - next actions and resolution plan

PIKA translation:
- updates only the Implementation Issue Tracker planning/mapping columns (contract-defined)
- persists resolution packets/checklists as run outputs

---

### Human-Driven Steps (Not Commands)

#### Human Review Gate (Design Approval)
Humans approve Draft Formatted SADS → Formatted SADS and resolve/close Design Issue Tracker entries.

#### Phase 3: Human Review of Code & Product
Humans review the product and code outcomes; findings become new/updated rows in the Implementation Issue Tracker.

#### Phase 4: Human Resolution
Humans make decisions needed to unblock or finalize issue resolution; those decisions are captured in the Implementation Issue Tracker and/or manual resolution artifacts.

---

### Contracts and Invariants (Hard Rules)

1) **Schema validation is mandatory**
- All agent output files must validate against their JSON Schemas. Agents MUST follow the output schema exactly.
- Large content (design spec drafts, unified diffs) is written by the agent to files in agent_artifacts_dir; schemas reference paths only, not inline content.
- `additionalProperties: false` means no invented fields.

2) **Agents never mutate documents directly**
- Agents only output schema-validated files.
- PIKA alone translates validated outputs into edits.

3) **Manual resolution is blocking**
- If manual_resolution_items are present, the agent output must contain **only** manual_resolution_items.
- PIKA must resolve them interactively (one-by-one) before re-running the agent to obtain normal outputs.

4) **Allowed mutations are contract-defined**
- CSV: never delete/reorder user columns; append missing contract columns at end in contract order
- update only columns permitted for the invoking command

5) **SRS is read-only**
- Any required SRS change must be emitted as a manual_resolution_item for human action.

6) **Code changes are diff-only**
- Agents write unified diffs to files in agent_artifacts_dir and return diff_path in output; PIKA reads from paths and applies them safely.

7) **Traceability is required**
- mappings reference `spec_id`
- diffs and implementation notes reference `spec_id`
- issue planning references issue IDs and mapped `spec_id`s

---

### Path Resolution: PIKA Root vs Workspace Root

PIKA distinguishes two roots:

1. **PIKA root** — Parent of `cli.py`; contains PIKA source, schemas, contracts, prompts.
   - Project-independent paths: `config/config.schema.json`, `docs/csv_contracts.md`, `docs/project_context_contracts.md`, `prompts/PROMPT.yaml`, `schemas/agent_outputs/*.schema.json`
   - Always resolved from the PIKA installation directory

2. **Workspace root** — The project PIKA is used to build (required input via `--project-root`, defaults to current directory).
   - Contains: project config (`config/config.yaml`), runtime outputs (`out/`), inputs (SRS, SADS, etc.)
   - All project-variable paths in config are relative to this

**Sanity check:** If a file/dir is project-independent, it lives under PIKA root; if it may vary per project, it lives under workspace root.

Prompts are always resolved from PIKA root; only template variables vary per project. Schemas in config: workspace first, then PIKA root. Workspace root (`--project-root`) is required.
