"""Tests for handlers.implement."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from core.context import RuntimeContext
from core.pika_config import reset_pika_config_cache
from handlers.implement import (
    _build_linker_retry_context,
    _build_batches,
    _build_briefs,
    _build_module_catalog,
    _collect_low_confidence_items,
    _get_impl_cfg,
    _resolve_min_confidence_threshold,
    _select_workset,
    _validate_batch_plan_dependencies,
    _validate_link_plan,
    run_implement,
)


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


class ImplementLowConfidenceTests(unittest.TestCase):
    """Tests for low-confidence manual resolution during batch briefs planning."""

    def test_collect_low_confidence_items_empty_when_threshold_zero(self) -> None:
        briefs = [
            {
                "batch_id": "B1",
                "relevant_bindings": [
                    {"contract_id": "c1", "confidence": 0.5, "required_ref": {}, "provided_ref": {}},
                ],
            }
        ]
        items = _collect_low_confidence_items(briefs, {}, 0.0)
        self.assertEqual(items, [])

    def test_collect_low_confidence_items_collects_bindings_below_threshold(self) -> None:
        briefs = [
            {
                "batch_id": "B1",
                "relevant_bindings": [
                    {
                        "contract_id": "ctr.api.x.v1",
                        "confidence": 0.75,
                        "required_ref": {"module_tag": "UI", "intent_local_id": "req"},
                        "provided_ref": {"module_tag": "API", "intent_local_id": "prov"},
                    },
                ],
            }
        ]
        items = _collect_low_confidence_items(briefs, {}, 0.85)
        self.assertEqual(len(items), 1)
        self.assertIn("low_conf_binding_", items[0]["item_id"])
        self.assertIn("0.75", items[0]["title"])
        self.assertEqual(items[0]["required"], True)
        self.assertEqual(len(items[0]["options"]), 2)

    def test_collect_low_confidence_items_skips_bindings_above_threshold(self) -> None:
        briefs = [
            {
                "batch_id": "B1",
                "relevant_bindings": [
                    {"contract_id": "c1", "confidence": 0.95, "required_ref": {}, "provided_ref": {}},
                ],
            }
        ]
        items = _collect_low_confidence_items(briefs, {}, 0.85)
        self.assertEqual(items, [])

    def test_resolve_min_confidence_threshold_project_overrides_pika(self) -> None:
        """Project config overrides pika config."""
        reset_pika_config_cache()
        impl = {"min_confidence_threshold": 0.9}
        self.assertEqual(_resolve_min_confidence_threshold(impl), 0.9)

    def test_resolve_min_confidence_threshold_falls_back_to_pika(self) -> None:
        """When project omits, pika config is used (0.7 default)."""
        reset_pika_config_cache()
        impl = {}
        self.assertEqual(_resolve_min_confidence_threshold(impl), 0.7)

    def test_collect_low_confidence_items_collects_intents_from_anchor_plans(self) -> None:
        briefs = []
        anchor_plans = {
            "API": {
                "provided_intents": [
                    {"intent_local_id": "api_x", "confidence": 0.7, "spec_ids": []},
                ],
                "required_intents": [],
            }
        }
        items = _collect_low_confidence_items(briefs, anchor_plans, 0.85)
        self.assertEqual(len(items), 1)
        self.assertIn("low_conf_intent_", items[0]["item_id"])
        self.assertIn("API", items[0]["item_id"])


class ImplementValidationTests(unittest.TestCase):
    """Tests for deterministic linker validation."""

    def test_validate_link_plan_detects_unbound_required(self) -> None:
        anchor_plans = {
            "API": {
                "required_intents": [
                    {"intent_local_id": "API_REQ_1"},
                ]
            }
        }
        module_catalog = {
            "modules": [{"module_tag": "API", "module_role": "api"}]
        }
        link_plan = {"contracts": [], "bindings": []}
        result = _validate_link_plan(anchor_plans, module_catalog, link_plan, "workspace/shared-contracts/")
        self.assertEqual(result["status"], "failed")
        self.assertIn("Unbound required intents exist", result["reasons"])
        self.assertEqual(
            result["unbound_required_refs"],
            [{"module_tag": "API", "intent_local_id": "API_REQ_1"}],
        )
        self.assertEqual(
            result["violations"][0]["code"],
            "unbound_required_intent",
        )

    def test_build_linker_retry_context_sorts_refs(self) -> None:
        context = _build_linker_retry_context(
            linker_attempt=1,
            linker_max_attempts=2,
            unbound_required_refs=[
                {"module_tag": "UI", "intent_local_id": "B"},
                {"module_tag": "API", "intent_local_id": "A"},
            ],
            validation_violations=[{"code": "disallowed_kind_for_required_role"}],
        )
        self.assertEqual(context["retry_reason"], "link_plan_validation_failed")
        self.assertEqual(context["next_attempt"], 2)
        self.assertEqual(
            context["unbound_required_intents"],
            [
                {"module_tag": "API", "intent_local_id": "A"},
                {"module_tag": "UI", "intent_local_id": "B"},
            ],
        )
        self.assertEqual(len(context["validation_violations"]), 1)

    def test_get_impl_cfg_defaults_disallowed_policy(self) -> None:
        cfg = {"commands": {"implement": {"enabled": True, "prompt_name": "implement_from_specs"}}}
        impl = _get_impl_cfg(cfg)
        self.assertIn("frontend", impl["disallowed_link_kinds_by_required_role"])
        self.assertIn("external_api", impl["disallowed_link_kinds_by_required_role"]["frontend"])
        self.assertIn("domain", impl["disallowed_link_kinds_by_required_role"])
        self.assertIn("external_api", impl["disallowed_link_kinds_by_required_role"]["domain"])

    def test_get_impl_cfg_overrides_disallowed_policy(self) -> None:
        cfg = {
            "commands": {
                "implement": {
                    "enabled": True,
                    "prompt_name": "implement_from_specs",
                    "disallowed_link_kinds_by_required_role": {
                        "frontend": ["external_api"],
                    },
                }
            }
        }
        impl = _get_impl_cfg(cfg)
        self.assertEqual(
            impl["disallowed_link_kinds_by_required_role"],
            {"frontend": {"external_api"}},
        )

    def test_validate_link_plan_uses_configured_disallowed_policy(self) -> None:
        anchor_plans = {
            "UI": {"required_intents": [{"intent_local_id": "UI_REQ_1"}]},
        }
        module_catalog = {
            "modules": [{"module_tag": "UI", "module_role": "frontend"}]
        }
        link_plan = {
            "contracts": [
                {
                    "contract_id": "ctr.ui.external",
                    "kind": "external_api",
                    "canonical_name": "x",
                    "shape": {},
                }
            ],
            "bindings": [
                {
                    "required_ref": {"module_tag": "UI", "intent_local_id": "UI_REQ_1"},
                    "provided_ref": {"module_tag": "API", "intent_local_id": "API_PROV_1"},
                    "contract_id": "ctr.ui.external",
                    "confidence": 0.9,
                    "rationale": "x",
                }
            ],
        }
        allowed_result = _validate_link_plan(
            anchor_plans,
            module_catalog,
            link_plan,
            "workspace/shared-contracts/",
            {},
        )
        self.assertEqual(allowed_result["status"], "passed")

        disallowed_result = _validate_link_plan(
            anchor_plans,
            module_catalog,
            link_plan,
            "workspace/shared-contracts/",
            {"frontend": {"external_api"}},
        )
        self.assertEqual(disallowed_result["status"], "failed")
        self.assertTrue(
            any("frontend module UI requires disallowed kind external_api" in reason for reason in disallowed_result["reasons"])
        )
        self.assertTrue(
            any(v.get("code") == "disallowed_kind_for_required_role" for v in disallowed_result["violations"])
        )


class ImplementBatchPlanTests(unittest.TestCase):
    """Tests for deterministic graph-aware batch planning and brief scoping."""

    def test_build_batches_adds_provider_dependencies_for_api(self) -> None:
        rows = [
            {"spec_id": "A1001", "module_tag": "API", "module_role": "api"},
            {"spec_id": "A2001", "module_tag": "CORE", "module_role": "domain"},
            {"spec_id": "A3001", "module_tag": "DATA", "module_role": "infra"},
            {"spec_id": "A4001", "module_tag": "OBS", "module_role": "infra"},
            {"spec_id": "A5001", "module_tag": "SHARED", "module_role": "shared"},
            {"spec_id": "A6001", "module_tag": "UI", "module_role": "frontend"},
        ]
        link_plan = {
            "bindings": [
                {
                    "required_ref": {"module_tag": "API", "intent_local_id": "req_core"},
                    "provided_ref": {"module_tag": "CORE", "intent_local_id": "prov_core"},
                    "contract_id": "ctr.core",
                    "confidence": 0.9,
                    "rationale": "x",
                },
                {
                    "required_ref": {"module_tag": "API", "intent_local_id": "req_data"},
                    "provided_ref": {"module_tag": "DATA", "intent_local_id": "prov_data"},
                    "contract_id": "ctr.data",
                    "confidence": 0.9,
                    "rationale": "x",
                },
                {
                    "required_ref": {"module_tag": "API", "intent_local_id": "req_obs"},
                    "provided_ref": {"module_tag": "OBS", "intent_local_id": "prov_obs"},
                    "contract_id": "ctr.obs",
                    "confidence": 0.9,
                    "rationale": "x",
                },
                {
                    "required_ref": {"module_tag": "API", "intent_local_id": "req_shared"},
                    "provided_ref": {"module_tag": "SHARED", "intent_local_id": "prov_shared"},
                    "contract_id": "ctr.shared",
                    "confidence": 0.9,
                    "rationale": "x",
                },
                {
                    "required_ref": {"module_tag": "UI", "intent_local_id": "req_api"},
                    "provided_ref": {"module_tag": "API", "intent_local_id": "prov_api"},
                    "contract_id": "ctr.ui",
                    "confidence": 0.9,
                    "rationale": "x",
                },
            ],
            "integration_actions": [{"action_id": "INT_1", "type": "add_di_wiring", "details": {}}],
        }
        batch_plan = _build_batches(rows, link_plan, {"max_specs_per_batch": 5})
        batches = [b for b in batch_plan["batches"] if b.get("kind") != "integration"]
        by_module = {b["module_tags"][0]: b for b in batches if len(b["module_tags"]) == 1}
        api_deps = set(by_module["API"]["depends_on_batches"])
        self.assertTrue(api_deps.intersection({by_module["CORE"]["batch_id"]}))
        self.assertTrue(api_deps.intersection({by_module["DATA"]["batch_id"]}))
        self.assertTrue(api_deps.intersection({by_module["OBS"]["batch_id"]}))
        self.assertTrue(api_deps.intersection({by_module["SHARED"]["batch_id"]}))

    def test_build_batches_collapses_cyclic_modules_into_scc_cohort(self) -> None:
        rows = [
            {"spec_id": "A1001", "module_tag": "API", "module_role": "api"},
            {"spec_id": "A2001", "module_tag": "CORE", "module_role": "domain"},
        ]
        link_plan = {
            "bindings": [
                {
                    "required_ref": {"module_tag": "API", "intent_local_id": "req_core"},
                    "provided_ref": {"module_tag": "CORE", "intent_local_id": "prov_core"},
                    "contract_id": "ctr.core",
                    "confidence": 0.9,
                    "rationale": "x",
                },
                {
                    "required_ref": {"module_tag": "CORE", "intent_local_id": "req_api"},
                    "provided_ref": {"module_tag": "API", "intent_local_id": "prov_api"},
                    "contract_id": "ctr.api",
                    "confidence": 0.9,
                    "rationale": "x",
                },
            ]
        }
        batch_plan = _build_batches(rows, link_plan, {"max_specs_per_batch": 5})
        cohort = [
            b
            for b in batch_plan["batches"]
            if b.get("kind") == "module_impl" and sorted(b.get("module_tags", [])) == ["API", "CORE"]
        ]
        self.assertGreaterEqual(len(cohort), 1)

    def test_validate_batch_plan_dependencies_detects_missing_provider_path(self) -> None:
        batch_plan = {
            "batches": [
                {
                    "batch_id": "B1",
                    "kind": "module_impl",
                    "module_tags": ["API"],
                    "spec_ids": ["A1001"],
                    "depends_on_batches": [],
                },
                {
                    "batch_id": "B2",
                    "kind": "module_impl",
                    "module_tags": ["CORE"],
                    "spec_ids": ["A2001"],
                    "depends_on_batches": [],
                },
            ]
        }
        link_plan = {
            "bindings": [
                {
                    "required_ref": {"module_tag": "API", "intent_local_id": "req_core"},
                    "provided_ref": {"module_tag": "CORE", "intent_local_id": "prov_core"},
                    "contract_id": "ctr.core",
                    "confidence": 0.9,
                    "rationale": "x",
                }
            ]
        }
        result = _validate_batch_plan_dependencies(batch_plan, link_plan)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("Missing provider dependency paths" in reason for reason in result["reasons"]))

    def test_build_briefs_scopes_bindings_and_anchors_to_batch_specs(self) -> None:
        rows = [
            {"spec_id": "A1001", "module_tag": "API", "module_role": "api"},
            {"spec_id": "A1002", "module_tag": "API", "module_role": "api"},
            {"spec_id": "A2001", "module_tag": "CORE", "module_role": "domain"},
        ]
        link_plan = {
            "contracts": [
                {"contract_id": "ctr.api.1"},
                {"contract_id": "ctr.api.2"},
            ],
            "bindings": [
                {
                    "required_ref": {"module_tag": "API", "intent_local_id": "req_1"},
                    "provided_ref": {"module_tag": "CORE", "intent_local_id": "prov_1"},
                    "contract_id": "ctr.api.1",
                    "confidence": 0.9,
                    "rationale": "x",
                },
                {
                    "required_ref": {"module_tag": "API", "intent_local_id": "req_2"},
                    "provided_ref": {"module_tag": "CORE", "intent_local_id": "prov_2"},
                    "contract_id": "ctr.api.2",
                    "confidence": 0.9,
                    "rationale": "x",
                },
            ],
        }
        anchor_plans = {
            "API": {
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
                        "planned_file_path": "API/app/routes.py",
                        "spec_ids": ["A1002"],
                    },
                ],
                "required_intents": [
                    {"intent_local_id": "req_1", "spec_ids": ["A1001"]},
                    {"intent_local_id": "req_2", "spec_ids": ["A1002"]},
                ],
                "provided_intents": [],
            },
            "CORE": {
                "planned_anchors": [],
                "required_intents": [],
                "provided_intents": [
                    {"intent_local_id": "prov_1", "spec_ids": ["A2001"]},
                    {"intent_local_id": "prov_2", "spec_ids": ["A2001"]},
                ],
            },
        }
        batch_plan = _build_batches(rows, link_plan, {"max_specs_per_batch": 1})
        briefs = _build_briefs(
            rows,
            anchor_plans,
            link_plan,
            batch_plan,
            {"forbidden_paths": [], "budgets": {"max_specs_per_batch": 1}, "verification_commands": []},
        )
        api_briefs = [b for b in briefs if b.get("spec_rows") and b["spec_rows"][0]["module_tag"] == "API"]
        self.assertEqual(len(api_briefs), 2)
        first = sorted(api_briefs, key=lambda b: b["spec_rows"][0]["spec_id"])[0]
        first_spec = first["spec_rows"][0]["spec_id"]
        self.assertEqual(first_spec, "A1001")
        self.assertEqual(len(first["relevant_bindings"]), 1)
        self.assertEqual(first["relevant_bindings"][0]["contract_id"], "ctr.api.1")
        self.assertEqual(len(first["planned_anchors"]), 1)
        self.assertEqual(first["planned_anchors"][0]["spec_ids"], ["A1001"])


class ImplementDryRunTests(unittest.TestCase):
    """End-to-end dry-run tests for run_implement."""

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

    def test_run_implement_dry_run_writes_planning_artifacts(self) -> None:
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
            "prompts": {"prompt_file": "prompts/PROMPT.yaml"},
            "commands": {
                "implement": {
                    "enabled": True,
                    "prompt_name": "implement_from_specs",
                    "anchor_planner_prompt_name": "implement_anchor_planner",
                    "anchor_linker_prompt_name": "implement_anchor_linker",
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
        # Outputs go to out/agent_runs/implement/{run_id}/
        run_dir = self.tmp / "out" / "agent_runs" / "implement" / "run-impl-001"
        self.assertTrue((run_dir / "run_meta.json").exists())
        self.assertTrue((run_dir / "workset.json").exists())
        self.assertTrue((run_dir / "module_catalog.json").exists())
        self.assertTrue((run_dir / "link_plan.json").exists())
        self.assertTrue((run_dir / "batch_plan.json").exists())
        self.assertTrue((run_dir / "batch_plan_validation.json").exists())
        self.assertTrue((run_dir / "summary.json").exists())
        run_meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
        self.assertIn("disallowed_link_kinds_by_required_role", run_meta)
        self.assertIn("frontend", run_meta["disallowed_link_kinds_by_required_role"])
        self.assertIn(
            "external_api",
            run_meta["disallowed_link_kinds_by_required_role"]["frontend"],
        )

    @patch("handlers.implement.invoke_agent_with_schema_retry")
    def test_run_implement_retries_linker_for_unbound_required_intents(self, mock_invoke: Any) -> None:
        planner_output = {
            "module_tag": "CORE",
            "planned_anchors": [],
            "provided_intents": [
                {
                    "intent_local_id": "core_prov",
                    "kind": "service_interface",
                    "capability_name": "Provider",
                    "description": "x",
                    "inputs": [],
                    "outputs": [],
                    "error_modes": [],
                    "spec_ids": ["A1"],
                    "confidence": 0.95,
                }
            ],
            "required_intents": [
                {
                    "intent_local_id": "core_req",
                    "kind": "service_interface",
                    "capability_name": "Required",
                    "description": "x",
                    "inputs": [],
                    "outputs": [],
                    "error_modes": [],
                    "spec_ids": ["A1"],
                    "confidence": 0.95,
                }
            ],
        }
        linker_first = {"contracts": [], "bindings": []}
        linker_second = {
            "contracts": [
                {
                    "contract_id": "ctr.core.req.v1",
                    "kind": "service_interface",
                    "canonical_name": "core_req_provider_contract",
                    "shape": {"request": "Req", "response": "Resp"},
                    "type_locations": {"placement_root": "workspace/shared-contracts/"},
                }
            ],
            "bindings": [
                {
                    "required_ref": {"module_tag": "CORE", "intent_local_id": "core_req"},
                    "provided_ref": {"module_tag": "CORE", "intent_local_id": "core_prov"},
                    "contract_id": "ctr.core.req.v1",
                    "confidence": 0.93,
                    "rationale": "intra-module binding",
                }
            ],
        }
        mock_invoke.side_effect = [planner_output, linker_first, linker_second]

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
            "prompts": {"prompt_file": "prompts/PROMPT.yaml"},
            "commands": {
                "implement": {
                    "enabled": True,
                    "prompt_name": "implement_from_specs",
                    "anchor_planner_prompt_name": "implement_anchor_planner",
                    "anchor_linker_prompt_name": "implement_anchor_linker",
                    "linker_max_attempts": 2,
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
            run_id="run-impl-retry-001",
            project_root=str(self.tmp),
            config_path=str(self.tmp / "config.yaml"),
        )
        result = run_implement(config, ctx)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(mock_invoke.call_count, 3)

        linker_calls = [
            call
            for call in mock_invoke.call_args_list
            if call.kwargs.get("prompt_name") == "implement_anchor_linker"
        ]
        self.assertEqual(len(linker_calls), 2)
        disallowed_rules = json.loads(
            linker_calls[0].kwargs["template_vars"]["disallowed_link_kinds_by_required_role_json"]
        )
        self.assertIn("frontend", disallowed_rules)
        self.assertIn("external_api", disallowed_rules["frontend"])
        retry_context = json.loads(linker_calls[1].kwargs["template_vars"]["linker_retry_context_json"])
        self.assertEqual(retry_context["retry_reason"], "link_plan_validation_failed")
        self.assertEqual(
            retry_context["unbound_required_intents"],
            [{"module_tag": "CORE", "intent_local_id": "core_req"}],
        )
        self.assertTrue(len(retry_context["validation_violations"]) >= 1)

    @patch("handlers.implement.invoke_agent_with_schema_retry")
    def test_run_implement_requests_manual_resolution_for_unbound_required_intents(self, mock_invoke: Any) -> None:
        planner_output = {
            "module_tag": "CORE",
            "planned_anchors": [],
            "provided_intents": [],
            "required_intents": [
                {
                    "intent_local_id": "core_req",
                    "kind": "service_interface",
                    "capability_name": "Required",
                    "description": "x",
                    "inputs": [],
                    "outputs": [],
                    "error_modes": [],
                    "spec_ids": ["A1"],
                    "confidence": 0.95,
                }
            ],
        }
        linker_first = {"contracts": [], "bindings": []}
        linker_second = {
            "manual_resolution_items": [
                {
                    "item_id": "linker_manual_core_req",
                    "title": "No valid provider for CORE:core_req",
                    "question": "No provider intent is available. How should this requirement be handled?",
                    "options": [
                        {
                            "option_id": "add_provider",
                            "label": "Add provider intent",
                            "effect": "Create provider capability and rerun linker",
                        }
                    ],
                    "required": True,
                    "blocking_reason": "No valid link target exists for required intent CORE:core_req",
                }
            ]
        }
        mock_invoke.side_effect = [planner_output, linker_first, linker_second]

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
            "prompts": {"prompt_file": "prompts/PROMPT.yaml"},
            "commands": {
                "implement": {
                    "enabled": True,
                    "prompt_name": "implement_from_specs",
                    "anchor_planner_prompt_name": "implement_anchor_planner",
                    "anchor_linker_prompt_name": "implement_anchor_linker",
                    "linker_max_attempts": 2,
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
            run_id="run-impl-retry-002",
            project_root=str(self.tmp),
            config_path=str(self.tmp / "config.yaml"),
        )
        result = run_implement(config, ctx)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocking_items"], 1)
        linker_calls = [
            call
            for call in mock_invoke.call_args_list
            if call.kwargs.get("prompt_name") == "implement_anchor_linker"
        ]
        self.assertEqual(len(linker_calls), 2)
        disallowed_rules = json.loads(
            linker_calls[0].kwargs["template_vars"]["disallowed_link_kinds_by_required_role_json"]
        )
        self.assertIn("frontend", disallowed_rules)
        retry_context = json.loads(linker_calls[1].kwargs["template_vars"]["linker_retry_context_json"])
        self.assertEqual(
            retry_context["unbound_required_intents"],
            [{"module_tag": "CORE", "intent_local_id": "core_req"}],
        )
        self.assertTrue(len(retry_context["validation_violations"]) >= 1)


if __name__ == "__main__":
    unittest.main()
