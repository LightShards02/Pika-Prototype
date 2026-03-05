# Implement Pipeline: Anchor-Linker Design (Archived)

This document describes the anchoring / anchor-linking / batching pipeline
used in the `implement` command **before** the Unified Planner redesign.
It is committed alongside the code so the branch
`archive/anchor-linker-design` preserves the full design for reference.

---

## 1. Current Design Overview

The implement command converts a Formatted SADS (design spec CSV) into
working code through a multi-stage pipeline:

```
Design Spec ──► Workset ──► Module Catalog
                                │
                    ┌───────────┴──────────┐
                    │  Anchor Planner (x N) │  one agent call per module
                    └───────────┬──────────┘
                                │  anchor_plans/{M}.json
                                ▼
                    ┌───────────────────────┐
                    │  Normalization (det.)  │  rewrite intent kinds, score candidates
                    └───────────┬───────────┘
                                │  anchor_plans_normalized/{M}.json
                                │  normalized_intent_catalog.json
                                ▼
                    ┌───────────────────────┐
                    │  Anchor Linker (1+)   │  one agent call + retries
                    └───────────┬───────────┘
                                │  link_plan.json (contracts, bindings)
                                ▼
                    ┌───────────────────────┐
                    │  Link Validation      │  deterministic checks
                    └───────────┬───────────┘
                                ▼
                    ┌───────────────────────┐
                    │  Build Batches (det.) │  topological order, budget chunking
                    └───────────┬───────────┘
                                │  batch_plan.json
                                ▼
                    ┌───────────────────────┐
                    │  Build Briefs (det.)  │  per-batch context packages
                    └───────────┬───────────┘
                                │  batch_briefs/B{N}.json
                                ▼
                    ┌───────────────────────┐
                    │  Confidence Check     │  blocks on low-confidence items
                    └───────────┬───────────┘
                                ▼
                    ┌───────────────────────┐
                    │  Execute Batches (xN) │  one agent call per batch
                    └───────────┬───────────┘
                                ▼
                    ┌───────────────────────┐
                    │  Translate            │  update DESIGN-SPEC.csv, test_spec.csv
                    └───────────────────────┘
```

### 1.1 Anchor Planner (per module)

Each module is sent to the `implement_anchor_planner` agent independently.
The agent receives only the specs belonging to that module and produces:

- **planned_anchors** — file paths, symbol names, anchor kinds (`new_symbol`,
  `existing_symbol`, `file_location`, `boundary_file`) and materialization
  kinds (`schema`, `interface`, `runtime_logic`, `wiring`, `test`).
- **provided_intents** — abstract capability descriptions this module offers
  to other modules (intent_local_id, kind, capability_name, inputs, outputs,
  error_modes, confidence).
- **required_intents** — abstract capability descriptions this module needs
  from other modules.

Schema: `schemas/agent_outputs/implement_anchor_planner_output.schema.json`

### 1.2 Normalization (deterministic)

`core/implement_normalization.py` rewrites intent kinds and enforces policies:

- **Kind rewrites** — for frontend modules, `external_api` intents targeting
  internal API routes are rewritten to `api_endpoint`.
- **Leaf dependency policy** — for leaf-role modules (e.g. infra), required
  intents are moved to `declared_external_dependencies` and cleared.
- **Intent scoring** — `score_intent_candidates()` builds a deterministic
  ranking of provided intents for each required intent using token overlap
  (capability 22%, IO 22%, error 10%, intent_local_id 28%, module affinity
  18%) to produce `normalized_intent_catalog.json`.

### 1.3 Anchor Linker (global, one agent call)

The `implement_anchor_linker` agent receives all normalized anchor plans and
the intent catalog. It produces:

- **contracts** — interface definitions (contract_id, kind, canonical_name,
  shape, optional type_locations).
- **bindings** — maps each required_ref (module_tag + intent_local_id) to a
  provided_ref with a contract_id, confidence score, and rationale. May flag
  `adapter_needed` with an `adapter_plan`.
- **integration_actions** (optional) — cross-module wiring steps.

