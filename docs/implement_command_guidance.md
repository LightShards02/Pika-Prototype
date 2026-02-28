# PIKA `implement` Command — Implementation Guidance
*(Contract-first, schema-driven, traceable, token-efficient)*

This document is a **step-by-step implementation guide** for the PIKA `implement` command.  
**Companion:** `docs/implement_appendix_examples.md` — full Nutrition Calculator examples.  

---

## 0) Terminology and run directory layout

### 0.1 Key objects
- **Spec**: one row in Formatted SADS (must include `spec_id`).
- **module_tag**: required SADS column (manually added); partition key for spec grouping. The implement command does not use `subunit`.
- **Module**: a grouping unit with a deterministic **module_role** (see §2.2).
- **Intent**: a module-local description of a capability that is either:
  - **provided_intent** (what this module will expose)
  - **required_intent** (what this module needs, provider unknown during planning)
- **Contract**: a global, canonical capability definition created by the linker by binding intents.
- **Binding**: the canonical mapping of `required_intent` ↔ `provided_intent` via a `contract_id`.

### 0.2 Run workspace layout
Within `agent_runs_dir` (per config):

- `run_meta.json` — run settings snapshot
- `inputs/` — SADS snapshot (or hashes), issue tracker snapshot
- `module_catalog.json` — module_tag → module_role mapping
- `anchor_plans/` — per-module planner outputs
- `link_plan.json` — global linker output
- `manual_resolution/` — user answers stored as `answer` field in each manual_resolution_item JSON
- `batch_plan.json` — batches + ordering + budgets used
- `batch_briefs/` — one brief per batch (for implement executor)
- `agent_outputs/` — validated JSON outputs per agent call
- `patches/` — unified diff files
- `verification/` — logs + exit codes per batch
- `trace/trace.jsonl` — append-only trace ledger
- `summary.json` — final command summary

---

## 1) High-level workflow overview

### Phase A — Deterministic preparation (PIKA)
1. Run setup + safety preflight
2. Select spec workset (deterministic; implementation_status != done)
3. Build module catalog with **module_role** (deterministic)

### Phase B — Planning (agents, schema-validated, blocking manual resolution)
4. **Anchor Planner** (per module): produces *planned anchors* + *intents* (no cross-module knowledge)
5. Manual resolution loop (if planner emits items)
6. **Anchor Linker** (global): binds intents → contracts + bindings; may emit integration actions
7. Manual resolution loop (if linker emits items)

### Phase C — Execution (diff-only, verified, traceable)
8. Build dependency graph from bindings + intra-module deps
9. Create batches (budgets enforced); **Batch 0 Integration** only if linker emitted `integration_actions`
10. For each batch: build batch brief → invoke Implementer agent → validate → apply in git worktree → verify → accept → trace
11. Translate implementer `mapped_classes_functions` + `mapped_test_cases` into design spec updates
12. Finalize summary artifacts and return status

---

## 2) Contracts (schemas in bullet form)

### 2.1 Manual resolution item (blocking)
Used by any agent when decisions are required. PIKA stores the user's answer as an `answer` field in the item JSON.

Fields:
- `item_id` (string): stable identifier for this question.
- `title` (string): short label.
- `question` (string): what the user must decide.
- `options[]` (list):
  - `option_id` (string)
  - `label` (string)
  - `effect` (string): what choosing this does.
- `recommended_option_id` (string, optional)
- `required` (bool): must be true for blocking items.
- `blocking_reason` (string): why it blocks.
- `evidence_refs[]` (optional): pointers to run artifacts that justify the question.

**Example**
```json
{
  "item_id": "MR_001",
  "title": "Default macro preset",
  "question": "If preset is omitted, default to Balanced or require explicit preset?",
  "options": [
    {"option_id":"A","label":"Default Balanced","effect":"Server fills missing preset=BALANCED"},
    {"option_id":"B","label":"Require preset","effect":"ValidationError if missing"}
  ],
  "recommended_option_id": "A",
  "required": true,
  "blocking_reason": "Affects request schema + validation behavior"
}
```

---

### 2.2 Module catalog (deterministic classification)
**Goal:** provide the linker enough structure without per-project layer rules (baked in prompt + validator).

Fields:
- `modules[]`:
  - `module_tag` (string): partition key used for spec grouping.
  - `module_role` (enum): **frontend | api | domain | infra | shared | cli | worker**
  - `root_dirs[]` (list of paths): where code for this module resides.
  - `languages[]` (optional): e.g., `["python"]`, `["typescript"]`.

