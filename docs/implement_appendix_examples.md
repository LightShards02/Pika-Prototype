# Appendix B — Example Artifacts (Nutrition Calculator)

This appendix provides **example-only** artifacts for the `implement` command workflow using a “Nutrition Calculator” website scenario.  
It adopts the agreed improvements:

- Modules are classified by deterministic `module_role` (no project-specific layer matrices).
- The global link plan contains **`contracts` + `bindings` only** (no `module_dependency_edges`). Downstream derives edges from `bindings`.

> Notes
> - These examples are intentionally concise but realistic.
> - Fields shown are representative; your real schemas may include additional metadata (timestamps, versions, hashes).

---

## A1) `module_catalog.json` (deterministic `module_role`)

```json
{
  "modules": [
    {"module_tag": "UI",   "module_role": "frontend", "root_dirs": ["ui-web/"],          "languages": ["typescript"]},
    {"module_tag": "API",  "module_role": "api",      "root_dirs": ["api-server/"],      "languages": ["python"]},
    {"module_tag": "CORE", "module_role": "domain",   "root_dirs": ["nutrition-core/"],  "languages": ["python"]},
    {"module_tag": "DATA", "module_role": "infra",    "root_dirs": ["food-data/"],       "languages": ["python"]},
    {"module_tag": "OBS",  "module_role": "infra",    "root_dirs": ["obs/"],             "languages": ["python"]},
    {"module_tag": "SHARED","module_role":"shared",   "root_dirs": ["shared-contracts/"],"languages": ["python"]}
  ]
}
```

---

## A2) Anchor Planner output example (per module)

### A2.1 `anchor_plans/UI.json` (frontend)
```json
{
  "module_tag": "UI",
  "planned_anchors": [
    {
      "anchor_kind": "new_symbol",
      "planned_file_path": "ui-web/components/NutritionForm.tsx",
      "planned_symbol": "NutritionForm",
      "spec_ids": ["SPEC-UI-001"]
    },
    {
      "anchor_kind": "new_symbol",
      "planned_file_path": "ui-web/lib/api.ts",
      "planned_symbol": "postNutritionCalc",
      "spec_ids": ["SPEC-UI-001", "SPEC-UI-002"]
    }
  ],
  "provided_intents": [],
  "required_intents": [
    {
      "intent_local_id": "UI_REQ_1",
      "kind": "api_endpoint",
      "capability_name": "CalcNutrition",
      "description": "Submit user profile and receive calories/day + macros grams.",
      "inputs": [{"name": "profile", "type_name": "NutritionCalcRequest"}],
      "outputs": [{"name": "result", "type_name": "NutritionCalcResponse"}],
      "error_modes": ["ValidationError", "RateLimited"],
      "nonfunctional": {"latency_ms_p95": 500},
      "call_site_plan": {
        "planned_file_path": "ui-web/lib/api.ts",
        "planned_symbol": "postNutritionCalc",
        "invocation_pattern": "fetch('/api/nutrition/calc', {method:'POST', body:JSON.stringify(req)})"
      },
      "spec_ids": ["SPEC-UI-001", "SPEC-UI-002"],
      "confidence": 0.9
    }
  ]
}
```

