"""Tests for handlers.implement (unified planner pipeline)."""

from __future__ import annotations

import io
import json
import subprocess
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from core.context import RuntimeContext
from core.pika_config import reset_pika_config_cache
from handlers.implement import (
    _escalate_spec_issues,
    _report_implement_phase,
    _build_batches,
    _build_briefs,
    _build_module_catalog,
    _get_impl_cfg,
    _resolve_min_confidence_threshold,
    _select_workset,
    _validate_batch_plan_dependencies,
    _validate_brief_scoping,
    _validate_contract_field_consistency,
    _validate_dependency_context_edges,
    _validate_required_field_coverage,
    _validate_unified_plan,
    run_implement,
)


class ReportImplementPhaseTests(unittest.TestCase):
    """Tests for per-phase progress output."""

    def test_report_implement_phase_writes_to_stderr(self) -> None:
        """_report_implement_phase emits [PIKA] phase: status — detail to stderr."""
        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            _report_implement_phase("Load", "ok", "24 specs from design spec")
        self.assertIn("[PIKA] Load: ok — 24 specs from design spec", buf.getvalue())


class ImplementSelectionTests(unittest.TestCase):
    """Tests for deterministic workset and module-catalog selection."""

    def test_select_workset_filters_completed(self) -> None:
        headers = ["spec_id", "module_tag", "module_role", "implementation_status"]
        rows = [
            {"spec_id": "A1", "module_tag": "API", "module_role": "api", "implementation_status": "Completed"},
            {"spec_id": "A2", "module_tag": "CORE", "module_role": "domain", "implementation_status": ""},
        ]
        selected = _select_workset(headers, rows)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["spec_id"], "A2")

    def test_build_module_catalog_rejects_inconsistent_role(self) -> None:
        rows = [
            {"spec_id": "A1", "module_tag": "CORE", "module_role": "domain"},
            {"spec_id": "A2", "module_tag": "CORE", "module_role": "infra"},
        ]
        with self.assertRaises(ValueError):
            _build_module_catalog(rows, {"domain", "infra"})


class UnifiedPlanValidationTests(unittest.TestCase):
    """Tests for unified plan DAG and coverage validation."""

    def test_validate_unified_plan_passes_for_valid_plan(self) -> None:
        plan = {
            "module_plans": [
                {
                    "module_tag": "API",
                    "planned_anchors": [
                        {"spec_ids": ["A1001"], "planned_file_path": "api/routes.py",
                         "anchor_kind": "new_symbol", "anchor_materialization_kind": "runtime_logic"},
                    ],
                },
                {
                    "module_tag": "CORE",
                    "planned_anchors": [
                        {"spec_ids": ["A2001"], "planned_file_path": "core/calc.py",
                         "anchor_kind": "new_symbol", "anchor_materialization_kind": "runtime_logic"},
                    ],
                },
            ],
            "spec_dependencies": [
                {"consumer_spec_id": "A1001", "provider_spec_ids": ["A2001"]},
            ],
            "shared_contracts": [],
        }
        all_spec_ids = {"A1001", "A2001"}
        module_catalog = {"modules": [
            {"module_tag": "API", "module_role": "api"},
            {"module_tag": "CORE", "module_role": "domain"},
        ]}
        result = _validate_unified_plan(plan, all_spec_ids, module_catalog)
        self.assertEqual(result["status"], "passed")
        self.assertIn("all_specs_covered", result["checks"])
        self.assertIn("spec_dependencies_acyclic", result["checks"])
        self.assertIn("spec_dependency_refs_valid", result["checks"])
        self.assertIn("all_modules_planned", result["checks"])
        self.assertEqual(result["retryable_reasons"], [])
        self.assertEqual(result["blocking_reasons"], [])
        self.assertIsNone(result["cycle_path"])

    def test_validate_unified_plan_detects_uncovered_specs(self) -> None:
        plan = {
            "module_plans": [
                {
                    "module_tag": "API",
                    "planned_anchors": [
                        {"spec_ids": ["A1001"], "planned_file_path": "api/routes.py",
                         "anchor_kind": "new_symbol", "anchor_materialization_kind": "runtime_logic"},
                    ],
                },
            ],
            "spec_dependencies": [],
            "shared_contracts": [],
        }
        all_spec_ids = {"A1001", "A2001"}
        module_catalog = {"modules": [{"module_tag": "API", "module_role": "api"}]}
        result = _validate_unified_plan(plan, all_spec_ids, module_catalog)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("A2001" in r for r in result["reasons"]))
        self.assertTrue(any("A2001" in r for r in result["retryable_reasons"]))
        self.assertEqual(result["blocking_reasons"], [])

    def test_validate_unified_plan_detects_cycle(self) -> None:
        plan = {
            "module_plans": [
                {
                    "module_tag": "API",
                    "planned_anchors": [
                        {"spec_ids": ["A1001"], "planned_file_path": "api/routes.py",
                         "anchor_kind": "new_symbol", "anchor_materialization_kind": "runtime_logic"},
                    ],
                },
                {
                    "module_tag": "CORE",
                    "planned_anchors": [
                        {"spec_ids": ["A2001"], "planned_file_path": "core/calc.py",
                         "anchor_kind": "new_symbol", "anchor_materialization_kind": "runtime_logic"},
                    ],
                },
            ],
            "spec_dependencies": [
                {"consumer_spec_id": "A1001", "provider_spec_ids": ["A2001"]},
                {"consumer_spec_id": "A2001", "provider_spec_ids": ["A1001"]},
            ],
            "shared_contracts": [],
        }
        all_spec_ids = {"A1001", "A2001"}
        module_catalog = {"modules": [
            {"module_tag": "API", "module_role": "api"},
            {"module_tag": "CORE", "module_role": "domain"},
        ]}
        result = _validate_unified_plan(plan, all_spec_ids, module_catalog)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("cycle" in r.lower() for r in result["reasons"]))
        self.assertTrue(len(result["blocking_reasons"]) > 0)
        self.assertIsNotNone(result["cycle_path"])
        self.assertEqual(result["retryable_reasons"], [])

    def test_validate_unified_plan_detects_unknown_spec_refs(self) -> None:
        plan = {
            "module_plans": [
                {
                    "module_tag": "API",
                    "planned_anchors": [
                        {"spec_ids": ["A1001"], "planned_file_path": "api/routes.py",
                         "anchor_kind": "new_symbol", "anchor_materialization_kind": "runtime_logic"},
                    ],
                },
            ],
            "spec_dependencies": [
                {"consumer_spec_id": "A1001", "provider_spec_ids": ["A9999"]},
            ],
            "shared_contracts": [],
        }
        all_spec_ids = {"A1001"}
        module_catalog = {"modules": [{"module_tag": "API", "module_role": "api"}]}
        result = _validate_unified_plan(plan, all_spec_ids, module_catalog)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("A9999" in r for r in result["reasons"]))
        self.assertTrue(any("A9999" in r for r in result["retryable_reasons"]))
        self.assertEqual(result["blocking_reasons"], [])

    def test_validate_unified_plan_detects_missing_module(self) -> None:
        plan = {
            "module_plans": [
                {
                    "module_tag": "API",
                    "planned_anchors": [
                        {"spec_ids": ["A1001"], "planned_file_path": "api/routes.py",
                         "anchor_kind": "new_symbol", "anchor_materialization_kind": "runtime_logic"},
                    ],
                },
            ],
            "spec_dependencies": [],
            "shared_contracts": [],
        }
        all_spec_ids = {"A1001"}
        module_catalog = {"modules": [
            {"module_tag": "API", "module_role": "api"},
            {"module_tag": "CORE", "module_role": "domain"},
        ]}
        result = _validate_unified_plan(plan, all_spec_ids, module_catalog)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("CORE" in r for r in result["reasons"]))
        self.assertTrue(any("CORE" in r for r in result["retryable_reasons"]))
        self.assertEqual(result["blocking_reasons"], [])