Schema: `schemas/agent_outputs/implement_anchor_linker_output.schema.json`

### 1.4 Validation, Batching, and Execution

- **Link validation** checks all required intents are bound, role rules are
  respected, and type placements are correct. On failure, a retry context is
  built and the linker is re-invoked (up to `linker_max_attempts`).
- **Batching** builds a consumer→provider dependency graph from bindings,
  computes Tarjan SCCs + topological order, and chunks specs by budget
  (`max_specs_per_batch`, `max_files`).
- **Briefs** package per-batch context (spec rows, relevant contracts,
  bindings, anchors, constraints).
- **Execution** invokes the `implement_from_specs` agent per batch, producing
  diffs that PIKA applies to the codebase.

---

## 2. Limitations of the Current Design

### 2.1 The Intent Abstraction Layer

The core problem is architectural: the planner creates **abstract intents**
per module in isolation, and the linker must **match** them across modules.
This introduces an unnecessary indirection layer that amplifies ambiguity.

The design spec already encodes cross-module relationships in natural
language (e.g., spec A1015 says "invoke CORE calorie and macro calculation
service"), but the intent abstraction forces the model to invent capability
names, then match them — a task a human architect would never perform.

### 2.2 Three Failure Classes

Based on the nutrition dataset run (20260304_190903), all 14 manual
resolution items fall into three classes:

#### Class 1: Granularity Mismatch (3 items)

The planner creates fine-grained intents per provider module but
coarse-grained required intents on the consumer side. The linker cannot
reconcile 1-to-many mappings.

| Item ID | Problem |
|---------|---------|
| MR-API-REQ-CORE-CALC | API needs "full calculation service"; CORE exposes 6 separate steps (BMR, TDEE, goal, macro, rounding, validation) |
| MR-API-REQ-SHARED-DTO-BUNDLE | API needs "all DTOs"; SHARED exposes 5 separate DTO contracts |
| MR-API-REQ-DATA-PROVIDER-ADAPTER | API intent spans startup + runtime; DATA has separate handshake and search intents |

#### Class 2: Shape / Field Mismatch (6 items)

Required intents define composite types while providers expect decomposed
fields, or vice versa. The linker cannot deterministically transform between
shapes it did not design.

| Item ID | Problem |
|---------|---------|
| MR-API-REQ-CREDENTIAL-RECORD-SHAPE | Required output is composite `credential_record`; provider returns three separate fields |
| MR-API-REQ-PASSWORD-VERIFY-INPUT | Required has 1 aggregate `verification_input`; provider expects 3 explicit fields |
| MR-API-REQ-HISTORY-READ-QUERY-SHAPE | Different query structures between API and DATA |
| MR-API-REQ-EXPORT-BUILDER-INPUT | Required intent does not include `history_records`; provider requires them |
| MR-API-REQ-ARTIFACT-METADATA-SHAPE | Required output is abstract; provider returns concrete fields |
| MR-API-REQ-OBS-METRICS | Output `record_status` is not directly in any OBS provider intent |

#### Class 3: Cross-Boundary Field Mapping (5 items)

UI-to-API field mappings are left as `manual_map` placeholders because the
linker lacks sufficient context to determine exact field projections.

| Item ID | Problem |
|---------|---------|
| MR-UI-REQ-NUTRITION-CALCULATE-MAPPING | Multiple manual_map placeholders for request/response fields |
| MR-UI-REQ-AUTH-LOGIN-MAPPING | Token fields and remember_me not deterministically mapped |
| MR-UI-REQ-SESSION-RESTORE-MAPPING | User object projection left under manual mapping |
| MR-UI-REQ-HISTORY-QUERY-PAGINATION | Pagination outputs not deterministically mapped |
| MR-UI-REQ-EXPORT-GENERATE-MAPPING | Export identifier mapping unspecified |

### 2.3 Systemic Cost

- **Agent call count**: 6 planner calls + 1-3 linker calls + N batch calls
  = 7-9 agent calls before any code is generated.
- **Cascading errors**: a poor anchor plan leads to worse linking, which
  leads to bad batches.
- **Blocking frequency**: the linker consistently produces manual resolution
  items, halting the entire pipeline.
- **Normalization complexity**: 200+ lines of deterministic scoring logic
  exists solely to help the linker, yet fails to prevent mismatches.

---

## 3. Alternatives Considered

### Alternative A: Keep Planner + Linker, Improve Matching

Replace the LLM-based linker with embedding-based intent matching.

**Pros:**
- Cheaper per-match (embedding similarity is fast and deterministic).
- Could reduce manual resolution items for exact-name matches.
- No change to the planner; minimal code impact.

**Cons:**
- Still suffers from granularity mismatch (Class 1). Embeddings cannot map
  one coarse intent to six fine-grained intents.
- Still suffers from shape mismatch (Class 2). Embeddings match names, not
  structural compatibility.
- Cross-boundary field mapping (Class 3) is unsolvable by embeddings alone.
- **The abstraction layer itself is the problem**, not the matching
  algorithm. This alternative treats the symptom, not the cause.

**Verdict:** Does not resolve 12 of 14 observed failures.

### Alternative B: Fully Agent-Driven Single Pass (Plan + Batch)

A single agent call produces the dependency plan AND batch assignments.

**Pros:**
- Eliminates the intent abstraction entirely — single holistic view.
- Maximum reduction in agent calls (1 planning call total).
- Simplest possible pipeline.

**Cons:**
- Batching is a deterministic operation (topological sort + budget chunking).
  Making it agent-driven adds non-determinism for no benefit.
- Batch assignments become harder to validate and reproduce.
- If the agent produces a bad batch grouping, the only recourse is to
  re-invoke the entire planning + batching call.
- Mixes two concerns (architectural planning vs. mechanical grouping) in one
  agent output, increasing schema complexity and failure surface.

**Verdict:** Correct direction but over-delegates. Batching should remain
deterministic. The agent should produce the dependency graph; PIKA should
compute batches from it.

### Alternative C: Spec Clustering Before Planning

Deterministically cluster specs by module + subunit, then plan each cluster
with cross-cluster context visible. A lightweight linking step resolves
cross-cluster dependencies.

**Pros:**
- Reduces per-call context size for very large specs (500+).
- Each cluster is a coherent unit of work.
- Cross-cluster context visibility mitigates the isolation problem of the
  current per-module planner.

**Cons:**
- Still requires a linking step for cross-cluster dependencies, re-
  introducing the matching problem (albeit smaller).
- Premature optimization for current spec sizes (64 rows, ~12K tokens).
- Clustering heuristics may split related specs across clusters.
- Adds complexity vs. a single-pass planner that sees everything.

**Verdict:** Viable escape hatch if spec counts exceed ~500 rows and context
window becomes a constraint. Not justified at current scale.

---

## 4. Decision

Replace the anchoring / anchor-linking / batching pipeline with a **Unified
Planner** that:

1. Receives the full design spec in one agent call.
2. Produces per-module file plans (planned anchors), an explicit spec-to-spec
   dependency graph, and shared contract declarations.
3. Feeds the dependency graph to deterministic batching (unchanged).
4. Per-batch implementation proceeds as before.

This eliminates the intent abstraction, the normalization layer, and the
linker entirely — resolving all three failure classes at the root cause.

---

## 5. Key Files in This Archive

| File | Purpose |
|------|---------|
| `handlers/implement/impl.py` | Main orchestrator (planner loop + linker + batching) |
| `handlers/implement/batching.py` | Batch building and brief construction |
| `handlers/implement/validation.py` | Link plan and batch plan validation |
| `core/implement_normalization.py` | Intent normalization and scoring |
| `core/implement_types.py` | TypedDicts for intents, bindings, batches |
| `schemas/agent_outputs/implement_anchor_planner_output.schema.json` | Planner output schema |
| `schemas/agent_outputs/implement_anchor_linker_output.schema.json` | Linker output schema |
| `prompts/PROMPT.yaml` | Agent prompts (implement_anchor_planner, implement_anchor_linker) |
| `docs/implement_dependency_diagram.md` | Data flow documentation |