### A2.2 `anchor_plans/API.json` (api)
```json
{
  "module_tag": "API",
  "planned_anchors": [
    {
      "anchor_kind": "new_symbol",
      "planned_file_path": "api-server/app/routes/nutrition.py",
      "planned_symbol": "post_calc_nutrition",
      "spec_ids": ["SPEC-API-001", "SPEC-SEC-001"]
    },
    {
      "anchor_kind": "new_symbol",
      "planned_file_path": "api-server/app/services/nutrition_service.py",
      "planned_symbol": "NutritionService.calc",
      "spec_ids": ["SPEC-API-001"]
    }
  ],
  "provided_intents": [
    {
      "intent_local_id": "API_PROV_1",
      "kind": "api_endpoint",
      "capability_name": "CalcNutrition",
      "description": "POST /api/nutrition/calc returns calories+macros.",
      "inputs": [{"name": "body", "type_name": "NutritionCalcRequest"}],
      "outputs": [{"name": "body", "type_name": "NutritionCalcResponse"}],
      "error_modes": ["ValidationError", "RateLimited", "ServerError"],
      "nonfunctional": {"rate_limit": "per_ip"},
      "planned_anchor": {
        "file_path": "api-server/app/routes/nutrition.py",
        "symbol_name": "post_calc_nutrition"
      },
      "spec_ids": ["SPEC-API-001", "SPEC-SEC-001"],
      "confidence": 0.9
    }
  ],
  "required_intents": [
    {
      "intent_local_id": "API_REQ_1",
      "kind": "service_interface",
      "capability_name": "ComputeNutrition",
      "description": "Compute calories + macros from domain profile + preset.",
      "inputs": [
        {"name": "profile", "type_name": "NutritionProfile"},
        {"name": "preset", "type_name": "MacroPreset"}
      ],
      "outputs": [{"name": "result", "type_name": "NutritionResult"}],
      "error_modes": ["ValidationError"],
      "call_site_plan": {
        "planned_file_path": "api-server/app/services/nutrition_service.py",
        "planned_symbol": "NutritionService.calc"
      },
      "spec_ids": ["SPEC-API-001"],
      "confidence": 0.8
    }
  ]
}
```

### A2.3 `anchor_plans/CORE.json` (domain)
```json
{
  "module_tag": "CORE",
  "planned_anchors": [
    {
      "anchor_kind": "new_symbol",
      "planned_file_path": "nutrition-core/nutrition/calculator.py",
      "planned_symbol": "compute_nutrition",
      "spec_ids": ["SPEC-CORE-001", "SPEC-CORE-002"]
    },
  ],
  "provided_intents": [
    {
      "intent_local_id": "CORE_PROV_1",
      "kind": "service_interface",
      "capability_name": "ComputeNutrition",
      "description": "Compute BMR/TDEE and macro grams using Mifflin-St Jeor + presets.",
      "inputs": [
        {"name": "profile", "type_name": "NutritionProfile"},
        {"name": "preset", "type_name": "MacroPreset"}
      ],
      "outputs": [{"name": "result", "type_name": "NutritionResult"}],
      "error_modes": ["ValidationError"],
      "nonfunctional": {"deterministic": true, "rounding": "nearest_1g"},
      "planned_anchor": {
        "file_path": "nutrition-core/nutrition/calculator.py",
        "symbol_name": "compute_nutrition"
      },
      "spec_ids": ["SPEC-CORE-001", "SPEC-CORE-002"],
      "confidence": 0.9
    }
  ],
  "required_intents": []
}
```

### A2.4 `anchor_plans/DATA.json` (infra)
```json
{
  "module_tag": "DATA",
  "planned_anchors": [
    {
      "anchor_kind": "new_symbol",
      "planned_file_path": "food-data/foods/provider.py",
      "planned_symbol": "search_foods",
      "spec_ids": ["SPEC-DATA-001"]
    }
  ],
  "provided_intents": [
    {
      "intent_local_id": "DATA_PROV_1",
      "kind": "service_interface",
      "capability_name": "SearchFoods",
      "description": "Search foods by query using external USDA API + cache.",
      "inputs": [{"name": "q", "type_name": "string", "constraints": ["min_len_1"]}],
      "outputs": [{"name": "items", "type_name": "FoodSearchItems"}],
      "error_modes": ["ProviderUnavailable"],
      "nonfunctional": {"cache_ttl_seconds": 86400},
      "planned_anchor": {
        "file_path": "food-data/foods/provider.py",
        "symbol_name": "search_foods"
      },
      "spec_ids": ["SPEC-DATA-001"],
      "confidence": 0.85
    }
  ],
  "required_intents": [
    {
      "intent_local_id": "DATA_REQ_1",
      "kind": "external_api",
      "capability_name": "USDAFoodDataCentralSearch",
      "description": "External HTTP request to USDA FoodData Central search endpoint.",
      "inputs": [{"name": "q", "type_name": "string"}],
      "outputs": [{"name": "raw", "type_name": "UsdaSearchResponseRaw"}],
      "error_modes": ["ProviderUnavailable"],
      "spec_ids": ["SPEC-DATA-001"],
      "confidence": 0.7
    }
  ]
}
```