class ImplementConfigTests(unittest.TestCase):
    """Tests for implement config parsing."""

    def test_get_impl_cfg_defaults_disallowed_policy(self) -> None:
        cfg = {"commands": {"implement": {"enabled": True}}}
        impl = _get_impl_cfg(cfg)
        self.assertIn("frontend", impl["disallowed_link_kinds_by_required_role"])
        self.assertIn("external_api", impl["disallowed_link_kinds_by_required_role"]["frontend"])
        self.assertEqual(impl["leaf_dependency_roles"], set())
        self.assertEqual(impl["leaf_dependency_policy"]["mode"], "auto_drop")
        self.assertTrue(impl["leaf_dependency_policy"]["track_external_dependencies"])
        self.assertEqual(impl["unified_planner_prompt_name"], "implement_unified_planner")
        self.assertEqual(impl["field_match_score_threshold"], 0.8)
        self.assertTrue(impl["steps"]["workset_schema_validation"]["enabled"])
        self.assertTrue(impl["steps"]["contract_field_consistency_validation"]["enabled"])
        self.assertEqual(
            impl["steps"]["contract_field_consistency_validation"]["field_match_score_threshold"],
            0.8,
        )

    def test_get_impl_cfg_parses_field_match_score_threshold(self) -> None:
        cfg = {
            "commands": {
                "implement": {
                    "enabled": True,
                    "contract_field_consistency_validation": {
                        "field_match_score_threshold": 0.75,
                    },
                }
            }
        }
        impl = _get_impl_cfg(cfg)
        self.assertEqual(impl["field_match_score_threshold"], 0.75)

    def test_get_impl_cfg_parses_step_scoped_settings(self) -> None:
        cfg = {
            "commands": {
                "implement": {
                    "enabled": True,
                    "contract_field_consistency_validation": {
                        "enabled": False,
                        "field_match_score_threshold": 0.66,
                    },
                    "planner_semantic_validation": {
                        "enabled": False,
                        "semantic_validation_retries": 3,
                    },
                    "implement_semantic_validation": {
                        "semantic_validation_retries": 4,
                    },
                }
            }
        }
        impl = _get_impl_cfg(cfg)
        self.assertFalse(impl["steps"]["contract_field_consistency_validation"]["enabled"])
        self.assertEqual(
            impl["steps"]["contract_field_consistency_validation"]["field_match_score_threshold"],
            0.66,
        )
        self.assertFalse(impl["steps"]["planner_semantic_validation"]["enabled"])
        self.assertEqual(
            impl["steps"]["planner_semantic_validation"]["semantic_validation_retries"],
            3,
        )
        self.assertEqual(
            impl["steps"]["implement_semantic_validation"]["semantic_validation_retries"],
            4,
        )

    def test_get_impl_cfg_parses_agent_scoped_fields(self) -> None:
        cfg = {
            "commands": {
                "implement": {
                    "enabled": True,
                    "unified_planner": {
                        "disallowed_link_kinds_by_required_role": {
                            "frontend": ["external_api"],
                        },
                        "leaf_dependency_roles": ["infra"],
                        "leaf_dependency_policy": {
                            "mode": "auto_drop",
                            "track_external_dependencies": False,
                        },
                        "contract_kind_definitions": {
                            "external_api": {
                                "definition": "External system boundary only.",
                            }
                        },
                        "type_shape_match": {
                            "min_auto_bind_score": 0.61,
                            "tie_margin": 0.05,
                        },
                        "min_confidence_threshold": 0.55,
                    },
                }
            }
        }
        impl = _get_impl_cfg(cfg)
        self.assertEqual(impl["prompt_name"], "implement_from_specs")
        self.assertEqual(impl["unified_planner_prompt_name"], "implement_unified_planner")
        self.assertEqual(impl["leaf_dependency_roles"], {"infra"})
        self.assertFalse(impl["leaf_dependency_policy"]["track_external_dependencies"])
        self.assertEqual(impl["type_shape_match"]["min_auto_bind_score"], 0.61)
        self.assertEqual(impl["type_shape_match"]["tie_margin"], 0.05)
        self.assertEqual(impl["min_confidence_threshold"], 0.55)

    def test_get_impl_cfg_defaults_to_local_prompt_for_local_provider(self) -> None:
        """prompt_name defaults to implement_from_specs_local when provider is local."""
        cfg = {"agent": {"provider": "local"}, "commands": {"implement": {"enabled": True}}}
        impl = _get_impl_cfg(cfg)
        self.assertEqual(impl["prompt_name"], "implement_from_specs_local")

    def test_resolve_min_confidence_threshold_project_overrides_pika(self) -> None:
        reset_pika_config_cache()
        impl = {"min_confidence_threshold": 0.9}
        self.assertEqual(_resolve_min_confidence_threshold(impl), 0.9)

    def test_resolve_min_confidence_threshold_falls_back_to_pika(self) -> None:
        reset_pika_config_cache()
        impl = {}
        self.assertEqual(_resolve_min_confidence_threshold(impl), 0.7)

    def test_get_impl_cfg_rejects_max_files_below_min(self) -> None:
        """budgets.max_files below pika.yaml implement.min_max_files raises ValueError."""
        reset_pika_config_cache()
        cfg = {
            "commands": {
                "implement": {
                    "enabled": True,
                    "prompt_name": "implement_from_specs",
                    "budgets": {"max_files": 1},
                }
            }
        }
        with self.assertRaises(ValueError) as ctx:
            _get_impl_cfg(cfg)
        self.assertIn("min_max_files", str(ctx.exception))


class ImplementBatchPlanTests(unittest.TestCase):
    """Tests for deterministic graph-aware batch planning from spec dependencies."""

    def test_build_batches_orders_providers_before_consumers(self) -> None:
        rows = [
            {"spec_id": "A1001", "module_tag": "API", "module_role": "api"},
            {"spec_id": "A2001", "module_tag": "CORE", "module_role": "domain"},
            {"spec_id": "A3001", "module_tag": "DATA", "module_role": "infra"},
        ]
        spec_dependencies = [
            {"consumer_spec_id": "A1001", "provider_spec_ids": ["A2001", "A3001"]},
        ]
        batch_plan = _build_batches(rows, spec_dependencies, {"max_specs_per_batch": 5})
        batches = batch_plan["batches"]
        by_module = {b["module_tags"][0]: b for b in batches if len(b["module_tags"]) == 1}
        api_deps = set(by_module["API"]["depends_on_batches"])
        self.assertIn(by_module["CORE"]["batch_id"], api_deps)
        self.assertIn(by_module["DATA"]["batch_id"], api_deps)

    def test_build_batches_handles_cyclic_modules(self) -> None:
        rows = [
            {"spec_id": "A1001", "module_tag": "API", "module_role": "api"},
            {"spec_id": "A2001", "module_tag": "CORE", "module_role": "domain"},
        ]
        spec_dependencies = [
            {"consumer_spec_id": "A1001", "provider_spec_ids": ["A2001"]},
            {"consumer_spec_id": "A2001", "provider_spec_ids": ["A1001"]},
        ]
        batch_plan = _build_batches(rows, spec_dependencies, {"max_specs_per_batch": 5})
        cohort = [
            b for b in batch_plan["batches"]
            if sorted(b.get("module_tags", [])) == ["API", "CORE"]
        ]
        self.assertGreaterEqual(len(cohort), 1)

    def test_build_batches_precise_spec_deps(self) -> None:
        """API spec depends on CORE/DATA but not OBS/SHARED."""
        rows = [
            {"spec_id": "A1001", "module_tag": "API", "module_role": "api"},
            {"spec_id": "A2001", "module_tag": "CORE", "module_role": "domain"},
            {"spec_id": "A3001", "module_tag": "DATA", "module_role": "infra"},
            {"spec_id": "A4001", "module_tag": "OBS", "module_role": "infra"},
            {"spec_id": "A5001", "module_tag": "SHARED", "module_role": "shared"},
        ]
        spec_dependencies = [
            {"consumer_spec_id": "A1001", "provider_spec_ids": ["A2001", "A3001"]},
        ]
        batch_plan = _build_batches(rows, spec_dependencies, {"max_specs_per_batch": 5})
        api_batch = next(b for b in batch_plan["batches"] if b.get("module_tags") == ["API"])
        deps = set(api_batch["depends_on_batches"])
        core_batch = next(b["batch_id"] for b in batch_plan["batches"] if b.get("module_tags") == ["CORE"])
        data_batch = next(b["batch_id"] for b in batch_plan["batches"] if b.get("module_tags") == ["DATA"])
        obs_batch = next(b["batch_id"] for b in batch_plan["batches"] if b.get("module_tags") == ["OBS"])
        shared_batch = next(b["batch_id"] for b in batch_plan["batches"] if b.get("module_tags") == ["SHARED"])
        self.assertIn(core_batch, deps)
        self.assertIn(data_batch, deps)
        self.assertNotIn(obs_batch, deps, "API only depends on CORE/DATA, not OBS")
        self.assertNotIn(shared_batch, deps, "API only depends on CORE/DATA, not SHARED")

    def test_build_batches_does_not_chain_module_chunks_without_reason(self) -> None:
        """Chunked module batches do not auto-chain unless dependency/safety reason exists."""
        rows = [
            {"spec_id": "A1001", "module_tag": "API", "module_role": "api"},
            {"spec_id": "A1002", "module_tag": "API", "module_role": "api"},
        ]
        batch_plan = _build_batches(rows, [], {"max_specs_per_batch": 1})
        api_batches = sorted(
            [b for b in batch_plan["batches"] if b.get("module_tags") == ["API"]],
            key=lambda b: b["batch_id"],
        )
        self.assertEqual(len(api_batches), 2)
        self.assertEqual(api_batches[1]["depends_on_batches"], [])

    def test_build_batches_adds_intra_module_dependency_across_chunks(self) -> None:
        """Intra-module spec dependency creates a cross-chunk batch dependency."""
        rows = [
            {"spec_id": "A1001", "module_tag": "API", "module_role": "api"},
            {"spec_id": "A1002", "module_tag": "API", "module_role": "api"},
        ]
        module_plans = [
            {
                "module_tag": "API",
                "planned_anchors": [],
                "intra_module_dependencies": [
                    {"spec_id": "A1002", "depends_on": ["A1001"], "reason": "order"},
                ],
            }
        ]
        batch_plan = _build_batches(
            rows,
            [],
            {"max_specs_per_batch": 1},
            module_plans=module_plans,
        )
        api_batches = sorted(
            [b for b in batch_plan["batches"] if b.get("module_tags") == ["API"]],
            key=lambda b: b["batch_id"],
        )
        self.assertEqual(len(api_batches), 2)
        self.assertIn(api_batches[0]["batch_id"], set(api_batches[1]["depends_on_batches"]))

    def test_build_batches_adds_sequential_fallback_on_file_overlap(self) -> None:
        """Chunked module batches chain when planned files overlap across chunks."""
        rows = [
            {"spec_id": "A1001", "module_tag": "API", "module_role": "api"},
            {"spec_id": "A1002", "module_tag": "API", "module_role": "api"},
        ]
        anchor_plans = {
            "API": {
                "module_tag": "API",
                "planned_anchors": [
                    {
                        "anchor_kind": "boundary_file",
                        "anchor_materialization_kind": "runtime_logic",
                        "planned_file_path": "API/routes/shared.py",
                        "spec_ids": ["A1001", "A1002"],
                    }
                ],
            }
        }
        batch_plan = _build_batches(
            rows,
            [],
            {"max_specs_per_batch": 1, "max_files": 10},
            anchor_plans=anchor_plans,
        )
        api_batches = sorted(
            [b for b in batch_plan["batches"] if b.get("module_tags") == ["API"]],
            key=lambda b: b["batch_id"],
        )
        self.assertEqual(len(api_batches), 2)
        self.assertIn(api_batches[0]["batch_id"], set(api_batches[1]["depends_on_batches"]))

    def test_build_batches_orders_forward_provider_refs_across_module_chunks(self) -> None:
        """Forward provider refs are wired even when lexical spec order would split them."""
        rows = [
            {"spec_id": "A1001", "module_tag": "API", "module_role": "api"},
            {"spec_id": "A1002", "module_tag": "API", "module_role": "api"},
            {"spec_id": "A1003", "module_tag": "API", "module_role": "api"},
        ]
        spec_dependencies = [
            {"consumer_spec_id": "A1001", "provider_spec_ids": ["A1003"]},
        ]
        batch_plan = _build_batches(rows, spec_dependencies, {"max_specs_per_batch": 2})
        result = _validate_batch_plan_dependencies(batch_plan, spec_dependencies)
        self.assertEqual(result["status"], "passed")
        self.assertIn("provider_dependency_paths_ok", result["checks"])

    def test_build_batches_cyclic_cohort_chunks_keep_provider_paths(self) -> None:
        """Cyclic module cohorts must still produce valid provider dependency paths."""
        rows = [
            {"spec_id": "A1010", "module_tag": "API", "module_role": "api"},
            {"spec_id": "A1015", "module_tag": "API", "module_role": "api"},
            {"spec_id": "A1018", "module_tag": "API", "module_role": "api"},
            {"spec_id": "A1019", "module_tag": "API", "module_role": "api"},
            {"spec_id": "A1029", "module_tag": "DATA", "module_role": "infra"},
            {"spec_id": "A1033", "module_tag": "OBS", "module_role": "infra"},
            {"spec_id": "A1051", "module_tag": "DATA", "module_role": "infra"},
        ]
        spec_dependencies = [
            {"consumer_spec_id": "A1010", "provider_spec_ids": ["A1029", "A1033"]},
            {"consumer_spec_id": "A1018", "provider_spec_ids": ["A1033"]},
            {"consumer_spec_id": "A1033", "provider_spec_ids": ["A1019"]},
            {"consumer_spec_id": "A1051", "provider_spec_ids": ["A1015"]},
        ]
        batch_plan = _build_batches(rows, spec_dependencies, {"max_specs_per_batch": 3})
        result = _validate_batch_plan_dependencies(batch_plan, spec_dependencies)
        self.assertEqual(result["status"], "passed")
        self.assertIn("provider_dependency_paths_ok", result["checks"])

    def test_validate_batch_plan_dependencies_detects_missing_provider_path(self) -> None:
        batch_plan = {
            "batches": [
                {
                    "batch_id": "B0",
                    "kind": "module_impl",
                    "module_tags": ["API"],
                    "spec_ids": ["A1001"],
                    "depends_on_batches": [],
                },
                {
                    "batch_id": "B1",
                    "kind": "module_impl",
                    "module_tags": ["CORE"],
                    "spec_ids": ["A2001"],
                    "depends_on_batches": [],
                },
            ]
        }
        spec_dependencies = [
            {"consumer_spec_id": "A1001", "provider_spec_ids": ["A2001"]},
        ]
        result = _validate_batch_plan_dependencies(batch_plan, spec_dependencies)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("Missing provider dependency paths" in r for r in result["reasons"]))

    def test_validate_batch_plan_dependencies_passes_when_wired(self) -> None:
        batch_plan = {
            "batches": [
                {
                    "batch_id": "B0",
                    "kind": "module_impl",
                    "module_tags": ["CORE"],
                    "spec_ids": ["A2001"],
                    "depends_on_batches": [],
                },
                {
                    "batch_id": "B1",
                    "kind": "module_impl",
                    "module_tags": ["API"],
                    "spec_ids": ["A1001"],
                    "depends_on_batches": ["B0"],
                },
            ]
        }
        spec_dependencies = [
            {"consumer_spec_id": "A1001", "provider_spec_ids": ["A2001"]},
        ]
        result = _validate_batch_plan_dependencies(batch_plan, spec_dependencies)
        self.assertEqual(result["status"], "passed")
        self.assertIn("provider_dependency_paths_ok", result["checks"])

    def test_chunk_specs_respects_max_files(self) -> None:
        from handlers.implement.batching import _chunk_specs

        spec_ids = ["A1", "A2", "A3", "A4"]
        spec_to_files = {"A1": {"f1", "f2"}, "A2": {"f3"}, "A3": {"f4", "f5"}, "A4": {"f6"}}
        chunks = _chunk_specs(spec_ids, chunk_size=10, max_files=3, spec_to_files=spec_to_files)
        self.assertGreater(len(chunks), 1, "Should split when files exceed max_files=3")
        for chunk in chunks:
            files = set()
            for sid in chunk:
                files |= spec_to_files.get(sid, set())
            self.assertLessEqual(len(files), 3, f"Chunk {chunk} has {len(files)} files, max 3")


