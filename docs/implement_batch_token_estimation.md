# Implement Batch Agent Input Token Estimation

This document estimates the **input token count** for each batch implement agent call (`implement_from_specs` prompt).

## Token Conversion

- **Rule of thumb:** ~4 characters per token for English/code (typical for GPT/Claude tokenizers).
- **Conservative:** Use chars ÷ 3 for upper-bound estimates.

---

## Input Components (per batch)

The batch prompt is built in `handlers/implement/execution.py` via `_execute_batch` → `template_vars` → `render_prompt`. The final prompt is `[System]\n{system}\n\n[User]\n{user}`.

### 1. System prompt (fixed)

- **Source:** `prompts/PROMPT.yaml` → `implement_from_specs.system`
- **Content:** ~1,200 chars (instructions, path rules, output schema reference)
- **Estimate:** ~300 tokens

### 2. User prompt template shell (fixed)

- **Source:** `prompts/PROMPT.yaml` → `implement_from_specs.user`
- **Content:** Labels like "Project Context:", "Batch Brief:", "Selected Specs (CSV):", etc. — ~800 chars
- **Estimate:** ~200 tokens

### 3. Variable components (batch-dependent)

| Variable | Source | Typical size | Token estimate |
|----------|--------|--------------|----------------|
| `project_context` | `PROJECT_CONTEXT.md` (workspace) | 8–12 KB | 2,000–3,000 |
| `batch_brief_json` | Per-batch brief | 3–8 KB (8–15 specs) | 750–2,000 |
| `selected_specs_csv` | Same as `batch_brief_json.spec_rows` | 2–6 KB | 500–1,500 |
| `design_spec_column_definitions` | `docs/csv_contracts.md` | ~1.5 KB | ~375 |
| `indexed_mappings_csv` | Same as `selected_specs_csv` | 2–6 KB | 500–1,500 |
| `codebase_dir` | Path string | ~80 chars | ~20 |
| `codebase_content` | **Local:** `""`; **API:** snapshot | 0 or up to 200 KB | 0 or up to 50,000 |
| `runtime_file_facts_json` | Planned paths × ~80 chars each | 0.3–1 KB | 75–250 |
| `allowed_paths_json` | Module roots + forbidden | 0.5–2 KB | 125–500 |
| `forbidden_path_patterns_json` | Array of path prefixes | ~100 chars | ~25 |
| `directory_tree_snapshot` | Tree, max 300 entries | 2–15 KB | 500–3,750 |
| `semantic_retry_context` | Empty on first attempt | 0 or ~500 chars | 0 or ~125 |
| `manual_resolution_file` | Path | ~80 chars | ~20 |
| `run_summary_file` | Path | ~80 chars | ~20 |
| `agent_artifacts_dir` | Path | ~100 chars | ~25 |
| `resolved_decisions` | Manual resolution log | 0 or small | 0–200 |

---

## Per-batch estimates

### Local provider (`agent.provider: local`)

- `codebase_content` = `""` (agent reads filesystem directly).

| Batch size | Specs | Low estimate | High estimate |
|------------|-------|---------------|----------------|
| Small | 3–5 | ~6,000 tokens | ~10,000 tokens |
| Medium | 6–10 | ~10,000 tokens | ~15,000 tokens |
| Large | 11–15 | ~14,000 tokens | ~20,000 tokens |

**Typical (8 specs, nutrition B0/B1):** ~12,000–14,000 input tokens.

### API provider (`agent.provider: api`)

- `codebase_content` = full codebase snapshot (AST + raw files).
- Capped by `codebase_transmission.max_summary_chars` (default 200,000).
- Default `max_raw_files: 10` for implement.

| Batch size | Specs | Low estimate | High estimate |
|------------|-------|---------------|----------------|
| Small | 3–5 | ~55,000 tokens | ~65,000 tokens |
| Medium | 6–10 | ~55,000 tokens | ~70,000 tokens |
| Large | 11–15 | ~55,000 tokens | ~75,000 tokens |

**Typical (8 specs, nutrition):** ~60,000–65,000 input tokens.

The codebase snapshot dominates; batch size has limited impact.

---

## Config knobs that affect size

| Config path | Effect |
|-------------|--------|
| `commands.implement.budgets.max_specs_per_batch` | Caps specs per batch → smaller `batch_brief_json`, `selected_specs_csv` |
| `commands.implement.budgets.max_context_tokens` | Advisory budget (not enforced by PIKA) |
| `codebase_transmission.max_summary_chars` | Caps `codebase_content` (API only) |
| `codebase_transmission.max_raw_files` | How many files get raw source in snapshot (API only) |

---

## Formula (approximate)

```
input_tokens ≈
  ~500                    # system + user shell
  + project_context       # ~2,500
  + batch_brief_json      # ~150 × spec_count
  + selected_specs_csv     # ~100 × spec_count
  + indexed_mappings_csv  # ~100 × spec_count
  + design_spec_defs       # ~375
  + runtime_file_facts     # ~50 × planned_path_count
  + allowed_paths          # ~300
  + directory_tree         # 500–3,750 (depends on codebase)
  + (0 if local else codebase_content)  # 0 or up to 50,000
```

---

## Verification

To measure actual input size for a run:

1. **Local:** Add logging in `core/lifecycle.py` after `render_prompt` to log `len(prompt_text)`.
2. **API:** Use the provider’s usage response (`input_tokens` / `prompt_tokens`) if available.
3. **Offline:** Render the prompt with `render_prompt()` and count chars; divide by 4 for token estimate.