### A2.5 `anchor_plans/OBS.json` (infra)
```json
{
  "module_tag": "OBS",
  "planned_anchors": [
    {
      "anchor_kind": "new_symbol",
      "planned_file_path": "obs/metrics.py",
      "planned_symbol": "record_request_metric",
      "spec_ids": ["SPEC-OBS-001"]
    }
  ],
  "provided_intents": [
    {
      "intent_local_id": "OBS_PROV_1",
      "kind": "service_interface",
      "capability_name": "RecordRequestMetrics",
      "description": "Record request metrics (latency, endpoint, status).",
      "inputs": [{"name": "event", "type_name": "RequestMetricEvent"}],
      "outputs": [{"name": "ok", "type_name": "bool"}],
      "error_modes": [],
      "planned_anchor": {"file_path": "obs/metrics.py", "symbol_name": "record_request_metric"},
      "spec_ids": ["SPEC-OBS-001"],
      "confidence": 0.75
    }
  ],
  "required_intents": []
}
```

---

## A3) Anchor Linker output example (`link_plan.json`)

### A3.1 Contracts (canonical, versioned) + type locations (shared DTO placement)
```json
{
  "contracts": [
    {
      "contract_id": "ctr.http.calcNutrition.v1",
      "kind": "api_endpoint",
      "canonical_name": "CalcNutrition",
      "shape": {
        "method": "POST",
        "path": "/api/nutrition/calc",
        "request_type": "NutritionCalcRequest",
        "response_type": "NutritionCalcResponse",
        "errors": ["ValidationError", "RateLimited", "ServerError"]
      },
      "type_locations": {
        "NutritionCalcRequest": "shared-contracts/nutrition_http.py",
        "NutritionCalcResponse": "shared-contracts/nutrition_http.py"
      }
    },
    {
      "contract_id": "ctr.svc.computeNutrition.v1",
      "kind": "service_interface",
      "canonical_name": "ComputeNutrition",
      "shape": {
        "function": "compute_nutrition(profile: NutritionProfile, preset: MacroPreset) -> NutritionResult",
        "errors": ["ValidationError"]
      },
      "type_locations": {
        "NutritionProfile": "shared-contracts/nutrition_domain.py",
        "MacroPreset": "shared-contracts/nutrition_domain.py",
        "NutritionResult": "shared-contracts/nutrition_domain.py"
      }
    },
    {
      "contract_id": "ctr.svc.searchFoods.v1",
      "kind": "service_interface",
      "canonical_name": "SearchFoods",
      "shape": {
        "function": "search_foods(q: str) -> FoodSearchItems",
        "errors": ["ProviderUnavailable"]
      },
      "type_locations": {
        "FoodSearchItems": "shared-contracts/food_domain.py"
      }
    },
    {
      "contract_id": "ctr.svc.recordRequestMetrics.v1",
      "kind": "service_interface",
      "canonical_name": "RecordRequestMetrics",
      "shape": {
        "function": "record_request_metric(event: RequestMetricEvent) -> bool"
      },
      "type_locations": {
        "RequestMetricEvent": "shared-contracts/obs.py"
      }
    }
  ],

  "bindings": [
    {
      "required_ref": {"module_tag": "UI", "intent_local_id": "UI_REQ_1"},
      "provided_ref": {"module_tag": "API", "intent_local_id": "API_PROV_1"},
      "contract_id": "ctr.http.calcNutrition.v1",
      "confidence": 0.95,
      "rationale": "UI needs CalcNutrition endpoint; API provides matching endpoint and DTOs."
    },
    {
      "required_ref": {"module_tag": "API", "intent_local_id": "API_REQ_1"},
      "provided_ref": {"module_tag": "CORE", "intent_local_id": "CORE_PROV_1"},
      "contract_id": "ctr.svc.computeNutrition.v1",
      "confidence": 0.9,
      "rationale": "API requires domain ComputeNutrition; CORE provides matching signature."
    },
    {
      "required_ref": {"module_tag": "API", "intent_local_id": "API_REQ_2"},
      "provided_ref": {"module_tag": "DATA", "intent_local_id": "DATA_PROV_1"},
      "contract_id": "ctr.svc.searchFoods.v1",
      "confidence": 0.85,
      "rationale": "API requires SearchFoods; DATA provides SearchFoods with cache."
    },
    {
      "required_ref": {"module_tag": "API", "intent_local_id": "API_REQ_3"},
      "provided_ref": {"module_tag": "OBS", "intent_local_id": "OBS_PROV_1"},
      "contract_id": "ctr.svc.recordRequestMetrics.v1",
      "confidence": 0.8,
      "rationale": "API requires metrics recorder; OBS provides metrics recorder."
    }
  ],

  "integration_actions": [
    {
      "action_id": "INT_1",
      "type": "create_shared_contracts",
      "details": {
        "target_path": "shared-contracts/",
        "files_to_create": [
          "shared-contracts/nutrition_http.py",
          "shared-contracts/nutrition_domain.py",
          "shared-contracts/food_domain.py",
          "shared-contracts/obs.py"
        ],
        "rationale": "Cross-module DTOs must be canonical and shared."
      }
    },
    {
      "action_id": "INT_2",
      "type": "add_adapter",
      "details": {
        "description": "API maps HTTP NutritionCalcRequest -> domain NutritionProfile + MacroPreset.",
        "planned_location": "api-server/app/services/nutrition_service.py"
      }
    }
  ]
}
```