class ImplementBriefTests(unittest.TestCase):
    """Tests for batch brief construction from unified planner output."""

    def test_build_briefs_scopes_anchors_and_contracts_to_batch(self) -> None:
        rows = [
            {"spec_id": "A1001", "module_tag": "API", "module_role": "api"},
            {"spec_id": "A1002", "module_tag": "API", "module_role": "api"},
            {"spec_id": "A2001", "module_tag": "CORE", "module_role": "domain"},
        ]
        module_plans = {
            "API": {
                "module_tag": "API",
                "planned_anchors": [
                    {
                        "anchor_kind": "new_symbol",
                        "anchor_materialization_kind": "runtime_logic",
                        "planned_file_path": "API/app/routes.py",
                        "spec_ids": ["A1001"],
                    },
                    {
                        "anchor_kind": "new_symbol",
                        "anchor_materialization_kind": "runtime_logic",
                        "planned_file_path": "API/app/auth.py",
                        "spec_ids": ["A1002"],
                    },
                ],
            },
            "CORE": {
                "module_tag": "CORE",
                "planned_anchors": [
                    {
                        "anchor_kind": "new_symbol",
                        "anchor_materialization_kind": "runtime_logic",
                        "planned_file_path": "CORE/calc.py",
                        "spec_ids": ["A2001"],
                    },
                ],
            },
        }
        spec_dependencies = [
            {"consumer_spec_id": "A1001", "provider_spec_ids": ["A2001"]},
        ]
        shared_contracts = [
            {"contract_id": "NutritionRequestDTO", "consumed_by_specs": ["A1001"]},
            {"contract_id": "LoginRequestDTO", "consumed_by_specs": ["A1002"]},
        ]
        batch_plan = _build_batches(
            rows, spec_dependencies, {"max_specs_per_batch": 1, "max_files": 10},
            anchor_plans=module_plans,
        )
        briefs = _build_briefs(
            rows,
            module_plans,
            spec_dependencies,
            shared_contracts,
            batch_plan,
            {"forbidden_paths": [], "budgets": {"max_specs_per_batch": 1, "max_files": 10}, "verification_commands": []},
        )
        api_briefs = [b for b in briefs if b.get("spec_rows") and b["spec_rows"][0]["module_tag"] == "API"]
        self.assertEqual(len(api_briefs), 2)
        first = sorted(api_briefs, key=lambda b: b["spec_rows"][0]["spec_id"])[0]
        self.assertEqual(first["spec_rows"][0]["spec_id"], "A1001")
        self.assertEqual(len(first["planned_anchors"]), 1)
        self.assertEqual(first["planned_anchors"][0]["spec_ids"], ["A1001"])
        self.assertEqual(len(first["shared_contracts"]), 1)
        self.assertEqual(first["shared_contracts"][0]["contract_id"], "NutritionRequestDTO")
        self.assertTrue(len(first["spec_dependency_context"]) >= 1)

    def test_build_briefs_raises_when_planned_files_exceed_max_files(self) -> None:
        rows = [
            {"spec_id": "A1001", "module_tag": "API", "module_role": "api"},
        ]
        module_plans = {
            "API": {
                "module_tag": "API",
                "planned_anchors": [
                    {"planned_file_path": f"API/f{i}.py", "spec_ids": ["A1001"],
                     "anchor_kind": "new_symbol", "anchor_materialization_kind": "runtime_logic"}
                    for i in range(12)
                ],
            },
        }
        batch_plan = _build_batches(
            rows, [], {"max_specs_per_batch": 5, "max_files": 20},
            anchor_plans=module_plans,
        )
        impl = {"forbidden_paths": [], "budgets": {"max_files": 10}, "verification_commands": []}
        with self.assertRaises(ValueError) as ctx:
            _build_briefs(rows, module_plans, [], [], batch_plan, impl)
        self.assertIn("exceeds max_files", str(ctx.exception))

    def test_build_briefs_narrows_anchor_spec_ids_to_batch(self) -> None:
        """Anchors shared across batches must have spec_ids narrowed to the current batch."""
        rows = [
            {"spec_id": "A1001", "module_tag": "API", "module_role": "api"},
            {"spec_id": "A1002", "module_tag": "API", "module_role": "api"},
        ]
        module_plans = {
            "API": {
                "module_tag": "API",
                "planned_anchors": [
                    {
                        "anchor_kind": "new_symbol",
                        "anchor_materialization_kind": "test",
                        "planned_file_path": "API/tests/test_all.py",
                        "spec_ids": ["A1001", "A1002"],
                    },
                ],
            },
        }
        batch_plan = _build_batches(
            rows, [], {"max_specs_per_batch": 1, "max_files": 10},
            anchor_plans=module_plans,
        )
        briefs = _build_briefs(
            rows, module_plans, [], [], batch_plan,
            {"forbidden_paths": [], "budgets": {"max_specs_per_batch": 1, "max_files": 10}, "verification_commands": []},
        )
        for brief in briefs:
            batch_specs = {r["spec_id"] for r in brief["spec_rows"]}
            for anchor in brief["planned_anchors"]:
                for sid in anchor["spec_ids"]:
                    self.assertIn(sid, batch_specs,
                        f"Anchor spec_id {sid} leaked into batch {brief['batch_id']} "
                        f"which only contains {batch_specs}")

    def test_build_briefs_narrows_contract_consumed_by_specs_to_batch(self) -> None:
        """Shared contracts must have consumed_by_specs narrowed to the current batch."""
        rows = [
            {"spec_id": "A1001", "module_tag": "API", "module_role": "api"},
            {"spec_id": "A2001", "module_tag": "CORE", "module_role": "domain"},
        ]
        module_plans = {
            "API": {"module_tag": "API", "planned_anchors": [
                {"planned_file_path": "api/r.py", "spec_ids": ["A1001"],
                 "anchor_kind": "new_symbol", "anchor_materialization_kind": "runtime_logic"},
            ]},
            "CORE": {"module_tag": "CORE", "planned_anchors": [
                {"planned_file_path": "core/c.py", "spec_ids": ["A2001"],
                 "anchor_kind": "new_symbol", "anchor_materialization_kind": "runtime_logic"},
            ]},
        }
        shared_contracts = [
            {"contract_id": "DTO1", "consumed_by_specs": ["A1001", "A2001"]},
        ]
        batch_plan = _build_batches(
            rows, [{"consumer_spec_id": "A1001", "provider_spec_ids": ["A2001"]}],
            {"max_specs_per_batch": 5, "max_files": 10}, anchor_plans=module_plans,
        )
        briefs = _build_briefs(
            rows, module_plans,
            [{"consumer_spec_id": "A1001", "provider_spec_ids": ["A2001"]}],
            shared_contracts, batch_plan,
            {"forbidden_paths": [], "budgets": {"max_specs_per_batch": 5, "max_files": 10}, "verification_commands": []},
        )
        for brief in briefs:
            batch_specs = {r["spec_id"] for r in brief["spec_rows"]}
            for contract in brief.get("shared_contracts", []):
                for sid in contract["consumed_by_specs"]:
                    self.assertIn(sid, batch_specs,
                        f"Contract consumer {sid} leaked into batch {brief['batch_id']} "
                        f"which only contains {batch_specs}")