**Example**
```json
{
  "modules": [
    {"module_tag":"UI","module_role":"frontend","root_dirs":["ui-web/"]},
    {"module_tag":"API","module_role":"api","root_dirs":["api-server/"]},
    {"module_tag":"CORE","module_role":"domain","root_dirs":["nutrition-core/"]},
    {"module_tag":"DATA","module_role":"infra","root_dirs":["food-data/"]},
    {"module_tag":"OBS","module_role":"infra","root_dirs":["obs/"]}
  ]
}
```

---

### 2.3 Module Anchor Plan (output of Anchor Planner per module)
**Planner input is module-local** (it does not know other modules exist).

Fields:
- `module_tag` (string)
- `planned_anchors[]`:
  - `anchor_kind` (enum): `new_symbol | existing_symbol | file_location | boundary_file`
  - `planned_file_path` (path, relative)
  - `planned_symbol` (string, optional): e.g., `NutritionService.calc`
  - `signature_hint` (string, optional)
  - `spec_ids[]` (list of spec ids)
- `provided_intents[]`:
  - `intent_local_id` (string): unique within this module.
  - `kind` (enum): `api_endpoint | service_interface | event_topic | db_table | file_format | external_api | test_suite`
  - `capability_name` (string): short semantic name (no module binding).
  - `description` (string): 1–3 lines.
  - `inputs[]`, `outputs[]` (list of `{name,type_name,constraints[]?}`)
  - `error_modes[]` (list)
  - `nonfunctional` (object, optional): latency, cache TTL, rate_limit, etc.
  - `planned_anchor` (object): `{file_path, symbol_name}`
  - `spec_ids[]`
  - `confidence` (0–1)
- `required_intents[]`: same structure but includes:
  - `call_site_plan` (object): `{planned_file_path, planned_symbol, invocation_pattern?}`
  - `provider_constraints` (optional): e.g., `{"must_be_api_endpoint": true}`
- `intra_module_dependencies[]` (optional):
  - `{spec_id, depends_on[], reason}`

**Example (very concise)**
```json
{
  "module_tag": "API",
  "planned_anchors": [
    {"anchor_kind":"new_symbol","planned_file_path":"api-server/app/routes/nutrition.py","planned_symbol":"post_calc","spec_ids":["SPEC-API-001"]}
  ],
  "provided_intents": [
    {
      "intent_local_id":"API_PROV_1",
      "kind":"api_endpoint",
      "capability_name":"CalcNutrition",
      "description":"POST /api/nutrition/calc returns calories+macros.",
      "inputs":[{"name":"body","type_name":"NutritionCalcRequest"}],
      "outputs":[{"name":"body","type_name":"NutritionCalcResponse"}],
      "error_modes":["ValidationError","RateLimited"],
      "planned_anchor":{"file_path":"api-server/app/routes/nutrition.py","symbol_name":"post_calc"},
      "spec_ids":["SPEC-API-001"],
      "confidence":0.85
    }
  ],
  "required_intents": [
    {
      "intent_local_id":"API_REQ_1",
      "kind":"service_interface",
      "capability_name":"ComputeNutrition",
      "description":"Compute calories+macros from profile.",
      "inputs":[{"name":"profile","type_name":"NutritionProfile"}],
      "outputs":[{"name":"result","type_name":"NutritionResult"}],
      "error_modes":["ValidationError"],
      "call_site_plan":{"planned_file_path":"api-server/app/services/nutrition_service.py","planned_symbol":"NutritionService.calc"},
      "spec_ids":["SPEC-API-001"],
      "confidence":0.8
    }
  ]
}
```

---

### 2.4 Global Link Plan (output of Anchor Linker)
**Adopted improvement:** no `module_dependency_edges`; downstream derives edges from `bindings`.

Fields:
- `contracts[]`:
  - `contract_id` (string): canonical id, versioned.
  - `kind` (same enum)
  - `canonical_name` (string)
  - `shape` (object): minimal signature/schema (endpoint path+method or function signature).
  - `type_locations` (object): `{type_name: shared_path}` for cross-module DTOs.
- `bindings[]` (**single source of truth**):
  - `required_ref`: `{module_tag, intent_local_id}`
  - `provided_ref`: `{module_tag, intent_local_id}`
  - `contract_id`
  - `confidence` (0–1)
  - `rationale` (short)
  - `adapter_needed` (bool, optional)
  - `adapter_plan` (optional): `{location_module_tag?, planned_file_path?, description}`
