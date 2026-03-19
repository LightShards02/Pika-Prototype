# Design Handoff: "Design Improvement" — Desktop GUI Feature

**Audience:** Designer agent
**Branch:** `desktop`
**Status:** Handoff for visual design & interaction design

---

## 1. Background: What This Feature Replaces

Pika is a CLI tool that processes a **design spec** (a CSV file called a SADS — Software Architecture Design Specification). Two of its most important CLI commands are:

- `pika refine` — audits the design spec for quality issues (ambiguity, structural problems, testability gaps)
- `pika implement` — turns the design spec into real code by planning, batching, and executing a series of AI agents

Both commands are **multi-phase sequential pipelines**. Many phases include a **blocking gate** — the CLI pauses and waits for the user to manually edit a YAML file to record their choices before it can continue.

The goal of this GUI feature is to merge these two commands into a single **"Design Improvement"** workflow with a rich interactive UI where the user can:
- Watch the pipeline progress in real time
- View their design spec throughout the process
- Make selections at each blocking gate without leaving the app
- Experience the whole process as a smooth, professional multi-step journey

---

## 2. The Combined Pipeline: All Phases in Order

The feature runs **Refine first, then Implement**. Together they form one continuous pipeline called "Design Improvement."

### Phase Group 1 — Refine (Spec Quality)

These phases analyze the design spec for quality issues before any code is generated.

| # | Phase Name | Type | Blocking? | Description |
|---|-----------|------|-----------|-------------|
| R1 | Load & Validate Spec | Deterministic | Never | Loads the design spec CSV, checks required columns (`spec_id`, `module_tag`, `module_role`, `requirement`, `acceptance_criteria`) |
| R2 | Decomposition Check | Deterministic (NLP) | **Conditional** | Detects specs with mixed responsibilities (split candidates) and specs that are overly similar within the same module (merge candidates). Uses sentence-level embedding variance. |
| R3 | Ambiguity Detection | Agent (AI) | **Conditional** | AI agent reads all specs in parallel and flags specs whose requirements or acceptance criteria are ambiguous or underspecified |
| R4 | Testability Audit | Agent (AI) | **Conditional** | AI agent reads all specs in parallel and flags specs that cannot be deterministically tested |

**Refine blocking behavior:** Phases R2, R3, R4 each produce a list of `manual_resolution_items`. Each item is a flag on one or more specs. If any items exist, the pipeline pauses and the user must resolve each item before continuing.

**Item option types in Refine:**
- `accept_suggestion` — accept the AI's proposed rewrite of the spec text
- `let_agent_edit` — delegate the fix to an AI agent (spec_editor)
- `skip` — keep the spec unchanged and continue

---

### Phase Group 2 — Implement (Code Generation)

These phases plan and execute code generation from the refined spec. They run after all Refine issues are resolved.