class BriefScopingValidationTests(unittest.TestCase):
    """Tests for _validate_brief_scoping."""

    def test_passes_when_all_scoped(self) -> None:
        briefs = [{
            "batch_id": "B0",
            "spec_rows": [{"spec_id": "A1"}],
            "planned_anchors": [{"spec_ids": ["A1"]}],
            "shared_contracts": [{"consumed_by_specs": ["A1"]}],
        }]
        result = _validate_brief_scoping(briefs)
        self.assertEqual(result["status"], "passed")

    def test_detects_anchor_leak(self) -> None:
        briefs = [{
            "batch_id": "B0",
            "spec_rows": [{"spec_id": "A1"}],
            "planned_anchors": [{"spec_ids": ["A1", "A2"]}],
            "shared_contracts": [],
        }]
        result = _validate_brief_scoping(briefs)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("planned_anchors" in r for r in result["reasons"]))

    def test_detects_contract_leak(self) -> None:
        briefs = [{
            "batch_id": "B0",
            "spec_rows": [{"spec_id": "A1"}],
            "planned_anchors": [],
            "shared_contracts": [{"consumed_by_specs": ["A1", "A2", "A3"]}],
        }]
        result = _validate_brief_scoping(briefs)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("shared_contracts" in r for r in result["reasons"]))


class ContractFieldConsistencyTests(unittest.TestCase):
    """Tests for _validate_contract_field_consistency."""

    def test_passes_when_contract_and_specs_match(self) -> None:
        """Provider and consumers all use same field names as contract."""
        headers = ["spec_id", "module_tag", "requirement", "acceptance_criteria"]
        spec_rows = [
            {
                "spec_id": "A1057",
                "module_tag": "SHARED",
                "requirement": "ExportRequest DTO with export_format, date_range_start, date_range_end, include_input_details",
                "acceptance_criteria": "Fields match shared contract.",
            },
            {
                "spec_id": "A1056",
                "module_tag": "UI",
                "requirement": "POST request containing export_format, date_range_start, date_range_end, include_input_details",
                "acceptance_criteria": "Values from modal controls.",
            },
        ]
        shared_contracts = [
            {
                "contract_id": "export_request_dto",
                "owning_module": "SHARED",
                "consumed_by_specs": ["A1057", "A1056"],
                "fields": [
                    {"name": "export_format", "type_name": "string", "nullable": False},
                    {"name": "date_range_start", "type_name": "string", "nullable": False},
                    {"name": "date_range_end", "type_name": "string", "nullable": False},
                    {"name": "include_input_details", "type_name": "boolean", "nullable": False},
                ],
            },
        ]
        result = _validate_contract_field_consistency(
            shared_contracts,
            spec_rows,
            headers,
            match_score_threshold=0.75,
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result.get("manual_resolution_items", []), [])

    def test_detects_consumer_mismatch_date_range(self) -> None:
        """A1056 says date_range but contract has date_range_start, date_range_end."""
        headers = ["spec_id", "module_tag", "requirement", "acceptance_criteria"]
        spec_rows = [
            {
                "spec_id": "A1057",
                "module_tag": "SHARED",
                "requirement": "ExportRequest DTO with export_format, date_range_start, date_range_end, include_input_details",
                "acceptance_criteria": "Fields match.",
            },
            {
                "spec_id": "A1056",
                "module_tag": "UI",
                "requirement": "POST request containing export_format, date_range, and include_input_details fields",
                "acceptance_criteria": "Values from modal.",
            },
        ]
        shared_contracts = [
            {
                "contract_id": "export_request_dto",
                "owning_module": "SHARED",
                "consumed_by_specs": ["A1057", "A1056"],
                "fields": [
                    {"name": "export_format", "type_name": "string", "nullable": False},
                    {"name": "date_range_start", "type_name": "string", "nullable": False},
                    {"name": "date_range_end", "type_name": "string", "nullable": False},
                    {"name": "include_input_details", "type_name": "boolean", "nullable": False},
                ],
            },
        ]
        result = _validate_contract_field_consistency(
            shared_contracts,
            spec_rows,
            headers,
            match_score_threshold=0.75,
        )
        self.assertEqual(result["status"], "failed")
        items = result.get("manual_resolution_items", [])
        self.assertGreaterEqual(len(items), 1)
        self.assertTrue(any(item.get("resolution_mode") == "edit_spec" for item in items))
        self.assertTrue(all((item.get("options") or []) == [] for item in items))
        self.assertTrue(
            any("date_range" in str(item.get("question", "")) for item in items),
            f"Expected date_range mismatch in items: {items}",
        )

    def test_detects_provider_mismatch_planner_deviation(self) -> None:
        """Contract has fields not in defining spec (planner deviation)."""
        headers = ["spec_id", "module_tag", "requirement", "acceptance_criteria"]
        spec_rows = [
            {
                "spec_id": "A1057",
                "module_tag": "SHARED",
                "requirement": "ExportRequest DTO with export_format, date_range_start, date_range_end, include_input_details",
                "acceptance_criteria": "Fields match.",
            },
        ]
        shared_contracts = [
            {
                "contract_id": "export_request_dto",
                "owning_module": "SHARED",
                "consumed_by_specs": ["A1057"],
                "fields": [
                    {"name": "export_format", "type_name": "string", "nullable": False},
                    {"name": "date_range", "type_name": "string", "nullable": False},  # planner used date_range, spec says date_range_start/end
                    {"name": "include_input_details", "type_name": "boolean", "nullable": False},
                ],
            },
        ]
        result = _validate_contract_field_consistency(
            shared_contracts,
            spec_rows,
            headers,
            match_score_threshold=0.75,
        )
        self.assertEqual(result["status"], "failed")
        items = result.get("manual_resolution_items", [])
        self.assertGreaterEqual(len(items), 1)
        self.assertTrue(any(item.get("resolution_mode") == "edit_spec" for item in items))
        self.assertTrue(all((item.get("options") or []) == [] for item in items))
        self.assertTrue(
            any("provider_deviation" in str(item.get("item_id", "")) for item in items),
            f"Expected provider deviation in items: {items}",
        )

    def test_still_fails_if_resolutions_exist_without_spec_edits(self) -> None:
        """Resolution records alone do not mutate contracts; specs must be edited."""
        headers = ["spec_id", "module_tag", "requirement", "acceptance_criteria"]
        spec_rows = [
            {
                "spec_id": "A1056",
                "module_tag": "UI",
                "requirement": "Export trigger sends date_range to API",
                "acceptance_criteria": "",
            },
            {
                "spec_id": "A1057",
                "module_tag": "SHARED",
                "requirement": "ExportRequest with date_range_start, date_range_end",
                "acceptance_criteria": "",
            },
        ]
        shared_contracts = [
            {
                "contract_id": "ExportRequest",
                "owning_module": "SHARED",
                "consumed_by_specs": ["A1056", "A1057"],
                "fields": [
                    {"name": "date_range_start"},
                    {"name": "date_range_end"},
                ],
            },
        ]
        resolutions = [
            {
                "item_id": "field_mismatch_ExportRequest_A1056_date_range",
                "chosen_option_id": "align_contract",
            },
        ]
        result = _validate_contract_field_consistency(
            shared_contracts,
            spec_rows,
            headers,
            resolutions=resolutions,
            match_score_threshold=0.75,
        )
        self.assertEqual(result["status"], "failed")
        self.assertGreaterEqual(len(result["manual_resolution_items"]), 1)

    def test_passes_when_no_contracts_with_fields(self) -> None:
        """Contracts without fields are skipped."""
        headers = ["spec_id", "module_tag", "requirement", "acceptance_criteria"]
        spec_rows = [{"spec_id": "A1", "module_tag": "API", "requirement": "x", "acceptance_criteria": ""}]
        shared_contracts = [
            {"contract_id": "c1", "owning_module": "SHARED", "consumed_by_specs": ["A1"], "fields": []},
        ]
        result = _validate_contract_field_consistency(
            shared_contracts,
            spec_rows,
            headers,
            match_score_threshold=0.75,
        )
        self.assertEqual(result["status"], "passed")

    def test_threshold_filters_non_issue_pairs(self) -> None:
        """No item is emitted when word distances are above threshold."""
        headers = ["spec_id", "module_tag", "requirement", "acceptance_criteria"]
        spec_rows = [
            {
                "spec_id": "A1",
                "module_tag": "UI",
                "requirement": "UI shows calculation summary for user.",
                "acceptance_criteria": "",
            },
            {
                "spec_id": "A2",
                "module_tag": "SHARED",
                "requirement": "Contract fields are calculation_version and request_id.",
                "acceptance_criteria": "",
            },
        ]
        shared_contracts = [
            {
                "contract_id": "nutrition_response_dto",
                "owning_module": "SHARED",
                "consumed_by_specs": ["A2", "A1"],
                "fields": [
                    {"name": "calculation_version"},
                    {"name": "request_id"},
                ],
            },
        ]
        result = _validate_contract_field_consistency(
            shared_contracts,
            spec_rows,
            headers,
            match_score_threshold=0.95,
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result.get("manual_resolution_items", []), [])

    def test_question_lists_high_match_pairs(self) -> None:
        """Validation question contains only high-match pairs and threshold text."""
        headers = ["spec_id", "module_tag", "requirement", "acceptance_criteria"]
        spec_rows = [
            {
                "spec_id": "A1057",
                "module_tag": "SHARED",
                "requirement": "ExportRequest DTO with export_format, date_range_start, date_range_end, include_input_details",
                "acceptance_criteria": "",
            },
            {
                "spec_id": "A1056",
                "module_tag": "UI",
                "requirement": "POST request containing export_format, date_range, include_input_details",
                "acceptance_criteria": "",
            },
        ]
        shared_contracts = [
            {
                "contract_id": "export_request_dto",
                "owning_module": "SHARED",
                "consumed_by_specs": ["A1057", "A1056"],
                "fields": [
                    {"name": "export_format"},
                    {"name": "date_range_start"},
                    {"name": "date_range_end"},
                    {"name": "include_input_details"},
                ],
            },
        ]
        result = _validate_contract_field_consistency(
            shared_contracts,
            spec_rows,
            headers,
            match_score_threshold=0.75,
        )
        self.assertEqual(result["status"], "failed")
        question_text = " ".join(
            str(item.get("question", ""))
            for item in result.get("manual_resolution_items", [])
        )
        self.assertIn("score_threshold=0.750", question_text)
        self.assertIn("date_range ~ date_range_end", question_text)

    def test_consumer_match_does_not_use_exactly_matched_contract_field(self) -> None:
        """Exact token matches are reserved and excluded from fuzzy mismatch matching."""
        headers = ["spec_id", "module_tag", "requirement", "acceptance_criteria"]
        spec_rows = [
            {
                "spec_id": "A1060",
                "module_tag": "DATA",
                "requirement": (
                    "Store the artifact and return artifact_id, file_name, expiration_utc "
                    "for persisted export artifact metadata."
                ),
                "acceptance_criteria": (
                    "Returns artifact_id, file_name, and expiration_utc fields."
                ),
            },
        ]
        shared_contracts = [
            {
                "contract_id": "export_artifact_metadata_dto",
                "owning_module": "DATA",
                "consumed_by_specs": ["A1060"],
                "fields": [
                    {"name": "artifact_id"},
                    {"name": "file_name"},
                    {"name": "expiration_utc"},
                ],
            },
        ]
        result = _validate_contract_field_consistency(
            shared_contracts,
            spec_rows,
            headers,
            match_score_threshold=0.80,
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result.get("manual_resolution_items", []), [])

    def test_consumer_matches_are_pruned_to_one_to_one_assignment(self) -> None:
        """When multiple source words target one field, keep only the global best pair."""
        headers = ["spec_id", "module_tag", "requirement", "acceptance_criteria"]
        spec_rows = [
            {
                "spec_id": "A2000",
                "module_tag": "SHARED",
                "requirement": "Response includes artifact_id and download_url.",
                "acceptance_criteria": "",
            },
            {
                "spec_id": "A2001",
                "module_tag": "UI",
                "requirement": (
                    "UI handles response fields artifact, id_artifact, and download_url."
                ),
                "acceptance_criteria": "",
            },
        ]
        shared_contracts = [
            {
                "contract_id": "export_link_response",
                "owning_module": "SHARED",
                "consumed_by_specs": ["A2000", "A2001"],
                "fields": [
                    {"name": "artifact_id"},
                    {"name": "download_url"},
                ],
            },
        ]
        result = _validate_contract_field_consistency(
            shared_contracts,
            spec_rows,
            headers,
            match_score_threshold=0.80,
        )
        items = [
            item
            for item in result.get("manual_resolution_items", [])
            if str(item.get("item_id", "")).startswith("field_mismatch_export_link_response_A2001_")
        ]
        self.assertEqual(len(items), 1, f"Expected exactly one pruned match item, got: {items}")
        self.assertIn("id_artifact", str(items[0].get("blocking_reason", "")))
        self.assertNotIn("Word 'artifact'", str(items[0].get("blocking_reason", "")))