- `integration_actions[]` (optional):
  - `action_id`
  - `type` (enum): `create_shared_contracts | add_adapter | add_di_wiring | add_smoke_tests`
  - `details` (object): action-specific
- `manual_resolution_items[]` (optional; if present, output must contain **only** these items)

**Example (one contract + one binding)**
```json
{
  "contracts": [
    {
      "contract_id":"ctr.svc.computeNutrition.v1",
      "kind":"service_interface",
      "canonical_name":"ComputeNutrition",
      "shape":{"function":"compute_nutrition(profile: NutritionProfile) -> NutritionResult"},
      "type_locations":{
        "NutritionProfile":"shared-contracts/nutrition_domain.py",
        "NutritionResult":"shared-contracts/nutrition_domain.py"
      }
    }
  ],
  "bindings": [
    {
      "required_ref":{"module_tag":"API","intent_local_id":"API_REQ_1"},
      "provided_ref":{"module_tag":"CORE","intent_local_id":"CORE_PROV_1"},
      "contract_id":"ctr.svc.computeNutrition.v1",
      "confidence":0.9,
      "rationale":"API needs ComputeNutrition; CORE provides matching signature."
    }
  ],
  "integration_actions":[
    {
      "action_id":"INT_1",
      "type":"create_shared_contracts",
      "details":{"target_path":"shared-contracts/","files":["nutrition_domain.py"]}
    }
  ]
}
```

---

### 2.5 Batch plan (deterministic; derived from link plan + budgets)
Fields:
- `batches[]`:
  - `batch_id` (string)
  - `kind` (enum): `integration | module_impl`
  - `spec_ids[]` (list; can be empty for integration-only batches)
  - `module_tags[]` (list; for module batches)
  - `depends_on_batches[]`
  - `rationale` (short)
  - `budgets_applied` (object): max files/lines/context tokens etc.

**Example**
```json
{
  "batches": [
    {"batch_id":"B0","kind":"integration","spec_ids":[],"module_tags":["SHARED"],"depends_on_batches":[],"rationale":"Create shared DTOs for linked contracts"},
    {"batch_id":"B1","kind":"module_impl","spec_ids":["SPEC-CORE-001"],"module_tags":["CORE"],"depends_on_batches":["B0"],"rationale":"Provide ComputeNutrition before API consumes it"}
  ]
}
```

---

### 2.6 Batch brief (input to implement executor for one batch)

**For integration batches (B0):** Include `integration_actions` from link plan; `spec_rows` may be empty.  
**For module_impl batches:** Include spec_rows, relevant_contracts, relevant_bindings, planned_anchors.

Fields:
- `batch_id`
- `spec_rows[]` (only those in batch; empty for integration-only B0)
- `relevant_contracts[]` (subset of `contracts` referenced by this batch)
- `relevant_bindings[]` (bindings touching this batch’s modules/specs)
- `planned_anchors[]` (subset)
- `constraints`:
  - `forbidden_paths[]`
  - `budgets_applied`
  - `verification_commands[]`
  - `traceability_rules` (e.g., every diff item must list `spec_ids`)

**Example**
```json
{
  "batch_id":"B1",
  "spec_rows":[{"spec_id":"SPEC-CORE-001","requirement":"Compute BMR/TDEE...","acceptance_criteria":"Unit tests pass..."}],
  "relevant_contracts":[{"contract_id":"ctr.svc.computeNutrition.v1","kind":"service_interface","shape":{"function":"compute_nutrition(profile)->result"}}],
  "relevant_bindings":[{"required_ref":{"module_tag":"API","intent_local_id":"API_REQ_1"},"provided_ref":{"module_tag":"CORE","intent_local_id":"CORE_PROV_1"},"contract_id":"ctr.svc.computeNutrition.v1"}],
  "planned_anchors":[{"planned_file_path":"nutrition-core/nutrition/calculator.py","planned_symbol":"compute_nutrition"}],
  "constraints":{
    "forbidden_paths":["docs/","specs/"],
    "verification_commands":["pytest -q"],
    "traceability_rules":{"require_spec_ids_per_diff":true}
  }
}
```

---

### 2.7 Implementer output (diff-only; schema-validated)
Per PROJECT_CONTEXT, agent writes large diffs to files and returns paths. See `docs/implement_appendix_examples.md` A6.1 for full example.

Top-level **one-of**:
- Variant A: `manual_resolution_items` only (blocking)
- Variant B: spec-keyed object + `run_summary` (no manual items)