### A3.2 Manual-resolution-only output (blocking)
If ambiguity exists, linker must output **only** these items:

```json
{
  "manual_resolution_items": [
    {
      "item_id": "MR_1",
      "title": "Macro preset default",
      "question": "When UI omits MacroPreset, should API default to BALANCED or require preset?",
      "options": [
        {"option_id": "A", "label": "Default BALANCED", "effect": "API fills missing preset=BALANCED"},
        {"option_id": "B", "label": "Require preset", "effect": "ValidationError if preset missing"}
      ],
      "recommended_option_id": "A",
      "required": true,
      "blocking_reason": "Affects request schema and validation rules"
    }
  ]
}
```

---

## A4) Batch plan example (`batch_plan.json`)

This plan derives ordering from:
- Integration actions (Batch 0)
- Provider-first ordering implied by bindings
- Spec `depends_on` fields (if any)

```json
{
  "batches": [
    {
      "batch_id": "B0",
      "kind": "integration",
      "spec_ids": [],
      "module_tags": ["SHARED"],
      "depends_on_batches": [],
      "rationale": "Create shared DTOs/interfaces referenced by all bound contracts.",
      "budgets_applied": {"max_files": 10, "max_lines_changed": 600}
    },
    {
      "batch_id": "B1",
      "kind": "module_impl",
      "spec_ids": ["SPEC-CORE-001", "SPEC-CORE-002"],
      "module_tags": ["CORE"],
      "depends_on_batches": ["B0"],
      "rationale": "Implement ComputeNutrition provider.",
      "budgets_applied": {"max_files": 8, "max_lines_changed": 500}
    },
    {
      "batch_id": "B2",
      "kind": "module_impl",
      "spec_ids": ["SPEC-DATA-001"],
      "module_tags": ["DATA"],
      "depends_on_batches": ["B0"],
      "rationale": "Implement SearchFoods provider before API consumes.",
      "budgets_applied": {"max_files": 6, "max_lines_changed": 400}
    },
    {
      "batch_id": "B3",
      "kind": "module_impl",
      "spec_ids": ["SPEC-OBS-001"],
      "module_tags": ["OBS"],
      "depends_on_batches": ["B0"],
      "rationale": "Provide RecordRequestMetrics before API integrates middleware.",
      "budgets_applied": {"max_files": 4, "max_lines_changed": 250}
    },
    {
      "batch_id": "B4",
      "kind": "module_impl",
      "spec_ids": ["SPEC-API-001", "SPEC-API-002", "SPEC-SEC-001"],
      "module_tags": ["API"],
      "depends_on_batches": ["B1", "B2", "B3", "B0"],
      "rationale": "Implement API endpoints and wiring to providers.",
      "budgets_applied": {"max_files": 10, "max_lines_changed": 700}
    },
    {
      "batch_id": "B5",
      "kind": "module_impl",
      "spec_ids": ["SPEC-UI-001", "SPEC-UI-002"],
      "module_tags": ["UI"],
      "depends_on_batches": ["B4", "B0"],
      "rationale": "Frontend integrates with API endpoints.",
      "budgets_applied": {"max_files": 10, "max_lines_changed": 700}
    }
  ]
}
```