class PlannedValidationChecksTests(unittest.TestCase):
    """Tests for v0.0.1 planned deterministic validation checks."""

    def test_required_field_coverage_passes_with_alias_resolution(self) -> None:
        headers = ["spec_id", "module_tag", "requirement", "acceptance_criteria"]
        spec_rows = [
            {
                "spec_id": "A1001",
                "module_tag": "API",
                "requirement": "The response includes artifactId and statusCode.",
                "acceptance_criteria": "",
            },
        ]
        shared_contracts = [
            {
                "contract_id": "artifact_response",
                "owning_module": "API",
                "planned_file_path": "shared/types/artifact_response.py",
                "consumed_by_specs": ["A1001"],
                "fields": [
                    {"name": "artifact_id", "type_name": "string", "nullable": False},
                    {"name": "status_code", "type_name": "integer", "nullable": False},
                ],
            }
        ]
        result = _validate_required_field_coverage(shared_contracts, spec_rows, headers)
        self.assertEqual(result["status"], "passed")

    def test_required_field_coverage_skips_when_provider_declares_canonical_contract(self) -> None:
        headers = ["spec_id", "module_tag", "requirement", "acceptance_criteria"]
        spec_rows = [
            {
                "spec_id": "A1027",
                "module_tag": "SHARED",
                "requirement": "Canonical DTO contract with explicit field names and field types.",
                "acceptance_criteria": "",
            },
            {
                "spec_id": "A1005",
                "module_tag": "UI",
                "requirement": "Submit request to API endpoint.",
                "acceptance_criteria": "",
            },
        ]
        shared_contracts = [
            {
                "contract_id": "nutrition_request_dto",
                "owning_module": "SHARED",
                "planned_file_path": "workspace/shared-contracts/nutrition_request_dto.json",
                "consumed_by_specs": ["A1027", "A1005"],
                "fields": [
                    {"name": "age", "type_name": "integer", "nullable": False},
                    {"name": "height_cm", "type_name": "number", "nullable": False},
                ],
            }
        ]
        result = _validate_required_field_coverage(shared_contracts, spec_rows, headers)
        self.assertEqual(result["status"], "passed")

    def test_dependency_context_edge_validation_detects_missing_edge(self) -> None:
        briefs = [
            {
                "batch_id": "B0",
                "spec_rows": [{"spec_id": "A1001"}],
                "spec_dependency_context": [],
            }
        ]
        spec_dependencies = [
            {"consumer_spec_id": "A1001", "provider_spec_ids": ["A2001"]},
        ]
        result = _validate_dependency_context_edges(briefs, spec_dependencies)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("Missing dependency-context edges" in reason for reason in result["reasons"]))