| # | Phase Name | Type | Blocking? | Description |
|---|-----------|------|-----------|-------------|
| I1 | Normalize Config | Deterministic | Never | Parse and normalize all implementation configuration (roles, policies, budgets) |
| I2 | Validate Workset | Deterministic | Never | Load design spec workset and verify required columns and fields |
| I3 | Validate Module Catalog | Deterministic | Never | Build module catalog and check role consistency across all rows |
| I4 | Prepare Path Contract | Deterministic | Never | Scan the codebase to define which paths the planner is allowed to touch |
| I5 | Run Unified Planner | Agent (AI) | Never (retries internally) | AI agent produces the full implementation plan: which files to create/modify, how specs depend on each other, shared data contracts between modules |
| I6 | Validate Planner Paths | Deterministic | Never | Verify planned file paths respect scope and ownership rules; retries planner if violated |
| I7 | Gate: Planner Blockers | Deterministic | **Conditional** | Block if the planner flagged items requiring human judgment before code can be written (e.g. unclear ownership, conflicting spec interpretations) |
| I8 | Gate: Dependency Gaps | Deterministic | **Conditional** | Block if cross-module dependency gaps exist that would make implementation incomplete |
| I9 | Validate Plan Structure | Deterministic | Never | Check spec coverage, dependency graph acyclicity, valid references, module coverage |
| I10 | Check Behavior Conflicts | Deterministic | Never | Detect incompatible failure behavior/status expectations between linked specs |
| I11 | Validate Contract Fields | Deterministic | Never | Verify field names and meanings align between spec text and shared data contracts |
| I12 | Check Contract Coverage | Deterministic | Never | Confirm every field a spec consumes from a shared contract is fully covered |
| I13 | Gate: Match Ambiguity | Deterministic | **Conditional** | Block on near-equal field or route matches where confidence scores are too close to call |
| I14 | Construct Batch Plan | Deterministic | Never | Group specs into execution batches respecting dependency order and budgets |
| I15 | Validate Batch Dependencies | Deterministic | Never | Confirm batch dependency IDs are valid, each spec appears exactly once, provider paths are reachable |
| I16 | Build Batch Briefs | Deterministic | Never | Assemble per-batch execution context (spec rows, planned anchors, shared contracts, dependency context) |
| I17 | Validate Brief Scope | Deterministic | Never | Confirm no cross-batch reference leakage in any brief |
| I18 | Check Dependency Edges | Deterministic | Never | Verify brief dependency edges exactly match the planner's approved dependency graph |
| I19 | Prepare Runtime Path Context | Deterministic | Never | Build per-batch path constraints and runtime file facts for the implementer agent |

**Per Batch (repeats for each batch B1, B2, …):**

| # | Phase Name | Type | Blocking? | Description |
|---|-----------|------|-----------|-------------|
| B-1 | Run Implementer Agent | Agent (AI) | Never (retries internally) | AI agent receives the batch brief and produces code diffs for all specs in the batch |
| B-2 | Validate Output Semantics | Deterministic | Never | Verify proposed changes respect semantic and path rules; retry agent if violated |
| B-3 | Validate Output Structure | Deterministic | Never | Check required sections, per-spec keys, and diff_refs completeness |
| B-4 | Validate Patch Constraints | Deterministic | Never | Enforce size/count budgets and forbidden-path policies on patch payloads |
| B-5 | Resolve Verification Commands | Deterministic | Never | Select test commands for this batch (from config or deterministic fallback) |
| B-6 | Normalize Patches | Deterministic | Never | Normalize hunk formatting and newlines for stable apply behavior |
| B-7 | Apply Patch Safety Gates | Deterministic | Never | Run `git apply --check` and safety gates before writing any changes |
| B-8 | Check Contract Schema Conformance | Deterministic | Never | Verify touched JSON schema files satisfy required-all + nullable contract policy |
| B-9 | Run Verification Commands | Deterministic | Never | Execute test/lint commands; mark batch failed if any exit non-zero |

---

## 3. Blocking Gates: The Interactive Breakpoints

These are the moments where the pipeline pauses for user input. Each gate surfaces a list of **resolution items**. The user must resolve every item to continue.

### Gate R-DECOMP: Spec Decomposition Issues

**Triggered when:** Decomposition check finds specs with high topic variance (split candidates) or high cross-spec similarity within a module (merge candidates)

**Item types:**
- `split_candidate` — One spec appears to cover multiple responsibilities
  - Options: `let_agent_edit` ("Let agent split into focused specs"), `skip` ("Keep as-is")
- `merge_candidate` — Two specs within the same module are nearly identical
  - Options: `let_agent_edit` ("Let agent merge into one spec"), `skip` ("Keep both")

**Item data available:** spec_id(s), reason, variance/similarity score

---

### Gate R-AGENTS: Ambiguity & Testability Review

**Triggered when:** Ambiguity Detector or Testability Auditor agents flag one or more specs

**Item types produced by Ambiguity Detector:**
- Specs with vague/contradictory requirements
- Specs missing concrete acceptance criteria

**Item types produced by Testability Auditor:**
- Specs that cannot be deterministically tested
- Specs with untestable acceptance criteria