---

## A5) Batch brief example (`batch_briefs/B1.json`)

This is the concise packet given to the implement executor (agent or Codex workflow).

```json
{
  "batch_id": "B1",
  "spec_rows": [
    {
      "spec_id": "SPEC-CORE-001",
      "title": "BMR/TDEE Calculator",
      "requirement": "Compute BMR with Mifflin-St Jeor; apply activity multiplier.",
      "acceptance_criteria": "Unit tests cover known reference cases."
    },
    {
      "spec_id": "SPEC-CORE-002",
      "title": "Macro Presets",
      "requirement": "Balanced/High-protein/Low-carb presets; grams rounding nearest 1g.",
      "acceptance_criteria": "Preset outputs sum to target calories within rounding tolerance."
    }
  ],
  "relevant_contracts": [
    {
      "contract_id": "ctr.svc.computeNutrition.v1",
      "kind": "service_interface",
      "shape": {
        "function": "compute_nutrition(profile: NutritionProfile, preset: MacroPreset) -> NutritionResult"
      }
    }
  ],
  "relevant_bindings": [
    {
      "required_ref": {"module_tag": "API", "intent_local_id": "API_REQ_1"},
      "provided_ref": {"module_tag": "CORE", "intent_local_id": "CORE_PROV_1"},
      "contract_id": "ctr.svc.computeNutrition.v1"
    }
  ],
  "planned_anchors": [
    {"planned_file_path": "nutrition-core/nutrition/calculator.py", "planned_symbol": "compute_nutrition"},
    {"planned_file_path": "nutrition-core/tests/test_calculator.py", "planned_symbol": "TestComputeNutrition"}
  ],
  "constraints": {
    "forbidden_paths": ["docs/", "specs/"],
    "budgets_applied": {"max_files": 8, "max_lines_changed": 500},
    "verification_commands": ["pytest -q"],
    "traceability_rules": {"require_spec_ids_per_diff": true}
  }
}
```

---

## A6) Implementer output example (diff-only)

The implement executor must output **either** blocking manual resolution **or** diffs.