class ImplementDryRunTests(unittest.TestCase):
    """End-to-end dry-run tests for run_implement with unified planner."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="implement-handler-"))
        (self.tmp / "PROJECT_CONTEXT.md").write_text(
            "## Purpose\nx\n\n## Overview\nx\n\n## Workflow\nx\n",
            encoding="utf-8",
        )
        self.design = self.tmp / "design_spec.csv"
        self.design.write_text(
            "spec_id,module_tag,module_role,implementation_status,title,requirement\n"
            "A1,CORE,domain,,T1,R1\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    @patch("handlers.implement.impl.invoke_with_semantic_retry")
    def test_run_implement_dry_run_with_unified_planner(self, mock_invoke: Any) -> None:
        unified_plan_output = {
            "module_plans": [
                {
                    "module_tag": "CORE",
                    "planned_anchors": [
                        {
                            "anchor_kind": "new_symbol",
                            "anchor_materialization_kind": "runtime_logic",
                            "planned_file_path": "core/calc.py",
                            "spec_ids": ["A1"],
                        },
                    ],
                }
            ],
            "spec_dependencies": [],
            "shared_contracts": [],
        }
        mock_invoke.return_value = unified_plan_output

        config = {
            "agent": {"provider": "stub", "schema_validation_retries": 0},
            "project": {
                "name": "test",
                "root_dir": ".",
                "state": {
                    "design_spec_path": str(self.design),
                    "id_registry_path": str(self.tmp / "out" / "state" / "id_registry.json"),
                    "sads_id_mapping_path": str(self.tmp / "out" / "state" / "sads_id_mapping.json"),
                },
            },

            "commands": {
                "implement": {
                    "enabled": True,
                    "prompt_name": "implement_from_specs",
                    "required_field_coverage_validation": {"enabled": False},
                    "inputs": {
                        "design_spec_path": str(self.design),
                        "codebase_dir": ".",
                        "project_context_filename": "PROJECT_CONTEXT.md",
                    },
                    "outputs": {
                        "agent_runs_dir": {"path": "out/agent_runs", "no_overwrite": False},
                        "agent_artifacts_dir": {"path": "out/agent_artifacts", "no_overwrite": False},
                        "backups_dir": {"path": "out/backups", "no_overwrite": False},
                    },
                }
            },
        }
        ctx = RuntimeContext(
            command="implement",
            dry_run=True,
            verbose=False,
            command_only_validation=False,
            run_id="run-impl-001",
            project_root=str(self.tmp),
            config_path=str(self.tmp / "config.yaml"),
        )
        result = run_implement(config, ctx)
        self.assertEqual(result["status"], "completed")

        run_dir = self.tmp / "out" / "agent_runs" / "implement" / "run-impl-001"
        self.assertTrue((run_dir / "run_meta.json").exists())
        self.assertTrue((run_dir / "workset.json").exists())
        self.assertTrue((run_dir / "module_catalog.json").exists())
        self.assertTrue((run_dir / "unified_plan.json").exists())
        self.assertTrue((run_dir / "plan_validation.json").exists())
        self.assertTrue((run_dir / "batch_plan.json").exists())
        self.assertTrue((run_dir / "batch_plan_validation.json").exists())
        self.assertTrue((run_dir / "summary.json").exists())
        self.assertTrue((run_dir / "module_plans" / "CORE.json").exists())
        self.assertTrue((run_dir / "spec_issues.json").exists())

        mock_invoke.assert_called_once()
        call_kwargs = mock_invoke.call_args.kwargs
        self.assertEqual(call_kwargs["prompt_name"], "implement_unified_planner")
        self.assertIn("design_spec_csv", call_kwargs["template_vars"])
        self.assertIn("module_catalog_json", call_kwargs["template_vars"])

    @patch("handlers.implement.impl.invoke_with_semantic_retry")
    def test_run_implement_blocks_on_manual_resolution(self, mock_invoke: Any) -> None:
        mock_invoke.return_value = {
            "manual_resolution_items": [
                {
                    "item_id": "MR-1",
                    "title": "Ambiguous dependency",
                    "question": "Which module provides calculation?",
                    "options": [
                        {"option_id": "opt_a", "label": "CORE", "effect": "Bind to CORE"},
                    ],
                    "required": True,
                    "blocking_reason": "Cannot determine provider",
                }
            ]
        }

        config = {
            "agent": {"provider": "stub", "schema_validation_retries": 0},
            "project": {
                "name": "test",
                "root_dir": ".",
                "state": {
                    "design_spec_path": str(self.design),
                    "id_registry_path": str(self.tmp / "out" / "state" / "id_registry.json"),
                    "sads_id_mapping_path": str(self.tmp / "out" / "state" / "sads_id_mapping.json"),
                },
            },

            "commands": {
                "implement": {
                    "enabled": True,
                    "prompt_name": "implement_from_specs",
                    "required_field_coverage_validation": {"enabled": False},
                    "inputs": {
                        "design_spec_path": str(self.design),
                        "codebase_dir": ".",
                        "project_context_filename": "PROJECT_CONTEXT.md",
                    },
                    "outputs": {
                        "agent_runs_dir": {"path": "out/agent_runs", "no_overwrite": False},
                        "agent_artifacts_dir": {"path": "out/agent_artifacts", "no_overwrite": False},
                        "backups_dir": {"path": "out/backups", "no_overwrite": False},
                    },
                }
            },
        }
        ctx = RuntimeContext(
            command="implement",
            dry_run=True,
            verbose=False,
            command_only_validation=False,
            run_id="run-impl-block-001",
            project_root=str(self.tmp),
            config_path=str(self.tmp / "config.yaml"),
        )
        result = run_implement(config, ctx)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocking_items"], 1)

    @patch("handlers.implement.impl.invoke_with_semantic_retry")
    def test_run_implement_resume_uses_cached_unified_plan(self, mock_invoke: Any) -> None:
        """Resume run uses cached unified_plan when run_meta marks unified_planner completed."""
        cached_plan = {
            "module_plans": [
                {
                    "module_tag": "CORE",
                    "planned_anchors": [
                        {
                            "anchor_kind": "new_symbol",
                            "anchor_materialization_kind": "runtime_logic",
                            "planned_file_path": "core/calc.py",
                            "spec_ids": ["A1"],
                        }
                    ],
                }
            ],
            "spec_dependencies": [],
            "shared_contracts": [],
        }
        run_id = "run-resume-001"
        run_dir = self.tmp / "out" / "agent_runs" / "implement" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "unified_plan.json").write_text(json.dumps(cached_plan, indent=2), encoding="utf-8")
        (run_dir / "run_meta.json").write_text(
            json.dumps(
                {
                    "command": "implement",
                    "run_id": run_id,
                    "blocked_at_stage": "contract_field_consistency",
                    "completed_stages": ["load", "catalog", "unified_planner"],
                    "resolution_status": "resolved",
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        config = {
            "agent": {"provider": "stub", "schema_validation_retries": 0},
            "project": {
                "name": "test",
                "root_dir": ".",
                "state": {
                    "design_spec_path": str(self.design),
                    "id_registry_path": str(self.tmp / "out" / "state" / "id_registry.json"),
                    "sads_id_mapping_path": str(self.tmp / "out" / "state" / "sads_id_mapping.json"),
                },
            },

            "commands": {
                "implement": {
                    "enabled": True,
                    "prompt_name": "implement_from_specs",
                    "required_field_coverage_validation": {"enabled": False},
                    "inputs": {
                        "design_spec_path": str(self.design),
                        "codebase_dir": ".",
                        "project_context_filename": "PROJECT_CONTEXT.md",
                    },
                    "outputs": {
                        "agent_runs_dir": {"path": "out/agent_runs", "no_overwrite": False},
                        "agent_artifacts_dir": {"path": "out/agent_artifacts", "no_overwrite": False},
                        "backups_dir": {"path": "out/backups", "no_overwrite": False},
                    },
                }
            },
        }
        ctx = RuntimeContext(
            command="implement",
            dry_run=True,
            verbose=False,
            command_only_validation=False,
            run_id=run_id,
            project_root=str(self.tmp),
            config_path=str(self.tmp / "config.yaml"),
            resume_run_id=run_id,
            resolved_decisions="## Resolved Decisions\n\n- [MR-1] Use CORE",
        )
        result = run_implement(config, ctx)
        self.assertEqual(result["status"], "completed")
        mock_invoke.assert_not_called()

        run_meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
        self.assertIn("unified_planner", run_meta.get("completed_stages", []))
        self.assertIn("brief_validation", run_meta.get("completed_stages", []))
        self.assertIsNone(run_meta.get("blocked_at_stage"))
        self.assertIsNone(run_meta.get("resolution_status"))
        self.assertIsNone(run_meta.get("failed_at_stage"))

    @patch("handlers.implement.impl._validate_brief_scoping")
    @patch("handlers.implement.impl._validate_batch_plan_dependencies")
    @patch("handlers.implement.impl._build_batches")
    @patch("handlers.implement.impl._validate_contract_field_consistency")
    @patch("handlers.implement.impl.invoke_with_semantic_retry")
    def test_run_implement_uses_patched_contracts_from_validation(
        self,
        mock_invoke: Any,
        mock_contract_validation: Any,
        mock_build_batches: Any,
        mock_batch_validation: Any,
        mock_brief_validation: Any,
    ) -> None:
        """run_implement uses contract_validation.shared_contracts for downstream brief building."""
        mock_invoke.return_value = {
            "module_plans": [
                {
                    "module_tag": "CORE",
                    "planned_anchors": [
                        {
                            "anchor_kind": "new_symbol",
                            "anchor_materialization_kind": "runtime_logic",
                            "planned_file_path": "core/calc.py",
                            "spec_ids": ["A1"],
                        },
                    ],
                }
            ],
            "spec_dependencies": [],
            "shared_contracts": [{"contract_id": "C_ORIG", "fields": [{"name": "old"}], "consumed_by_specs": ["A1"]}],
        }
        patched_contracts = [
            {
                "contract_id": "C_PATCHED",
                "owning_module": "CORE",
                "consumed_by_specs": ["A1"],
                "fields": [{"name": "new_field"}],
            }
        ]
        mock_contract_validation.return_value = {
            "status": "passed",
            "manual_resolution_items": [],
            "reasons": [],
            "shared_contracts": patched_contracts,
        }
        mock_build_batches.return_value = {"batches": []}
        mock_batch_validation.return_value = {"status": "passed", "reasons": []}
        mock_brief_validation.return_value = {"status": "passed", "reasons": []}

        captured: dict[str, Any] = {}

        def fake_build_briefs(
            selected: list[dict[str, Any]],
            anchor_plans_by_module: dict[str, Any],
            spec_dependencies: list[dict[str, Any]],
            shared_contracts: list[dict[str, Any]],
            batch_plan: dict[str, Any],
            impl_cfg: dict[str, Any],
        ) -> list[dict[str, Any]]:
            _ = selected, anchor_plans_by_module, spec_dependencies, batch_plan, impl_cfg
            captured["shared_contracts"] = shared_contracts
            return []

        config = {
            "agent": {"provider": "stub", "schema_validation_retries": 0},
            "project": {
                "name": "test",
                "root_dir": ".",
                "state": {
                    "design_spec_path": str(self.design),
                    "id_registry_path": str(self.tmp / "out" / "state" / "id_registry.json"),
                    "sads_id_mapping_path": str(self.tmp / "out" / "state" / "sads_id_mapping.json"),
                },
            },

            "commands": {
                "implement": {
                    "enabled": True,
                    "prompt_name": "implement_from_specs",
                    "required_field_coverage_validation": {"enabled": False},
                    "inputs": {
                        "design_spec_path": str(self.design),
                        "codebase_dir": ".",
                        "project_context_filename": "PROJECT_CONTEXT.md",
                    },
                    "outputs": {
                        "agent_runs_dir": {"path": "out/agent_runs", "no_overwrite": False},
                        "agent_artifacts_dir": {"path": "out/agent_artifacts", "no_overwrite": False},
                        "backups_dir": {"path": "out/backups", "no_overwrite": False},
                    },
                }
            },
        }
        ctx = RuntimeContext(
            command="implement",
            dry_run=True,
            verbose=False,
            command_only_validation=False,
            run_id="run-contract-patch-001",
            project_root=str(self.tmp),
            config_path=str(self.tmp / "config.yaml"),
        )

        with patch("handlers.implement.impl._build_briefs", side_effect=fake_build_briefs):
            result = run_implement(config, ctx)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(captured.get("shared_contracts"), patched_contracts)


class SpecIssuesExtractionTests(ImplementDryRunTests):
    """Tests for spec_issues extraction and persistence from planner Phase 0 output."""

    def _make_plan(self, spec_issues: list[dict] | None = None) -> dict:
        plan: dict = {
            "module_plans": [
                {
                    "module_tag": "CORE",
                    "planned_anchors": [
                        {
                            "anchor_kind": "new_symbol",
                            "anchor_materialization_kind": "runtime_logic",
                            "planned_file_path": "core/calc.py",
                            "spec_ids": ["A1"],
                        }
                    ],
                }
            ],
            "spec_dependencies": [],
            "shared_contracts": [],
        }
        if spec_issues is not None:
            plan["spec_issues"] = spec_issues
        return plan

    def _make_config_ctx(self) -> tuple[dict, Any]:
        from core.context import RuntimeContext

        config = {
            "agent": {"provider": "stub", "schema_validation_retries": 0},
            "project": {
                "name": "test",
                "root_dir": ".",
                "state": {
                    "design_spec_path": str(self.design),
                    "id_registry_path": str(self.tmp / "out" / "state" / "id_registry.json"),
                    "sads_id_mapping_path": str(self.tmp / "out" / "state" / "sads_id_mapping.json"),
                },
            },

            "commands": {
                "implement": {
                    "enabled": True,
                    "prompt_name": "implement_from_specs",
                    "required_field_coverage_validation": {"enabled": False},
                    "inputs": {
                        "design_spec_path": str(self.design),
                        "codebase_dir": ".",
                        "project_context_filename": "PROJECT_CONTEXT.md",
                    },
                    "outputs": {
                        "agent_runs_dir": {"path": "out/agent_runs", "no_overwrite": False},
                        "agent_artifacts_dir": {"path": "out/agent_artifacts", "no_overwrite": False},
                        "backups_dir": {"path": "out/backups", "no_overwrite": False},
                    },
                }
            },
        }
        ctx = RuntimeContext(
            command="implement",
            dry_run=True,
            verbose=False,
            command_only_validation=False,
            run_id="run-spec-issues-001",
            project_root=str(self.tmp),
            config_path=str(self.tmp / "config.yaml"),
        )
        return config, ctx

    def _run_dir(self) -> "Path":
        return self.tmp / "out" / "agent_runs" / "implement" / "run-spec-issues-001"

    @patch("handlers.implement.impl.invoke_with_semantic_retry")
    def test_spec_issues_written_to_disk_when_present(self, mock_invoke: Any) -> None:
        """spec_issues.json is written even when escalation blocks execution."""
        mock_invoke.return_value = self._make_plan(spec_issues=[
            {
                "issue_id": "ISSUE-001",
                "kind": "ambiguity",
                "affected_spec_ids": ["A1"],
                "description": "R1 does not specify a return value.",
                "resolution_hint": "Add expected return type to requirement.",
            }
        ])
        config, ctx = self._make_config_ctx()
        result = run_implement(config, ctx)
        # All spec_issue kinds now escalate to blocking manual_resolution_items (step 8)
        self.assertEqual(result["status"], "blocked")
        spec_issues_path = self._run_dir() / "spec_issues.json"
        self.assertTrue(spec_issues_path.exists())
        data = json.loads(spec_issues_path.read_text(encoding="utf-8"))
        self.assertEqual(len(data["spec_issues"]), 1)
        self.assertEqual(data["spec_issues"][0]["issue_id"], "ISSUE-001")
        self.assertEqual(data["spec_issues"][0]["kind"], "ambiguity")

    @patch("handlers.implement.impl.invoke_with_semantic_retry")
    def test_spec_issues_empty_file_written_when_no_issues(self, mock_invoke: Any) -> None:
        """spec_issues.json is written empty when planner emits no spec_issues key."""
        mock_invoke.return_value = self._make_plan()  # no spec_issues key
        config, ctx = self._make_config_ctx()
        result = run_implement(config, ctx)
        self.assertEqual(result["status"], "completed")
        spec_issues_path = self._run_dir() / "spec_issues.json"
        self.assertTrue(spec_issues_path.exists())
        data = json.loads(spec_issues_path.read_text(encoding="utf-8"))
        self.assertEqual(data["spec_issues"], [])

    @patch("handlers.implement.impl.invoke_with_semantic_retry")
    def test_spec_issues_each_logged_at_warn_level(self, mock_invoke: Any) -> None:
        """Each spec_issue generates a warning-level phase log entry on stderr."""
        mock_invoke.return_value = self._make_plan(spec_issues=[
            {
                "issue_id": "ISSUE-001",
                "kind": "contradiction",
                "affected_spec_ids": ["A1"],
                "description": "Conflicting status codes.",
            }
        ])
        config, ctx = self._make_config_ctx()
        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            run_implement(config, ctx)
        output = buf.getvalue()
        self.assertIn("ISSUE-001", output)
        self.assertIn("contradiction", output)
        self.assertIn("A1", output)
        self.assertIn("warning", output)

    @patch("handlers.implement.impl.invoke_with_semantic_retry")
    def test_spec_issues_all_five_kinds_preserved(self, mock_invoke: Any) -> None:
        """All five issue kinds are preserved when the planner emits one of each."""
        taxonomy = ["contradiction", "overlap", "dependency_gap", "ambiguity", "orphan_reference"]
        issues = [
            {
                "issue_id": f"ISSUE-00{i + 1}",
                "kind": kind,
                "affected_spec_ids": ["A1"],
                "description": f"Test {kind}.",
            }
            for i, kind in enumerate(taxonomy)
        ]
        mock_invoke.return_value = self._make_plan(spec_issues=issues)
        config, ctx = self._make_config_ctx()
        run_implement(config, ctx)
        data = json.loads((self._run_dir() / "spec_issues.json").read_text(encoding="utf-8"))
        kinds = {item["kind"] for item in data["spec_issues"]}
        self.assertEqual(kinds, set(taxonomy))


class ImplementLocalSharedWorkspaceTests(unittest.TestCase):
    """Tests for run-scoped shared temp workspace wiring in implement handler."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="implement-local-shared-"))
        (self.tmp / "PROJECT_CONTEXT.md").write_text(
            "## Purpose\nx\n\n## Overview\nx\n\n## Workflow\nx\n",
            encoding="utf-8",
        )
        self.design = self.tmp / "design_spec.csv"
        self.design.write_text(
            "spec_id,module_tag,module_role,implementation_status,title,requirement\n"
            "A1,CORE,domain,,T1,R1\n",
            encoding="utf-8",
        )
        self.shared_workspace = self.tmp / "shared-workspace"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _config(self) -> dict[str, Any]:
        return {
            "agent": {"provider": "local", "schema_validation_retries": 0},
            "project": {
                "name": "test",
                "root_dir": ".",
                "state": {
                    "design_spec_path": str(self.design),
                    "id_registry_path": str(self.tmp / "out" / "state" / "id_registry.json"),
                    "sads_id_mapping_path": str(self.tmp / "out" / "state" / "sads_id_mapping.json"),
                },
            },

            "commands": {
                "implement": {
                    "enabled": True,
                    "prompt_name": "implement_from_specs",
                    "inputs": {
                        "design_spec_path": str(self.design),
                        "codebase_dir": ".",
                        "project_context_filename": "PROJECT_CONTEXT.md",
                    },
                    "outputs": {
                        "agent_runs_dir": {"path": "out/agent_runs", "no_overwrite": False},
                        "agent_artifacts_dir": {"path": "out/agent_artifacts", "no_overwrite": False},
                        "backups_dir": {"path": "out/backups", "no_overwrite": False},
                    },
                }
            },
        }

    def test_local_shared_workspace_passed_to_planner_and_batch(self) -> None:
        """Local provider uses one shared workspace path for planner and batch execution (sequential mode)."""
        config = self._config()
        config["commands"]["implement"]["budgets"] = {"max_parallel_batches": 1}
        planner_output = {
            "module_plans": [
                {
                    "module_tag": "CORE",
                    "planned_anchors": [
                        {
                            "anchor_kind": "new_symbol",
                            "anchor_materialization_kind": "runtime_logic",
                            "planned_file_path": "core/calc.py",
                            "spec_ids": ["A1"],
                        },
                    ],
                }
            ],
            "spec_dependencies": [],
            "shared_contracts": [],
        }
        brief = {
            "batch_id": "B0",
            "spec_rows": [{"spec_id": "A1", "module_tag": "CORE", "module_role": "domain"}],
            "constraints": {},
            "planned_anchors": [{"planned_file_path": "core/calc.py"}],
            "shared_contracts": [],
        }

        ctx = RuntimeContext(
            command="implement",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-local-shared-1",
            project_root=str(self.tmp),
            config_path=str(self.tmp / "config.yaml"),
        )

        with patch("handlers.implement.impl.create_local_agent_shared_workspace", return_value=self.shared_workspace) as mock_create:
            with patch("handlers.implement.impl.sync_local_agent_workspace") as mock_sync:
                with patch("handlers.implement.impl.invoke_with_semantic_retry", return_value=planner_output) as mock_invoke:
                    with patch("handlers.implement.impl._build_batches", return_value={"batches": [{"batch_id": "B0"}]}):
                        with patch("handlers.implement.impl._validate_batch_plan_dependencies", return_value={"status": "passed", "reasons": []}):
                            with patch("handlers.implement.impl._build_briefs", return_value=[brief]):
                                with patch("handlers.implement.impl._validate_brief_scoping", return_value={"status": "passed", "reasons": []}):
                                    with patch("handlers.implement.impl._execute_batch", return_value={"status": "completed", "spec_outputs": {}}) as mock_execute:
                                        with patch("handlers.implement.impl._update_design_and_test_spec"):
                                            with patch("handlers.implement.impl.cleanup_local_agent_temp_workspace") as mock_cleanup:
                                                result = run_implement(config, ctx)

        self.assertEqual(result["status"], "completed")
        mock_create.assert_called_once_with(
            config,
            self.tmp,
            command="implement",
            run_id="run-local-shared-1",
        )
        self.assertEqual(mock_sync.call_count, 2)
        self.assertTrue((self.tmp / "CORE").is_dir())
        for sync_call in mock_sync.call_args_list:
            self.assertEqual(sync_call.args[0], self.tmp.resolve())
            self.assertEqual(sync_call.args[1], self.shared_workspace)
        self.assertEqual(
            mock_invoke.call_args.kwargs.get("local_workspace_override"),
            self.shared_workspace,
        )
        self.assertEqual(
            mock_execute.call_args.kwargs.get("local_workspace_override"),
            self.shared_workspace,
        )
        mock_cleanup.assert_called_once_with(self.shared_workspace)

    def test_local_shared_workspace_cleaned_when_planner_blocks(self) -> None:
        """Shared workspace is cleaned even when unified planner blocks."""
        config = self._config()
        blocked_output = {
            "manual_resolution_items": [
                {
                    "item_id": "MR-1",
                    "title": "Ambiguous",
                    "question": "Choose one",
                    "options": [{"option_id": "opt1", "label": "A", "effect": "Use A"}],
                    "required": True,
                    "blocking_reason": "Cannot choose automatically",
                }
            ]
        }
        ctx = RuntimeContext(
            command="implement",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-local-shared-blocked-1",
            project_root=str(self.tmp),
            config_path=str(self.tmp / "config.yaml"),
        )

        with patch("handlers.implement.impl.create_local_agent_shared_workspace", return_value=self.shared_workspace):
            with patch("handlers.implement.impl.invoke_with_semantic_retry", return_value=blocked_output):
                with patch("handlers.implement.impl.sync_local_agent_workspace"):
                    with patch("handlers.implement.impl.cleanup_local_agent_temp_workspace") as mock_cleanup:
                        result = run_implement(config, ctx)

        self.assertEqual(result["status"], "blocked")
        mock_cleanup.assert_called_once_with(self.shared_workspace)

    def test_local_shared_workspace_cleaned_when_planner_raises_timeout(self) -> None:
        """Shared workspace is cleaned and failed status is returned when planner invocation times out."""
        config = self._config()
        ctx = RuntimeContext(
            command="implement",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-local-shared-timeout-1",
            project_root=str(self.tmp),
            config_path=str(self.tmp / "config.yaml"),
        )

        with patch("handlers.implement.impl.create_local_agent_shared_workspace", return_value=self.shared_workspace):
            with patch(
                "handlers.implement.impl.invoke_with_semantic_retry",
                side_effect=subprocess.TimeoutExpired(cmd="codex", timeout=600),
            ):
                with patch("handlers.implement.impl.sync_local_agent_workspace"):
                    with patch("handlers.implement.impl.cleanup_local_agent_temp_workspace") as mock_cleanup:
                        result = run_implement(config, ctx)

        self.assertEqual(result["status"], "failed")
        self.assertIn("planner agent failed", result["reason"].lower())
        mock_cleanup.assert_called_once_with(self.shared_workspace)


