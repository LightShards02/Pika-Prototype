# Design: Codebase Transmission for API-Based Agents

## Problem

API-based agents (e.g. Kimi via NVIDIA) receive only:
- `project_context` (PROJECT_CONTEXT.md)
- `codebase_dir` (path string)

**No actual source code is transmitted.** The model cannot access the filesystem, so it cannot perform real spec-to-code mapping. Codex works because it runs with `--cd workspace` and can read files directly.

## Goal

Transmit relevant source code files in the prompt so API-based agents can perform actual mapping.

## Design Overview

### 1. New Module: `core/codebase_transmission.py`

Builds a snapshot of the codebase for inclusion in prompts:

```
build_codebase_snapshot(codebase_dir: Path, config: dict) -> str
```

**Returns:** Formatted string suitable for prompt injection, e.g.:

```
## File: src/main.py
```python
def main():
    ...
```

## File: src/utils.py
```python
def helper():
    ...
```
```

**When empty:** Returns `"(No source files included. Check codebase_transmission config.)"` so the agent knows the snapshot is intentionally absent.

---

### 2. Config Schema

Add to `config.schema.json`:

```json
"codebase_transmission": {
  "type": "object",
  "additionalProperties": false,
  "description": "Controls how source files are included in prompts for API-based agents (e.g. Kimi). Ignored when provider is codex (has filesystem access).",
  "properties": {
    "enabled": {
      "type": "boolean",
      "default": true,
      "description": "Include codebase snapshot when provider is kimi. Default true."
    },
    "max_total_chars": {
      "type": "integer",
      "minimum": 1000,
      "default": 80000,
      "description": "Max total characters across all files. Prevents context overflow."
    },
    "max_files": {
      "type": "integer",
      "minimum": 1,
      "default": 40,
      "description": "Max number of files to include."
    },
    "max_chars_per_file": {
      "type": "integer",
      "minimum": 100,
      "default": 4000,
      "description": "Truncate files longer than this. Append '... (truncated)'."
    },
    "include_extensions": {
      "type": "array",
      "items": { "type": "string" },
      "default": [".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".go", ".rs", ".cpp", ".c", ".h"],
      "description": "Include only files with these extensions."
    },
    "exclude_patterns": {
      "type": "array",
      "items": { "type": "string" },
      "default": ["**/node_modules/**", "**/__pycache__/**", "**/.git/**", "**/venv/**", "**/dist/**", "**/build/**"],
      "description": "Glob patterns to exclude. Applied after include_extensions."
    },
    "include_patterns": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Optional. If set, only include paths matching these globs. Overrides include_extensions."
    },
    "depth_limit": {
      "type": "integer",
      "minimum": 1,
      "default": 10,
      "description": "Max directory depth from codebase root. 1 = root only."
    }
  }
}
```

---

### 3. Algorithm: `build_codebase_snapshot`

1. **Collect candidates**  
   Walk `codebase_dir` (respecting `depth_limit`), collect files matching `include_extensions` or `include_patterns`, excluding `exclude_patterns`.

2. **Sort**  
   Prefer shallow paths first (e.g. `src/main.py` before `src/nested/deep/file.py`). Then by size (smaller first) so more files fit within limits.

3. **Fill**  
   For each file:
   - Read content
   - Truncate to `max_chars_per_file` if needed
   - Stop when `max_files` or `max_total_chars` reached

4. **Format**  
   For each file:
   ```
   ## File: {relative_path}
   ```{language}
   {content}
   ```
   ```
   Language inferred from extension (e.g. `.py` → `python`, `.ts` → `typescript`).

5. **Return**  
   Concatenated string; or empty if no files, then return the fallback message.

---

### 4. Template Variable: `codebase_content`

Add to prompts that need code:

| Prompt | Command | Add `codebase_content`? |
|--------|---------|-------------------------|
| map_spec_to_code | map | Yes |
| implement_from_specs | implement | Yes |
| resolve_issues_with_diffs | resolve_plan | Yes (already has placeholder) |
| map_issues_to_specs | resolve_plan | No (no code needed) |
| project_designer | plan | No |

---

### 5. Prompt Changes

**map_spec_to_code** (prompts/PROMPT.yaml):

```yaml
template_variables:
  # ... existing ...
  - name: codebase_content
    required: false
    description: "Relevant source files from codebase. Empty when provider is codex or codebase_transmission disabled."
```

Add to user section:

```yaml
user: |
  Context:
  {{project_context}}

  Design Specs (CSV):
  {{design_spec_rows_csv}}
  ...

  Codebase Dir:
  {{codebase_dir}}

  Source Files (for mapping):
  {{codebase_content}}
  ...
```

---

### 6. Integration Points

**Handler: map** (`handlers/map.py`)

In `_build_template_vars`:

```python
from core.codebase_transmission import build_codebase_snapshot

# After resolving codebase_dir_path:
codebase_content = ""
if _should_include_codebase(config, ctx):
    codebase_content = build_codebase_snapshot(codebase_dir_path, config)

return {
    # ... existing ...
    "codebase_content": codebase_content,
}
```

**Helper: `_should_include_codebase(config, ctx) -> bool`**

- `False` if `agent.provider == "codex"` (Codex has filesystem access)
- `False` if `codebase_transmission.enabled == false`
- `True` otherwise

**Handlers: implement, resolve_plan**

Same pattern: call `build_codebase_snapshot` when provider is API-based and `codebase_transmission.enabled` is true.

---

### 7. Edge Cases

| Case | Behavior |
|------|----------|
| `codebase_dir` missing | `codebase_content` = fallback message |
| Empty codebase | Fallback message |
| All files excluded | Fallback message |
| Provider is codex | Skip snapshot; `codebase_content` = fallback or empty |
| `codebase_transmission` not in config | Use defaults (enabled, max_total_chars=80000, etc.) |
| Binary file | Skip (only text files) |
| Encoding error | Skip file, log warning |

---

### 8. Implementation Plan

1. **Milestone 1: Core module**
   - Add `core/codebase_transmission.py` with `build_codebase_snapshot`
   - Add `_should_include_codebase` helper
   - Unit tests for collection, truncation, formatting

2. **Milestone 2: Config**
   - Add `codebase_transmission` to config.schema.json
   - Add defaults to config.example.yaml

3. **Milestone 3: Map integration**
   - Add `codebase_content` to map_spec_to_code
   - Update `_build_template_vars` in map handler
   - Test with small codebase

4. **Milestone 4: Implement & resolve_plan**
   - Add `codebase_content` to implement_from_specs
   - Populate `codebase_snapshot` in resolve_plan for resolve_issues_with_diffs

5. **Milestone 5: Documentation**
   - Update config.example.yaml comments
   - Add section to docs/handler_summary.md

---

### 9. Optional: Per-Command Overrides

For finer control, allow per-command overrides:

```yaml
codebase_transmission:
  max_total_chars: 80000
  commands:
    map:
      max_total_chars: 100000
      max_files: 60
    implement:
      max_total_chars: 50000
```

Schema can support this later; initial implementation uses global defaults.

---

### 10. Optional: Relevance-Based Selection

Future enhancement: include only files likely relevant to the specs:

- Extract keywords from `design_spec_rows_csv` (title, requirement)
- Grep for those keywords in codebase
- Prioritize files with matches

Deferred for v1; simpler inclusion rules are sufficient initially.