**Variant B structure:** Top-level keys are `spec_id` strings; reserved key `run_summary`. Per spec:
- `summary` (string): short description
- `diffs[]`: `{diff_id, diff_path, touched_files[], verification_notes}`
- `mapped_classes_functions[]`: `{kind, qualified_name, file_path}` — `kind` ∈ `function|class`
- `mapped_test_cases[]`: `{framework, test_file, test_case}`

PIKA translates `mapped_classes_functions` and `mapped_test_cases` into design spec column updates after the run.

---

### 2.8 Trace record (append-only ledger)
Fields:
- `run_id`, `batch_id`
- `spec_ids[]`
- `diff_sha256`
- `before_hashes[]` / `after_hashes[]` (list of `{path, sha256}`)
- `verification[]` (list of `{command, exit_code, log_ref}`)
- `artifacts[]` (refs to validated outputs and diff files)

---

### 2.9 Implementation Issue Tracker — auto-emitted row (verification failure)

When batch verification fails, PIKA adds a row to the Implementation Issue Tracker. Draft schema for the emitted row:

| Field | Value |
|-------|-------|
| `issue_id` | Generated per id_generation rules |
| `summary` | e.g. "Batch B1 verification failed: pytest exited 1" |
| `description` | Failing command output + batch_id + spec_ids |
| `severity` | `high` (verification failure) |
| `status` | `open` |
| `author` | `pika-implement` |
| `mapped_spec_ids` | Comma-delimited spec_ids from the failed batch |
| `issue_notes` | "Verification failed; repair mode available." |
| `follow_up_uncertainties` | "No follow_up_uncertainties" |

---

**Example trace record**
```json
{
  "run_id":"RUN123",
  "batch_id":"B1",
  "spec_ids":["SPEC-CORE-001"],
  "diff_sha256":"abc123...",
  "before_hashes":[{"path":"nutrition-core/nutrition/calculator.py","sha256":"..."}],
  "after_hashes":[{"path":"nutrition-core/nutrition/calculator.py","sha256":"..."}],
  "verification":[{"command":"pytest -q","exit_code":0,"log_ref":"verification/B1_pytest.log"}],
  "artifacts":[{"kind":"link_plan","ref":"link_plan.json"},{"kind":"patch","ref":"patches/B1_D1.diff"}]
}
```

---

## 3) Step-by-step implementation guidance (with deliverables + examples)

### Step 1 — Run setup + safety preflight (PIKA)
**What to do**
- Create `run_id`, run workspace directory, `run_meta.json`.
- Ensure outputs/state directories are writable.
- Ensure required input files exist (Formatted SADS; Implementation Issue Tracker may be empty initially).

**Deliverables**
- `run_meta.json`: command, run_id, config snapshot hash, dry_run, budgets snapshot (from config).

**Example `run_meta.json`**
```json
{"command":"implement","run_id":"RUN123","dry_run":false,"budgets":{"max_specs_per_batch":5,"max_files":10,"max_lines_changed":600}}
```

**dry_run:** Performs Steps 1–9 (run workspace creation, workset selection, module catalog, Anchor Planner, Anchor Linker, batch plan). Does **not** invoke the Implementer agent or produce diffs, issues, spec→symbol mapping, or trace records.

---

### Step 2 — Workset selection (PIKA)
**What to do**
- Parse Formatted SADS.
- Select specs to implement (`implementation_status != done`; implementation_status is boolean: done or not done).
- Partition by `module_tag` (required SADS column).

**Deliverables**
- `workset.json`: list of spec_ids + module_tag.

**Example**
```json
{"selected":[{"spec_id":"SPEC-CORE-001","module_tag":"CORE"}]}
```

---

### Step 3 — Module catalog construction (PIKA, deterministic)
**What to do**
- Build `module_catalog.json` mapping module_tag → module_role and root dirs.
- This replaces project-specific layer rules. The Linker prompt uses baked general rules; PIKA validates with the same baked rules.

**Deliverables**
- `module_catalog.json`

**Example**
```json
{"modules":[{"module_tag":"CORE","module_role":"domain","root_dirs":["nutrition-core/"]}]}
```

---

### Step 4 — Anchor Planner per module (Agent)
**What to do**
- For each module, construct a **module-only** planning packet:
  - specs in that module (only minimal fields)
  - naming/convention hints
  - module roots
- Invoke Anchor Planner → validate output schema.
- If output contains `manual_resolution_items`, it must contain **only** those items; block and resolve; re-invoke after resolution. (Current scope: implement up to blocked.)