class EscalateSpecIssuesTests(unittest.TestCase):
    """Tests for _escalate_spec_issues — all spec_issue kinds escalate to blocking items."""

    def _make_selected(self, assignments: dict[str, str]) -> list[dict[str, Any]]:
        """Build workset rows from {spec_id: module_tag} mapping."""
        return [{"spec_id": sid, "module_tag": tag} for sid, tag in assignments.items()]

    def test_no_issues_returns_empty(self) -> None:
        """Empty spec_issues list returns empty escalation list."""
        result = _escalate_spec_issues([], self._make_selected({"A1": "API"}))
        self.assertEqual(result, [])

    def test_overlap_kind_is_escalated(self) -> None:
        """All spec_issue kinds are escalated, including overlap."""
        issues = [
            {
                "issue_id": "I001",
                "kind": "overlap",
                "affected_spec_ids": ["A1", "A2"],
                "description": "Overlap issue",
            }
        ]
        selected = self._make_selected({"A1": "API", "A2": "OBS"})
        result = _escalate_spec_issues(issues, selected)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["item_id"], "I001")
        self.assertIn("Overlapping responsibilities", result[0]["blocking_reason"])

    def test_single_module_gap_is_escalated(self) -> None:
        """A dependency_gap in the same module is still escalated (no module filter)."""
        issues = [
            {
                "issue_id": "I001",
                "kind": "dependency_gap",
                "affected_spec_ids": ["A1", "A2"],
                "description": "Single module gap",
            }
        ]
        selected = self._make_selected({"A1": "API", "A2": "API"})
        result = _escalate_spec_issues(issues, selected)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["item_id"], "I001")

    def test_dependency_gap_is_escalated(self) -> None:
        """A dependency_gap is escalated to a blocking manual_resolution_item."""
        issues = [
            {
                "issue_id": "I001",
                "kind": "dependency_gap",
                "affected_spec_ids": ["A1", "D1", "D2"],
                "description": "Export flow missing history retrieval step",
                "resolution_hint": "Amend A1 to require history retrieval before calling D1",
            }
        ]
        selected = self._make_selected({"A1": "API", "D1": "DATA", "D2": "DATA"})
        result = _escalate_spec_issues(issues, selected)
        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertEqual(item["item_id"], "I001")
        self.assertEqual(item["required"], True)
        self.assertIn("Dependency gap", item["blocking_reason"])
        self.assertEqual(item["evidence_refs"], ["A1", "D1", "D2"])
        self.assertEqual(item["options"], [])
        self.assertEqual(item["resolution_mode"], "edit_spec")
        self.assertEqual(item["spec_amendment_hints"], "Amend A1 to require history retrieval before calling D1")

    def test_no_hint_has_empty_options(self) -> None:
        """An issue with no resolution_hint produces empty options list."""
        issues = [
            {
                "issue_id": "I002",
                "kind": "dependency_gap",
                "affected_spec_ids": ["A1", "C1"],
                "description": "Missing intermediary step",
            }
        ]
        selected = self._make_selected({"A1": "API", "C1": "CORE"})
        result = _escalate_spec_issues(issues, selected)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["options"], [])

    def test_title_truncated_to_120_chars(self) -> None:
        """Title is truncated to 120 characters from description."""
        long_desc = "X" * 200
        issues = [
            {
                "issue_id": "I003",
                "kind": "dependency_gap",
                "affected_spec_ids": ["A1", "B1"],
                "description": long_desc,
            }
        ]
        selected = self._make_selected({"A1": "API", "B1": "CORE"})
        result = _escalate_spec_issues(issues, selected)
        self.assertEqual(len(result[0]["title"]), 120)

    def test_all_kinds_escalated(self) -> None:
        """All 5 spec_issue kinds (contradiction, overlap, dependency_gap, ambiguity, orphan_reference) escalate."""
        kinds = ["contradiction", "overlap", "dependency_gap", "ambiguity", "orphan_reference"]
        issues = [
            {"issue_id": f"I{i:03d}", "kind": k, "affected_spec_ids": ["A1", "A2"], "description": f"{k} issue"}
            for i, k in enumerate(kinds)
        ]
        selected = self._make_selected({"A1": "API", "A2": "CORE"})
        result = _escalate_spec_issues(issues, selected)
        self.assertEqual(len(result), 5)
        result_ids = {item["item_id"] for item in result}
        self.assertEqual(result_ids, {"I000", "I001", "I002", "I003", "I004"})

    def test_blocking_reason_includes_kind(self) -> None:
        """Each kind has a distinct blocking_reason template."""
        expected_snippets = {
            "contradiction": "Mutually exclusive",
            "overlap": "Overlapping responsibilities",
            "dependency_gap": "Dependency gap",
            "ambiguity": "Ambiguous requirement",
            "orphan_reference": "Orphan reference",
        }
        for kind, snippet in expected_snippets.items():
            issues = [{"issue_id": "I001", "kind": kind, "affected_spec_ids": ["A1"], "description": "test"}]
            selected = self._make_selected({"A1": "API"})
            result = _escalate_spec_issues(issues, selected)
            self.assertEqual(len(result), 1, f"kind={kind} should produce 1 item")
            self.assertIn(snippet, result[0]["blocking_reason"], f"kind={kind}")