**Option types per item:**
- `accept_suggestion` — Accept the AI's proposed rewrite (shows diff)
- `let_agent_edit` — Delegate fix to spec_editor agent
- `skip` — Keep spec unchanged

---

### Gate I-PLANNER: Planner Manual Blockers

**Triggered when:** The unified planner flags items requiring human judgment before code generation

**Common scenarios:** unclear spec ownership across modules, specs requiring decisions about which module "owns" a data contract, conflicting interpretations of a spec requirement

**Option types per item:** vary by item (typically `accept_suggestion`, `manual_resolution`, `skip`)

---

### Gate I-DEP-GAPS: Cross-Module Dependency Gaps

**Triggered when:** A spec depends on a shape (DTO, contract, paginated envelope) provided by a different module, but that shape is not declared as a shared contract in the plan

**Consequence:** If not resolved, the implementer will generate code with missing types/interfaces

**Option types per item:** typically `accept_suggestion` (accept the planner's proposed contract), `manual_resolution` (user provides the shape description), `skip`

---

### Gate I-AMBIGUITY: Match Ambiguity / Tie-Breaking

**Triggered when:** A field or route match has near-equal confidence scores across two candidates (tie or near-tie)

**Consequence:** If not resolved, the implementer might reference the wrong field or endpoint

**Option types per item:** `select_option_A`, `select_option_B`, `skip`

---

## 4. UI Architecture: The "Design Improvement" Screen

### 4.1 Overall Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│  TOP BAR                                                             │
│  [← Back]  Design Improvement  ●●●●●●●●○○○○  63%    [Cancel Run]   │
├────────────────────────────┬─────────────────────────────────────────┤
│                            │                                         │
│   LEFT PANEL               │   RIGHT PANEL                          │
│   Design Spec Viewer       │   Pipeline + Active Interaction         │
│                            │                                         │
│   Live view of the SADS    │   Scrollable vertical list of phases    │
│   CSV as a styled table    │   + expanded interaction card when      │
│                            │   blocked                               │
│   Rows can be highlighted  │                                         │
│   when a phase references  │                                         │
│   specific spec_ids        │                                         │
│                            │                                         │
└────────────────────────────┴─────────────────────────────────────────┘
```

**Panel proportions:** Left: 45%, Right: 55% (adjustable via drag handle)
**Scroll behavior:** Both panels scroll independently. Right panel auto-scrolls to the active phase.

---

### 4.2 Top Bar

```
┌──────────────────────────────────────────────────────────────────────┐
│  ←   Design Improvement        ━━━━━━━━━━━━━━━━━━━━━○○  82%        │
│       Run #4  ·  my-spec.csv   [Paused at Gate]    [Cancel Run]      │
└──────────────────────────────────────────────────────────────────────┘
```

- **Title:** "Design Improvement"
- **Run indicator:** Small run number + input filename
- **Progress bar:** Full-width horizontal bar using accent color. Fills left-to-right as phases complete. Shows integer percentage.
- **Status chip:** Small pill-shaped chip showing current state: `Running`, `Paused at Gate`, `Completed`, `Failed`. Color-coded.
- **Cancel button:** Right-aligned, ghost/outline style. Requires confirmation on click.

---

### 4.3 Left Panel: Design Spec Viewer

**Purpose:** The user should always be able to see their design spec during the process. When a blocking gate references specific specs, those rows are highlighted.

**Structure:**
```
┌────────────────────────────────────┐
│ DESIGN SPEC  ·  127 specs          │
│ [Search specs…]       [Filter ▾]   │
├────────────────────────────────────┤
│ spec_id  │ module_tag │ requirement │
│ ──────── │ ────────── │ ─────────── │
│ SPEC-001 │ auth       │ The system… │
│ SPEC-002 │ auth       │ Users shall…│
│◉ SPEC-003│ user_mgmt  │ The user…   │  ← highlighted (referenced)
│ SPEC-004 │ user_mgmt  │ Profiles…   │
└────────────────────────────────────┘
```

- **Columns shown:** spec_id, module_tag, requirement (truncated), current status indicators
- **Row highlighting:** Rows referenced by the current active gate are softly highlighted (light cyan background `#e8f9fd`). Rows already processed by a completed gate have a subtle checkmark indicator.
- **Scrollable:** The table scrolls vertically. When a gate is active, the viewer auto-scrolls to bring the first referenced spec into view.
- **Search/filter:** Simple text search by spec_id or requirement text. Module tag filter dropdown.
- **Expand row:** Clicking a row opens a slide-out drawer showing full spec details (all columns).

---

### 4.4 Right Panel: Pipeline View

The pipeline view has two modes:

**Mode 1: Running (no active gate)** — A vertical list of phase groups + phases. Each item shows its status with an icon and color.

**Mode 2: Blocked at gate** — The pipeline list collapses/dims all phases except the active gate. The gate expands into a full interactive resolution panel.

#### 4.4.1 Phase List Items

Each phase renders as a compact row:

```
  ✓  Load & Validate Spec              [DONE]
  ✓  Decomposition Check               [DONE · 0 issues]
  ◌  Ambiguity Detection               [Running…  ●●●○]
  ◌  Testability Audit                 [Running…  ●●○○]
  ─  Gate: Ambiguity & Testability     [Waiting]
  ─  Normalize Config                  [Pending]
  …
```

**Icon states:**
- `✓` (checkmark) — Completed successfully (color: `#0db7d9`)
- `⚠` (warning) — Blocked / needs resolution (color: amber `#f0a800`)
- `✗` (cross) — Failed (color: `#e05555`)
- `●●●○` (animated dots) — Currently running (cycling animation)
- `─` (dash) — Pending (grey)

**Phase group headers:** Refine and Implement are section headers in the list. Collapsed by default when completed, expandable on click.

**Batch progress:** When Implement batches are running, a sub-list shows each batch (B1, B2, …) as nested rows within the relevant batch phases.

---

#### 4.4.2 Gate Resolution Panel (Blocking State)

When a gate is active, the right panel transitions to show the gate's resolution UI. The phase list is still visible but dimmed above and below. The active gate expands to fill most of the available height.

```
┌────────────────────────────────────────────┐
│  ⚠  Gate: Ambiguity & Testability Review   │
│  11 items need your review to continue.    │
│                                            │
│  ●●●●●●●●○○○  9 / 11 resolved             │
│  [Continue ↓]  (disabled until all done)  │
├────────────────────────────────────────────┤
│  ITEM 1 of 11  ·  SPEC-003                 │
│  ┌──────────────────────────────────────┐  │
│  │ Ambiguity: Requirement underspecified│  │
│  │                                      │  │
│  │ "The user profile shall be updated   │  │
│  │  when requested."                    │  │
│  │                                      │  │
│  │ Reason: No triggering condition, no  │  │
│  │ actor, no latency/consistency spec.  │  │
│  │                                      │  │
│  │ Suggested rewrite:                   │  │
│  │ ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄ │  │
│  │ "When an authenticated user submits  │  │
│  │ a profile update request via the     │  │
│  │ PATCH /users/{id} endpoint, the      │  │
│  │ system shall persist the change…"    │  │
│  │ ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄ │  │
│  │                                      │  │
│  │ [✓ Accept suggestion]                │  │
│  │ [✎ Let agent edit]                   │  │
│  │ [— Keep as-is]                       │  │
│  └──────────────────────────────────────┘  │
│                                            │
│  [← Prev]              [Next →]            │
└────────────────────────────────────────────┘
```

**Gate header:** Gate name, item count, progress bar showing resolved/total. "Continue" button is disabled until all items are resolved.

**Item card:**
- Item number indicator ("ITEM 1 of 11") and spec_id(s) referenced
- Issue type label (e.g. "Ambiguity", "Testability Gap", "Split Candidate", "Merge Candidate", "Planner Blocker")
- Current spec text (if relevant), displayed in a monospace block
- Reason/explanation text from the AI
- Suggested rewrite (if available), displayed in a styled diff block with added text shown in `#e8f9fd` / `#99e1f0` background
- Option buttons (see below)

**Option buttons:** Full-width buttons stacked vertically. The selected option fills with the accent color (`#0db7d9`). Unselected options are outlined.

**Navigation:** Prev/Next to move through items. Already-resolved items show their selection with a checkmark. Users can change a selection by returning to a previous item.

---

### 4.5 Transition Between Phases

**Non-blocking phases:** Animate through automatically with a brief "pulsing" effect on the phase row. A subtle progress fill within each row shows internal progress. Duration is real — not simulated.

**Entering a gate:** The right panel smoothly transitions (300ms ease-out) from the phase list view into the gate resolution panel. A subtle ambient shift in the background color (from neutral white to a very light warm white `#fffdf5`) signals the pause.

**Exiting a gate:** After the user clicks "Continue", a brief agent-call animation plays (if needed for `let_agent_edit` items), then the pipeline resumes. Background transitions back to neutral white.

**Phase group completion:** When all Refine phases complete, a compact "Refine complete ✓" summary card appears at the top of the Implement section before Implement phases begin. Shows: total issues found, accepted/edited/skipped breakdown.

---

## 5. Screen States

### 5.1 Entry Screen (Before Run)

Before the pipeline starts, the user sees a setup screen.

```
┌─────────────────────────────────────────────────┐
│                                                 │
│   Design Improvement                            │
│   Refine and implement your design spec         │
│                                                 │
│   Design Spec  ─────────────────────────────   │
│   [  my-design-spec.csv  ·  127 specs  ▾  ]    │
│                                                 │
│   Codebase Directory  ──────────────────────    │
│   [  src/  ▾  ]                                 │
│                                                 │
│   Options  ─────────────────────────────────   │
│   ☑ Run Refine (spec quality check)            │
│   ☑ Run Implement (code generation)            │
│   ☑ Decomposition check                        │
│                                                 │
│              [  Start Design Improvement  →  ] │
│                                                 │
└─────────────────────────────────────────────────┘
```

The "Start" button is the primary CTA. Large, full-width at the bottom, accent color.

---

### 5.2 Completion Screen

When the pipeline finishes with no failures:

```
┌─────────────────────────────────────────────────┐
│                                                 │
│   ✓  Design Improvement Complete                │
│                                                 │
│   Refine:      14 specs improved                │
│   Implement:   3 batches ·  47 files changed   │
│   Duration:    4m 32s                           │
│                                                 │
│   [  View Changes  ]   [  Open in Editor  ]    │
│                                                 │
│   ──────────────────────────────────────────   │
│                                                 │
│   REFINED SPEC SAVED TO                        │
│   out/state/REFINED-SPEC.csv                   │
│                                                 │
│   [  Run Again  ]                               │
│                                                 │
└─────────────────────────────────────────────────┘
```

---

### 5.3 Failure Screen

When a phase fails (non-gate failure):

```
┌─────────────────────────────────────────────────┐
│   ✗  Run Failed at Phase I9                     │
│                                                 │
│   Validate Plan Structure                       │
│                                                 │
│   Error:                                        │
│   ┌──────────────────────────────────────────┐ │
│   │  Dependency cycle detected:              │ │
│   │  SPEC-003 → SPEC-012 → SPEC-003          │ │
│   └──────────────────────────────────────────┘ │
│                                                 │
│   [  Edit Design Spec  ]   [  Retry  ]         │
│                                                 │
└─────────────────────────────────────────────────┘
```

---

## 6. Visual Design Language

### 6.1 Color Palette

| Role | Color | Usage |
|------|-------|-------|
| Background (primary) | `#FFFFFF` | Main app background |
| Background (panel) | `#FAFAFA` | Spec viewer panel, side surfaces |
| Background (elevated) | `#F5F5F5` | Cards, hover states |
| Background (gate active) | `#FFFDF5` | Right panel when paused at gate |
| Background (highlighted row) | `#E8F9FD` | Spec rows referenced by active gate |
| Border (subtle) | `#E8E8E8` | Card borders, dividers |
| Border (medium) | `#D0D0D0` | Input borders, table lines |
| Text (primary) | `#111111` | Body text, labels |
| Text (secondary) | `#666666` | Descriptions, metadata, hints |
| Text (tertiary) | `#999999` | Placeholders, timestamps |
| Accent (primary) | `#0db7d9` | CTAs, active states, progress bars, selected options |
| Accent (light) | `#99e1f0` | Accent backgrounds, suggestion diffs, highlights |
| Accent (deep) | `#0891b2` | Hover state for accent elements |
| Indigo (dark) | `#1e3a5f` | Phase group headers, strong labels |
| Indigo (mid) | `#2d5a8e` | Secondary accents, module tags |
| Indigo (light) | `#dbeafe` | Indigo-tinted badges and chips |
| Success | `#16a34a` | Completed phase icons, success chips |
| Warning | `#f0a800` | Gate/blocked state, caution items |
| Error | `#e05555` | Failed phases, error messages |

### 6.2 Typography

- **Font:** Inter (system fallback: -apple-system, BlinkMacSystemFont, "Segoe UI")
- **Weights used:** 400 (body), 500 (labels, table headers), 600 (section headers, gate titles), 700 (completion headings)
- **Sizes:**
  - Top bar title: 15px / 600
  - Section headers: 13px / 600 / letter-spacing 0.06em / uppercase / `#666666`
  - Phase row text: 14px / 500
  - Gate item title: 16px / 600
  - Spec text block: 13px / 400 / monospace (JetBrains Mono or similar)
  - Body/reason text: 14px / 400 / `#444444`
  - Metadata / timestamps: 12px / 400 / `#999999`

### 6.3 Spacing & Shape

- **Border radius:** 8px (cards), 6px (buttons), 4px (chips, badges), 2px (table rows)
- **Card shadow:** `0 1px 3px rgba(0,0,0,0.07), 0 4px 12px rgba(0,0,0,0.04)`
- **Spacing unit:** 4px base. Major sections: 24px gap. Within cards: 16px padding. Within rows: 12px vertical, 16px horizontal.
- **Dividers:** 1px `#E8E8E8` horizontal lines. Never use vertical dividers inside cards.

### 6.4 Motion

- **Phase transitions:** 250ms ease-out for phase row status changes (icon swap + color fill)
- **Gate enter/exit:** 300ms ease-in-out slide + fade. Background color shift 400ms ease.
- **Agent running animation:** Three dots pulsing sequentially (not spinning). Duration: 1.2s loop.
- **Progress bar fill:** 600ms ease-out per segment. No sudden jumps.
- **Row highlight:** 200ms ease-in fade from transparent to `#E8F9FD`
- **Option selection:** 150ms ease. Selected button fills with `#0db7d9`, other options fade slightly.
- **No decorative animations.** Every motion serves a functional purpose (communicates progress, signals state change, guides attention).

### 6.5 Interactive Elements

**Primary button (CTA):**
```
Background: #0db7d9
Text: #FFFFFF, 14px/600
Padding: 10px 20px
Radius: 6px
Hover: background #0891b2, transition 150ms
Disabled: background #D0D0D0, text #999999, cursor: not-allowed
```

**Secondary/ghost button:**
```
Background: transparent
Border: 1.5px solid #D0D0D0
Text: #444444, 14px/500
Padding: 10px 20px
Radius: 6px
Hover: border-color #0db7d9, text #0db7d9
```

**Option selection button (in gates):**
```
Full-width
Background (unselected): #FFFFFF, border 1.5px #D0D0D0
Background (selected): #0db7d9, border transparent, text #FFFFFF
Background (hover unselected): #F5F5F5
Text: 14px/500
Padding: 12px 16px
Radius: 6px
Left-aligned text with icon on left
```

**Status chip:**
```
Running:    background #dbeafe,  text #2d5a8e,  dot: animated #0db7d9
Blocked:    background #FFF3CD,  text #856404,  dot: static #f0a800
Completed:  background #DCFCE7,  text #166534,  dot: static #16a34a
Failed:     background #FEE2E2,  text #991B1B,  dot: static #e05555
```

### 6.6 Table (Design Spec Viewer)

```
Header row: background #F5F5F5, text #666666 12px/600 uppercase, border-bottom 1px #E8E8E8
Body rows: background #FFFFFF, alternating #FAFAFA, height 40px
Highlighted row: background #E8F9FD, left border 3px #0db7d9
Hover row: background #F5F5F5 (non-highlighted), cursor: pointer
spec_id column: monospace, #2d5a8e, 600 weight
module_tag column: small pill badge, indigo-tinted (#dbeafe bg, #2d5a8e text)
requirement column: truncated with ellipsis, max-width: 320px
```

---

## 7. Data Flow for the Designer

The designer should understand what data moves through the UI at each phase:

```
INPUT:
  design-spec.csv
      │
      ▼
┌─────────────────────────────────────────────────────┐
│  REFINE PIPELINE                                    │
│                                                     │
│  Load CSV → NLP Check → [Gate R-DECOMP?]           │
│                                                     │
│         → Agent Analysis (parallel)                 │
│           ├─ Ambiguity Detector                     │
│           └─ Testability Auditor                    │
│                                                     │
│         → [Gate R-AGENTS?]                          │
│                                                     │
│  Resolved items → spec_editor agent runs if needed  │
│  Output: REFINED-SPEC.csv                           │
└─────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────┐
│  IMPLEMENT PIPELINE                                 │
│                                                     │
│  Validate → Build Catalog → Path Contract           │
│         → Unified Planner Agent                     │
│         → [Gate I-PLANNER?]                         │
│         → [Gate I-DEP-GAPS?]                        │
│         → Plan Validations (×4)                     │
│         → [Gate I-AMBIGUITY?]                       │
│         → Batch Plan → Briefs → Validations (×4)   │
│                                                     │
│  FOR EACH BATCH:                                    │
│  └─ Implementer Agent → Validate → Patch → Verify  │
│                                                     │
│  Output: Code changes + trace artifacts             │
└─────────────────────────────────────────────────────┘
      │
      ▼
DONE: refined spec + generated code
```

---

## 8. Specific Interaction Design Guidance

### 8.1 Multi-Item Gate Navigation

When a gate has more than 5 items, navigation changes from simple Prev/Next to a sidebar list:

```
┌──────────────────────────────────────────────────┐
│  ⚠  Gate: Ambiguity & Testability Review         │
├──────────────┬───────────────────────────────────┤
│ ITEMS (11)   │  SPEC-003  ·  Ambiguity           │
│              │  ──────────────────────────────── │
│ ✓ SPEC-001   │  "The user profile shall be       │
│ ✓ SPEC-002   │   updated when requested."        │
│ ● SPEC-003   │                                   │
│ ○ SPEC-004   │  Reason: No triggering condition, │
│ ○ SPEC-005   │  no actor, no latency spec.       │
│ ○ SPEC-006   │                                   │
│ ○ SPEC-007   │  Suggestion:                      │
│ ○ SPEC-008   │  ┌──────────────────────────────┐ │
│ ○ SPEC-009   │  │ "When an authenticated user  │ │
│ ○ SPEC-010   │  │  submits a profile update…"  │ │
│ ○ SPEC-011   │  └──────────────────────────────┘ │
│              │                                   │
│              │  [✓ Accept]  [✎ Agent]  [— Keep] │
│              │                      [Continue →] │
└──────────────┴───────────────────────────────────┘
```

Sidebar legend: `✓` resolved, `●` current, `○` pending

### 8.2 Spec-Viewer Sync

When navigating between items in a gate, the left panel (design spec viewer) automatically scrolls to and highlights the spec_id(s) referenced by the current item. This creates a feeling of the spec being "alive" — the user sees exactly which part of their spec is being discussed.

### 8.3 Refine Summary Before Implement

After all Refine gates are resolved and the REFINED-SPEC.csv is written, a brief "phase boundary" card appears in the pipeline:

```
┌─────────────────────────────────────────────────────┐
│  ✓  Refine Complete                                 │
│  ─────────────────────────────────────────────────  │
│  14 specs reviewed · 6 accepted suggestions         │
│  3 agent edits · 5 kept as-is · 0 issues skipped   │
│                                                     │
│  Refined spec saved to out/state/REFINED-SPEC.csv   │
│                                                     │
│  Starting Implementation…                           │
└─────────────────────────────────────────────────────┘
```

This card stays visible (pinned) at the top of the pipeline list as Implement phases proceed, acting as a receipt.

### 8.4 Batch Progress in Implement

When Implement begins batch execution (phases B-1 through B-9, repeated per batch), the batch phases should be rendered as a nested sub-list under a collapsible "Batch Execution" section:

```
  ✓  Construct Batch Plan                   [3 batches]
  ✓  Validate Batch Dependencies            [ok]
  ✓  Build Batch Briefs                     [ok]
  ✓  Validate Brief Scope                   [ok]
  ✓  Check Dependency Edges                 [ok]
  ✓  Prepare Runtime Path Context           [ok]
  ▼  Batch Execution                        [B1 ✓ · B2 ✓ · B3 ●●●○]
     ├─ Batch 1  ✓  12 specs · 18 files
     ├─ Batch 2  ✓  20 specs · 31 files
     └─ Batch 3  ●  19 specs · running…
```

---

## 9. Edge Cases to Design For

| Scenario | How to handle |
|----------|--------------|
| Gate has 0 items (passes automatically) | Show phase row transition from "running" to "done" instantly. No gate panel opens. Optional toast: "No issues found." |
| Agent call fails mid-run | Show phase row as "failed" (red ✗). Show failure screen overlay with error message and "Retry" button. |
| User cancels during a gate | Show confirmation dialog: "Cancel will discard unsaved selections. Continue?" with "Keep working" and "Cancel run" buttons. |
| Very long spec (500+ rows) | Table virtualizes rows. Spec viewer shows only 50 rows at a time with pagination. Highlighted rows auto-navigate pages. |
| Batch failure (verification commands exit non-zero) | Show failure within the batch sub-row. Error log is expandable inline. Other batches continue if they are independent. |
| Run resumes from a prior blocked state | Pipeline shows completed phases pre-filled as ✓. Opens directly at the first unresolved gate. |
| User changes a previously-resolved item | Allowed freely until "Continue" is clicked. Selections are ephemeral until Continue. |
| All items at a gate are skipped | "Continue" becomes enabled. Show a warning chip: "All items skipped. Proceed?" |

---

## 10. Developer Handoff Notes (for reference)

These notes explain the CLI backend behavior the GUI needs to drive. The GUI is a frontend for the CLI runtime — it invokes the CLI with flags and reads structured run artifacts from disk.

**Run artifacts directory:** `out/agent_runs/{command}/{run_id}/`

**Key files the GUI reads:**
- `run_meta.json` — current phase, blocked_at_stage, completed_stages, resolution_status
- `manual_resolution/{stage}.json` — items for the active gate
- `manual_resolution/resolutions.yaml` — the file the user's selections must be written into (this is what the GUI writes on behalf of the user instead of them editing YAML manually)
- `summary.json` — final run summary when completed

**Key signals:**
- `resolution_status: "pending"` in run_meta → gate is active, show gate panel
- `resolution_status: "running"` → pipeline is running, show phase list
- `resolution_status: "not_needed"` → completed cleanly

The GUI replaces manual YAML editing entirely. Instead of the user editing `resolutions.yaml`, the GUI writes it programmatically from the option selections made in the gate panel.