**Deliverables**
- `anchor_plans/<module_tag>.json` (validated)
- `agent_outputs/anchor_planner_<module_tag>.json` (raw + validated copy)

**Example output excerpt**
```json
{"module_tag":"CORE","provided_intents":[{"intent_local_id":"CORE_PROV_1","kind":"service_interface","capability_name":"ComputeNutrition"}]}
```

---

### Step 5 — Anchor Linker (Agent, global)
**What to do**
- Build linker input from:
  - module_catalog (module_role included)
  - all module anchor plans (trimmed to intents + key anchors)
  - type placement policy: configurable, default `workspace/shared-contracts/`
- Invoke Linker; validate schema.
- **Adopted improvement:** linker output includes `contracts` + `bindings` only (plus integration actions), **no module_dependency_edges**.
- If manual items exist, block and resolve; re-run linker.

**Deliverables**
- `link_plan.json` (validated)
- `agent_outputs/anchor_linker.json` (raw + validated)

**Example**
```json
{"bindings":[{"required_ref":{"module_tag":"API","intent_local_id":"API_REQ_1"},"provided_ref":{"module_tag":"CORE","intent_local_id":"CORE_PROV_1"},"contract_id":"ctr.svc.computeNutrition.v1"}]}
```

---

### Step 6 — Deterministic validation of link plan (PIKA)
**What to do**
Validate the plan **deterministically** before batching:
- Every `required_intent` is bound (or linker produced a blocking manual item).
- General role rules hold (baked policy):
  - frontend can only require `api_endpoint`
  - api can require `service_interface`, etc.
- Type placement rules satisfied (cross-module types in shared area).

**Deliverables**
- `link_plan_validation.json` with pass/fail + reasons

**Example**
```json
{"status":"passed","checks":["all_required_bound","role_rules_ok","type_locations_ok"]}
```

---

### Step 7 — Build spec dependency graph and batch plan (PIKA)
**What to do**
- Derive module dependency edges **from bindings** (do not rely on a separate field).
- Create **Batch 0 Integration** only if linker emitted `integration_actions`; otherwise omit Batch 0.
- Batch 0 brief includes `integration_actions`; the Implementer agent executes them (produces diffs for shared DTOs, adapters, DI wiring, smoke tests).
- Then schedule module batches provider-first:
  - For each binding `consumer → provider`, provider batches must run first.
- Pack specs into batches under budgets (max specs/files/lines/context tokens). Budgets are defined in config and passed into `run_meta`; PIKA enforces them when creating batches and preparing agent inputs.

**Deliverables**
- `batch_plan.json`

**Example**
```json
{"batches":[{"batch_id":"B0","kind":"integration"},{"batch_id":"B1","kind":"module_impl","module_tags":["CORE"],"depends_on_batches":["B0"]}]}
```

---

### Step 8 — Build batch briefs (PIKA)
**What to do**
For each batch:
- Collect only relevant specs, contracts, bindings, planned anchors.
- Add constraints: forbidden paths, budgets, verification commands.
- Write `batch_briefs/<batch_id>.json`.

**Deliverables**
- `batch_briefs/B1.json`

**Example**
```json
{"batch_id":"B1","spec_rows":[{"spec_id":"SPEC-CORE-001"}],"relevant_contracts":[{"contract_id":"ctr.svc.computeNutrition.v1"}]}
```

---

### Step 9 — Execute a batch (Implement executor + PIKA gates)
Both styles keep PIKA as the **only applier**:

**Style A (pure PIKA):** Implementer agent emits diffs to `diff_path`; PIKA applies.  
**Style B (Codex Desktop as helper):** Codex produces a patch file; PIKA still validates + applies + traces.  
Either way, the accepted artifact is a unified diff file.

**What to do (for each batch)**
1) Invoke executor with batch brief (agent or Codex workflow).  
2) Validate executor output schema (spec-keyed diffs or manual-only).  
3) Validate each diff deterministically:
   - touched files under project root
   - not forbidden paths
   - budgets within limits
   - spec_ids non-empty (implicit in spec-keyed structure)
4) Apply diff in **git worktree** (sandbox) and run verification commands.
5) If verification fails:
   - add row to Implementation Issue Tracker (draft schema: §2.9)
   - optionally rerun executor in **repair mode**: different prompt, shared base context, reduced context (only touched snippets + failure logs)