class TestContractFieldNullableMetadata(unittest.TestCase):
    """Tests for nullable enforcement in stage 11 (contract_field_consistency) and stage 12/17."""

    _HEADERS = ["spec_id", "module_tag", "requirement", "acceptance_criteria"]

    def _spec(self, spec_id: str, module: str, req: str = "x") -> dict[str, Any]:
        return {"spec_id": spec_id, "module_tag": module, "requirement": req, "acceptance_criteria": ""}

    # --- Stage 11 structural pre-pass ---

    def test_stage11_rejects_field_missing_nullable(self) -> None:
        """Field with name+type_name but no nullable triggers a missing_nullable item."""
        contracts = [{
            "contract_id": "my_dto",
            "owning_module": "SHARED",
            "consumed_by_specs": ["A1"],
            "fields": [{"name": "user_id", "type_name": "string"}],  # no nullable
        }]
        spec_rows = [self._spec("A1", "SHARED", "user_id field for my_dto")]
        result = _validate_contract_field_consistency(
            contracts, spec_rows, self._HEADERS, match_score_threshold=0.8
        )
        self.assertEqual(result["status"], "failed")
        item_ids = [item["item_id"] for item in result.get("manual_resolution_items", [])]
        self.assertTrue(any("missing_nullable" in iid for iid in item_ids), item_ids)

    def test_stage11_accepts_field_with_nullable_true_and_false(self) -> None:
        """Fields with explicit nullable=true/false emit no structural items."""
        contracts = [{
            "contract_id": "my_dto",
            "owning_module": "SHARED",
            "consumed_by_specs": ["A1"],
            "fields": [
                {"name": "user_id", "type_name": "string", "nullable": False},
                {"name": "display_name", "type_name": "string", "nullable": True},
            ],
        }]
        spec_rows = [self._spec("A1", "SHARED", "user_id display_name fields for my_dto")]
        result = _validate_contract_field_consistency(
            contracts, spec_rows, self._HEADERS, match_score_threshold=0.8
        )
        items = result.get("manual_resolution_items", [])
        structural_items = [
            item for item in items
            if "missing_nullable" in item.get("item_id", "")
            or "duplicate_field" in item.get("item_id", "")
        ]
        self.assertEqual(structural_items, [], structural_items)

    def test_stage11_rejects_duplicate_field_names(self) -> None:
        """Two fields with identical names in one contract trigger a duplicate_field item."""
        contracts = [{
            "contract_id": "my_dto",
            "owning_module": "SHARED",
            "consumed_by_specs": ["A1"],
            "fields": [
                {"name": "user_id", "type_name": "string", "nullable": False},
                {"name": "user_id", "type_name": "integer", "nullable": False},  # duplicate
            ],
        }]
        spec_rows = [self._spec("A1", "SHARED", "user_id field")]
        result = _validate_contract_field_consistency(
            contracts, spec_rows, self._HEADERS, match_score_threshold=0.8
        )
        self.assertEqual(result["status"], "failed")
        item_ids = [item["item_id"] for item in result.get("manual_resolution_items", [])]
        self.assertTrue(any("duplicate_field" in iid for iid in item_ids), item_ids)

    # --- Stage 12 providerless handling ---

    def test_stage12_manual_block_on_no_provider(self) -> None:
        """No provider spec always emits manual_resolution_item and fails."""
        contracts = [{
            "contract_id": "shared_filter",
            "owning_module": "DOMAIN",
            "consumed_by_specs": ["U3"],  # U3 is UI, not DOMAIN
            "fields": [{"name": "status", "type_name": "string", "nullable": True}],
        }]
        spec_rows = [self._spec("U3", "UI", "status filter for shared_filter")]
        result = _validate_required_field_coverage(contracts, spec_rows, self._HEADERS)
        self.assertEqual(result["status"], "failed")
        items = result.get("manual_resolution_items", [])
        self.assertGreater(len(items), 0, "Expected at least one manual_resolution_item")
        item_ids = [item["item_id"] for item in items]
        self.assertTrue(any("no_provider_spec_shared_filter" in iid for iid in item_ids), item_ids)
        checks = result.get("checks", [])
        self.assertTrue(any("manual_block_no_provider_spec" in c for c in checks), checks)

    # --- Stage 17 nullable check in brief scoping ---

    def test_stage17_rejects_field_missing_nullable_in_brief(self) -> None:
        """Brief with a contract field missing nullable causes scope validation to fail."""
        briefs = [{
            "batch_id": "B0",
            "spec_rows": [{"spec_id": "A1"}],
            "planned_anchors": [],
            "shared_contracts": [{
                "contract_id": "my_dto",
                "consumed_by_specs": ["A1"],
                "fields": [{"name": "user_id", "type_name": "string"}],  # no nullable
            }],
        }]
        result = _validate_brief_scoping(briefs)
        self.assertEqual(result["status"], "failed")
        reasons = result.get("reasons", [])
        self.assertTrue(any("nullable" in r for r in reasons), reasons)

    def test_stage17_passes_when_all_fields_have_nullable(self) -> None:
        """Brief with all contract fields having nullable passes scope validation."""
        briefs = [{
            "batch_id": "B0",
            "spec_rows": [{"spec_id": "A1"}],
            "planned_anchors": [],
            "shared_contracts": [{
                "contract_id": "my_dto",
                "consumed_by_specs": ["A1"],
                "fields": [{"name": "user_id", "type_name": "string", "nullable": False}],
            }],
        }]
        result = _validate_brief_scoping(briefs)
        self.assertEqual(result["status"], "passed")
        self.assertIn("contract_fields_have_nullable", result.get("checks", []))


if __name__ == "__main__":
    unittest.main()