### A6.1 Diffs output
```json
{
  "SPEC-CORE-001": {
    "summary": "Implement Mifflin–St Jeor BMR/TDEE calculation and input validation.",
    "diffs": [
      {
        "diff_id": "D_B1_CORE_001_01",
        "diff_path": "agent_artifacts/patches/B1_D_B1_CORE_001_01.diff",
        "touched_files": [
          "nutrition-core/nutrition/calculator.py",
          "nutrition-core/nutrition/models.py",
          "nutrition-core/tests/test_calculator.py"
        ],
        "verification_notes": "Run pytest -q under nutrition-core/"
      }
    ],
    "mapped_classes_functions": [
      {
        "kind": "function",
        "qualified_name": "nutrition.calculator.compute_bmr_mifflin_st_jeor",
        "file_path": "nutrition-core/nutrition/calculator.py"
      },
      {
        "kind": "function",
        "qualified_name": "nutrition.calculator.compute_tdee",
        "file_path": "nutrition-core/nutrition/calculator.py"
      },
      {
        "kind": "class",
        "qualified_name": "nutrition.models.NutritionProfile",
        "file_path": "nutrition-core/nutrition/models.py"
      }
    ],
    "mapped_test_cases": [
      {
        "framework": "pytest",
        "test_file": "nutrition-core/tests/test_calculator.py",
        "test_case": "test_bmr_reference_case_male"
      },
      {
        "framework": "pytest",
        "test_file": "nutrition-core/tests/test_calculator.py",
        "test_case": "test_tdee_activity_multiplier_moderate"
      },
      {
        "framework": "pytest",
        "test_file": "nutrition-core/tests/test_calculator.py",
        "test_case": "test_validation_rejects_negative_weight"
      }
    ]
  },

  "SPEC-CORE-002": {
    "summary": "Implement macro preset rules and rounding behavior.",
    "diffs": [
      {
        "diff_id": "D_B1_CORE_002_01",
        "diff_path": "agent_artifacts/patches/B1_D_B1_CORE_002_01.diff",
        "touched_files": [
          "nutrition-core/nutrition/calculator.py",
          "nutrition-core/nutrition/models.py",
          "nutrition-core/tests/test_calculator.py"
        ],
        "verification_notes": "Run pytest -q under nutrition-core/"
      }
    ],
    "mapped_classes_functions": [
      {
        "kind": "enum",
        "qualified_name": "nutrition.models.MacroPreset",
        "file_path": "nutrition-core/nutrition/models.py"
      },
      {
        "kind": "function",
        "qualified_name": "nutrition.calculator.allocate_macros",
        "file_path": "nutrition-core/nutrition/calculator.py"
      }
    ],
    "mapped_test_cases": [
      {
        "framework": "pytest",
        "test_file": "nutrition-core/tests/test_calculator.py",
        "test_case": "test_macro_preset_balanced_sums_to_calories_within_tolerance"
      },
      {
        "framework": "pytest",
        "test_file": "nutrition-core/tests/test_calculator.py",
        "test_case": "test_macro_rounding_nearest_1g"
      }
    ]
  },

  "run_summary": {
    "status": "success",
    "notes": "Generated per-spec diffs with explicit symbol + test mappings."
  }
}
```

---

## A7) Trace ledger record example (`trace/trace.jsonl`)

```json
{
  "run_id": "RUN123",
  "batch_id": "B1",
  "spec_ids": ["SPEC-CORE-001", "SPEC-CORE-002"],
  "diff_sha256": "e2d1c9a0...",
  "before_hashes": [
    {"path": "nutrition-core/nutrition/calculator.py", "sha256": "000...000"}
  ],
  "after_hashes": [
    {"path": "nutrition-core/nutrition/calculator.py", "sha256": "aaa...111"}
  ],
  "verification": [
    {"command": "pytest -q", "exit_code": 0, "log_ref": "verification/B1_pytest.log"}
  ],
  "artifacts": [
    {"kind": "module_catalog", "ref": "module_catalog.json"},
    {"kind": "link_plan", "ref": "link_plan.json"},
    {"kind": "batch_brief", "ref": "batch_briefs/B1.json"},
    {"kind": "patch", "ref": "patches/B1_D_B1_01.diff"}
  ]
}
```

---

## A8) Deriving module edges from `bindings` (no `module_dependency_edges`)

Given bindings:
```json
[
  {
    "required_ref": {"module_tag": "API", "intent_local_id": "API_REQ_1"},
    "provided_ref": {"module_tag": "CORE", "intent_local_id": "CORE_PROV_1"},
    "contract_id": "ctr.svc.computeNutrition.v1"
  }
]
```

Derived module edge (consumer → provider):
- `API → CORE`

Rule:
- `consumer_module = required_ref.module_tag`
- `provider_module = provided_ref.module_tag`

You can compute:
- a unique set of module edges for visualization, and/or
- a topological ordering constraint for batching.