6) If verification passes: accept and apply to main workspace.
7) Write trace record.
8) Translate `mapped_classes_functions` and `mapped_test_cases` into design spec column updates.

**Deliverables**
- `patches/<batch_id>_*.diff`
- `verification/<batch_id>_*.log`
- `trace/trace.jsonl` appended
- optional `issues_emitted.jsonl`

**Example output structure** (see appendix A6.1 for full spec-keyed format)

---

### Step 10 — Finalize summary + status (PIKA)
**What to do**
- Summarize batches completed/failed/skipped.
- Emit `summary.json` with artifact index.
- Return handler result with `status`:
  - `completed`, `blocked`, `skipped`, `failed`.

**Deliverables**
- `summary.json`

**Example**
```json
{"status":"completed","batches_completed":5,"batches_failed":0,"artifact_index":["link_plan.json","batch_plan.json","trace/trace.jsonl"]}
```

---

## 4) Implementation checklist (for the agent implementing `implement`)

1. **Create run workspace** (agent_runs_dir) and write `run_meta.json` (include budgets from config).
2. **Load Formatted SADS** and select workset (implementation_status != done; partition by module_tag).
3. **Create module_catalog** using deterministic mapping (config-backed or heuristic).
4. **Run Anchor Planner** per module:
   - validate schema
   - if manual items → block + resolve (store answer in item); re-invoke after resolution
5. **Run Anchor Linker**:
   - input includes module_role + type placement policy (configurable, default shared-contracts/)
   - output includes contracts + bindings only (no module_dependency_edges)
   - if manual items → block + resolve; re-invoke after resolution
6. **Validate link plan deterministically** (role rules + completeness).
7. **Create batch_plan**:
   - derive edges from bindings
   - include Batch 0 only if integration_actions exist
   - enforce budgets when packing specs
8. For each batch:
   - build batch_brief (for B0: include integration_actions; for module_impl: include spec_rows, contracts, bindings, anchors)
   - invoke Implementer agent → get spec-keyed output (diffs + mapped_classes_functions + mapped_test_cases)
   - validate diffs
   - apply in git worktree + run verification commands
   - if verification fails: emit issue to Implementation Issue Tracker; optionally repair mode
   - if verification passes: accept to main tree (unless dry_run)
   - write trace record
   - translate mapped_classes_functions + mapped_test_cases to design spec updates
9. Emit final `summary.json` + return `status`.

---

## 5) Config keys for implement

Add to project config (or extend config schema) as needed:

- `commands.implement.type_placement_path`: where to place shared DTOs; default `workspace/shared-contracts/`
- `commands.implement.budgets`: `max_specs_per_batch`, `max_files`, `max_lines_changed`, `max_context_tokens` (optional)

These are passed into `run_meta.json` and enforced by PIKA when creating batches and preparing agent inputs.

---

## 6) Notes on robustness and token usage

- Keep planner and linker contexts small: **spec rows + module catalog + intents**, not the full repo.
- Only the execution batch needs code snippets; keep those bounded by budgets.
- Repair loop should send only:
  - failing command output
  - touched file hunks
  - the patch that failed

---

## Appendix A — “Baked” module-role rules (for Linker prompt + PIKA validator)

These are **general rules** (not project-specific matrices):

- `frontend`:
  - may only **require** `api_endpoint`
  - should not require `service_interface` directly
- `api`:
  - may **provide** `api_endpoint`
  - may **require** `service_interface`, `event_topic`
- `domain`:
  - should **provide** `service_interface`
  - should not require `external_api` directly (prefer via `infra`)
- `infra`:
  - may provide `service_interface` that wraps `external_api`, persistence, metrics
- `shared`:
  - types/contracts only; no runtime service requirements
- `cli`:
  - command-line entry point; may require `service_interface` or `api_endpoint` per common usage
- `worker`:
  - background/async processor; may require `service_interface`, `event_topic` per common usage

If a binding violates these, PIKA should reject or emit a manual resolution item.

---

## Appendix B — Minimal examples of deriving edges from bindings

Given:
```json
{"bindings":[
  {"required_ref":{"module_tag":"API","intent_local_id":"API_REQ_1"},
   "provided_ref":{"module_tag":"CORE","intent_local_id":"CORE_PROV_1"},
   "contract_id":"ctr.svc.computeNutrition.v1"}
]}
```

Derived module edge:
- `API → CORE` (consumer is `required_ref.module_tag`, provider is `provided_ref.module_tag`)

Use derived edges only internally for batching; do not store them in link plan schema.
