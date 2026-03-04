# Implement Command Dependency Diagram (no dry-run)

Field-level dependency diagram for `pika agent implement --project-root <path>` **without** `--dry-run`. Each node is a field or value; edges show where each value is sourced from.

## Top-level attributes summary

### Inputs

| File | Top-level attributes |
|------|----------------------|
| **config.yaml** | `version`, `project`, `agent`, `prompts`, `schemas`, `commands`, `id_generation`, `csv_contracts`, `logging` — implement uses `commands.implement.inputs`, `commands.implement.budgets`, `commands.implement.type_placement_path`, `commands.implement.forbidden_paths`, `commands.implement.verification_commands` |
| **design_spec.csv** (DESIGN-SPEC.csv) | `spec_id`, `module_tag`, `module_role`, `subunit`, `title`, `requirement`, `acceptance_criteria`, `implementation_status`, `mapped_code_symbols`, `mapped_confidence`, `mapped_consistency_score`, `mapped_problems`, `index_status`, `assumptions`, `last_indexed_at`, `mapped_test_cases`, `map_status`, `map_assumptions`, `mapped_at` |
| **PROJECT_CONTEXT.md** | Free-form markdown; project context for agents |
| **codebase** | Source tree under `codebase_dir` (e.g. `src/` or `.`) |
| **RuntimeContext** | `run_id`, `dry_run`, `project_root` |

### Intermediate (run-scoped)

| File | Top-level attributes |
|------|----------------------|
| **run_meta.json** | `command`, `run_id`, `dry_run`, `budgets`, `type_placement_path`, `config_hash` |
| **workset.json** | `selected` — array of `{spec_id, module_tag, module_role}` |
| **module_catalog.json** | `modules` — array of `{module_tag, module_role, root_dirs, languages}` |
| **anchor_plans/{M}.json** | `module_tag`, `planned_anchors`, `provided_intents`, `required_intents`, `intra_module_dependencies` (optional) |
| **link_plan.json** | `contracts`, `bindings`, `integration_actions` (optional) — agent output |
| **link_plan_validation.json** | `status`, `checks`, `reasons` |
| **batch_plan.json** | `batches` — array of `{batch_id, kind, spec_ids, module_tags, depends_on_batches, rationale, budgets_applied}` |
| **batch_plan_validation.json** | `status`, `checks`, `reasons` |
| **batch_briefs/B{N}.json** | `batch_id`, `spec_rows`, `relevant_contracts`, `relevant_bindings`, `planned_anchors`, `integration_actions` (B0 only), `constraints` |
| **agent_outputs/implement_{B}.json** | `run_summary`, plus spec-keyed `{spec_id}` objects with `summary`, `diffs`, `mapped_classes_functions`, `mapped_test_cases` |

### Outputs

| File | Top-level attributes |
|------|----------------------|
| **summary.json** | `status`, `dry_run` (optional) |
| **trace/trace.jsonl** | One JSON object per line: `run_id`, `batch_id`, `spec_ids`, `diff_sha256`, `before_hashes`, `after_hashes`, `verification`, `artifacts` |
| **patches/*.diff** | Unified diff content; copied from `implement_{B}.{spec_id}.diffs[].diff_path` |
| **DESIGN-SPEC.csv** | Updated `mapped_code_symbols`, `mapped_test_cases` (and optionally `implementation_status`) |
| **test_spec.csv** | `test_id`, `framework`, `test_file`, `test_case` — deduplicated from implement outputs |
| **codebase** | Modified files via `git apply` of patches |

### Agent artifacts (per-run, transient)

| Path | Description |
|------|-------------|
| **agent_artifacts/implement/{run_id}/local_output.json** | Agent raw output (anchor_planner or anchor_linker); overwritten per invoke |
| **agent_artifacts/implement/{run_id}/*.diff** | Unified diffs written by implement agent; referenced by `diff_path` in implement output |

## Mermaid diagram

```mermaid
flowchart TB
    subgraph INPUTS["Inputs"]
        cfg["config.yaml"]
        ds["design_spec.csv"]
        pc["PROJECT_CONTEXT.md"]
        cb["codebase"]
        ctx["RuntimeContext"]
    end

    subgraph RUN_META["run_meta.json"]
        rm_command["command ← literal implement"]
        rm_run_id["run_id ← ctx.run_id"]
        rm_dry["dry_run ← ctx.dry_run"]
        rm_budgets["budgets ← config.implement.budgets"]
        rm_type_placement["type_placement_path ← config"]
        rm_config_hash["config_hash ← sha256 config"]
    end

    subgraph WORKSET["workset.json"]
        ws_spec["selected[].spec_id ← design_spec.row.spec_id"]
        ws_tag["selected[].module_tag ← design_spec.row.module_tag"]
        ws_role["selected[].module_role ← design_spec.row.module_role"]
    end

    subgraph MOD_CAT["module_catalog.json"]
        mc_tag["modules[].module_tag ← workset group by module_tag"]
        mc_role["modules[].module_role ← workset"]
        mc_dirs["modules[].root_dirs ← f module_tag /"]
        mc_lang["modules[].languages ← []"]
    end

    subgraph AP["anchor_plans/{M}.json"]
        ap_tag["module_tag ← catalog"]
        ap_anchors["planned_anchors ← agent from module packet + project_context"]
        ap_prov["provided_intents ← agent"]
        ap_req["required_intents ← agent"]
    end

    subgraph LP["link_plan.json"]
        lp_ctr["contracts ← agent from catalog + anchor_plans"]
        lp_bind["bindings ← agent"]
        lp_int["integration_actions ← agent"]
    end

    subgraph LV["link_plan_validation.json"]
        lv_status["status ← validate anchor_plans + link_plan + type_placement"]
        lv_checks["checks ← all_required_bound, role_rules_ok, type_locations_ok"]
        lv_reasons["reasons ← validation failures"]
    end

    subgraph BP["batch_plan.json"]
        bp_batches["batches[].batch_id, kind, spec_ids, module_tags"]
        bp_deps["batches[].depends_on_batches ← bindings + provider readiness"]
        bp_rationale["batches[].rationale ← planner"]
        bp_budgets["batches[].budgets_applied ← config.budgets"]
    end

    subgraph BV["batch_plan_validation.json"]
        bv_status["status ← validate batch deps + spec uniqueness"]
        bv_checks["checks ← dependency paths, batch refs"]
        bv_reasons["reasons ← validation failures"]
    end

    subgraph BB["batch_briefs/B{N}.json"]
        bb_id["batch_id ← batch_plan.batches[].batch_id"]
        bb_specs["spec_rows ← workset by spec_ids"]
        bb_ctr["relevant_contracts ← link_plan.contracts filter by bindings"]
        bb_bind["relevant_bindings ← bindings intersect batch spec_ids"]
        bb_anchors["planned_anchors ← anchor_plans filtered by spec_ids"]
        bb_int["integration_actions ← link_plan B0 only"]
        bb_const["constraints ← forbidden_paths + budgets + verify_cmds"]
    end

    subgraph IO["implement_{B}.json"]
        io_summary["run_summary ← agent"]
        io_diffs["{spec_id}.diffs ← agent writes to agent_artifacts"]
        io_mapped["{spec_id}.mapped_classes_functions ← agent"]
        io_tests["{spec_id}.mapped_test_cases ← agent"]
    end

    subgraph PATCHES["patches/*.diff"]
        patch["content ← copy from diffs[].diff_path"]
    end

    subgraph TRACE["trace.jsonl"]
        tr_run["run_id ← ctx.run_id"]
        tr_batch["batch_id ← brief.batch_id"]
        tr_specs["spec_ids ← implement output keys"]
        tr_sha["diff_sha256 ← sha256 patches"]
        tr_before["before_hashes ← codebase pre-apply"]
        tr_after["after_hashes ← codebase post-apply"]
        tr_verify["verification ← verification_commands output"]
        tr_artifacts["artifacts ← patch refs"]
    end

    subgraph SUMMARY["summary.json"]
        sum_status["status ← completed | failed"]
        sum_dry["dry_run ← ctx.dry_run"]
    end

    subgraph OUT["Outputs"]
        dso["DESIGN-SPEC.mapped_code_symbols ← mapped_classes_functions.qualified_name"]
        dso_t["DESIGN-SPEC.mapped_test_cases ← mapped_test_cases to test_id"]
        ts["test_spec.csv ← mapped_test_cases dedup"]
        code["codebase ← git apply patches"]
    end

    ds --> ws_spec
    ds --> ws_tag
    ds --> ws_role
    ctx --> rm_run_id
    ctx --> rm_dry
    cfg --> rm_budgets
    cfg --> rm_type_placement
    cfg --> rm_config_hash

    ws_spec --> mc_tag
    ws_tag --> mc_tag
    ws_role --> mc_role
    mc_tag --> mc_dirs

    mc_tag --> ap_tag
    mc_tag --> ap_anchors
    pc --> ap_anchors
    pc --> ap_prov
    pc --> ap_req

    mc_tag --> lp_ctr
    ap_anchors --> lp_ctr
    ap_prov --> lp_bind
    ap_req --> lp_bind

    ap_anchors --> lv_status
    lp_bind --> lv_status

    ws_tag --> bp_batches
    lp_bind --> bp_deps
    cfg --> bp_budgets
    bp_batches --> bv_status
    bp_deps --> bv_status

    bv_status --> bb_id
    bp_batches --> bb_specs
    lp_ctr --> bb_ctr
    lp_bind --> bb_bind
    ap_anchors --> bb_anchors
    lp_int --> bb_int
    cfg --> bb_const

    bb_specs --> io_diffs
    bb_anchors --> io_diffs
    cb --> io_diffs
    bb_const --> io_diffs

    io_diffs --> patch
    patch --> tr_sha
    cb --> tr_before
    patch --> code
    code --> tr_after
    ctx --> tr_run
    bb_id --> tr_batch
    io_diffs --> tr_specs
    bb_const --> tr_verify

    io_mapped --> dso
    io_tests --> dso_t
    io_tests --> ts
    patch --> code
    ctx --> sum_dry
```

## Field-level dependency table

| Target file | Field | Source |
|-------------|-------|--------|
| **run_meta.json** | command | literal `"implement"` |
| | run_id | `ctx.run_id` |
| | dry_run | `ctx.dry_run` |
| | budgets | `config.commands.implement.budgets` |
| | type_placement_path | `config.commands.implement.type_placement_path` |
| | config_hash | `sha256(json.dumps(config))` |
| **workset.json** | selected[].spec_id | `design_spec.row.spec_id` (where implementation_status ≠ Completed) |
| | selected[].module_tag | `design_spec.row.module_tag` |
| | selected[].module_role | `design_spec.row.module_role` |
| **module_catalog.json** | modules[].module_tag | `workset.group_by(module_tag)` |
| | modules[].module_role | `workset.group_by(module_tag)` |
| | modules[].root_dirs | `["{module_tag}/"]` |
| | modules[].languages | `[]` |
| **anchor_plans/{M}.json** | module_tag | `module_catalog.modules[].module_tag` |
| | planned_anchors | agent (from module packet, project_context, spec_rows) |
| | planned_anchors[].anchor_materialization_kind | agent enum: `schema|interface|runtime_logic|wiring|test` |
| | provided_intents | agent |
| | required_intents | agent |
| **link_plan.json** | contracts | agent (from module_catalog, anchor_plans, type_placement_path) |
| | bindings | agent |
| | integration_actions | agent |
| **link_plan_validation.json** | status | `_validate_link_plan(anchor_plans, module_catalog, link_plan, type_placement_path)` |
| | checks | derived from bindings, contracts, required_intents |
| | reasons | validation failures |
| **batch_plan.json** | batches[].batch_id | derived (B0, B1, …) |
| | batches[].kind | `integration` (B0) or `module_impl` |
| | batches[].spec_ids | deterministic module/SCC chunking from workset |
| | batches[].module_tags | from module/SCC planner |
| | batches[].depends_on_batches | from bindings + provider batch availability + prior batch chain |
| | batches[].rationale | planner-derived (e.g. "integration actions", "provider-first API") |
| | batches[].budgets_applied | `config.commands.implement.budgets` |
| **batch_plan_validation.json** | status | `_validate_batch_plan_dependencies(batch_plan, link_plan)` |
| | checks | dependency IDs exist, spec uniqueness, provider dependency paths |
| | reasons | validation failures |
| **batch_briefs/B{N}.json** | batch_id | `batch_plan.batches[].batch_id` |
| | spec_rows | `workset.by_spec(spec_ids)` (full design_spec rows) |
| | relevant_contracts | `link_plan.contracts` filtered by binding contract_ids |
| | relevant_bindings | binding refs filtered by batch module + intent-linked spec intersection |
| | planned_anchors | `anchor_plans[module].planned_anchors` filtered by `anchor.spec_ids ∩ batch.spec_ids` |
| | integration_actions | `link_plan.integration_actions` (B0 integration batch only) |
| | constraints | `{forbidden_paths, budgets_applied, verification_commands, traceability_rules}` from config |
| **implement_{batch}.json** | run_summary | agent `{status, notes}` |
| | {spec_id}.summary | agent |
| | {spec_id}.diffs[] | agent: `diff_id`, `diff_path`, `touched_files`, `verification_notes` |
| | {spec_id}.mapped_classes_functions | agent |
| | {spec_id}.mapped_test_cases | agent |
| **patches/*.diff** | content | copy from `implement_{batch}.{spec_id}.diffs[].diff_path` |
| **trace/trace.jsonl** | run_id | `ctx.run_id` |
| | batch_id | `brief.batch_id` |
| | spec_ids | `implement_output` keys (sorted) |
| | diff_sha256 | `sha256(patches)` |
| | before_hashes | `sha256(codebase)` pre-apply |
| | after_hashes | `sha256(codebase)` post-apply |
| | verification | `verification_commands` output records |
| | artifacts | `[{kind: "patch", ref: "patches/{name}"}]` |
| **summary.json** | status | `"completed"` or `"failed"` |
| | dry_run | `ctx.dry_run` (optional) |
| **DESIGN-SPEC.csv** | row.mapped_code_symbols | `implement_output[spec_id].mapped_classes_functions[].qualified_name` |
| | row.mapped_test_cases | `implement_output[spec_id].mapped_test_cases` → test_id |
| **test_spec.csv** | test_id | `T{N}` (next from existing or new) |
| | framework, test_file, test_case | `implement_output[spec_id].mapped_test_cases[]` |
| **Code repository** | modified files | `git apply patches/*.diff` |

## Path resolution (defaults)

- `design_spec_path`: `commands.implement.inputs.design_spec_path` or `project.state.design_spec_path` → e.g. `state/DESIGN-SPEC.csv`
- `agent_runs_dir`: `out/agent_runs`
- `agent_artifacts_dir`: `out/agent_artifacts`
- `log_dir`: `logging.log_dir` or `out/logs`
- `test_spec_path`: `commands.implement.test_spec_path` → `out/state/test_spec.csv`
- `backups_dir`: `out/backups`
