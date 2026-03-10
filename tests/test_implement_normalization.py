"""Tests for deterministic implement normalization helpers."""

from __future__ import annotations

import unittest

from core.implement_normalization import (
    build_normalized_intent_catalog,
    enforce_leaf_dependency_policy,
    normalize_anchor_plan_kinds,
    normalize_for_linking,
    score_intent_candidates,
)


class ImplementNormalizationTests(unittest.TestCase):
    """Unit tests for kind normalization, leaf policy, and scoring artifacts."""

    def setUp(self) -> None:
        self.module_catalog = {
            "modules": [
                {"module_tag": "UI", "module_role": "frontend"},
                {"module_tag": "API", "module_role": "api"},
                {"module_tag": "CORE", "module_role": "domain"},
                {"module_tag": "DATA", "module_role": "infra"},
            ]
        }

    def test_normalize_anchor_plan_kinds_rewrites_frontend_internal_api(self) -> None:
        anchor_plans = {
            "UI": {
                "provided_intents": [],
                "required_intents": [
                    {
                        "intent_local_id": "req_post_nutrition_calculate",
                        "kind": "external_api",
                        "capability_name": "post_api_v1_nutrition_calculate",
                        "description": "internal endpoint",
                        "inputs": [
                            {
                                "name": "request",
                                "type_name": "POST /api/v1/nutrition/calculate",
                            }
                        ],
                        "outputs": [],
                        "error_modes": [],
                        "spec_ids": ["A1005"],
                        "confidence": 0.95,
                    }
                ],
            }
        }
        normalized, events = normalize_anchor_plan_kinds(anchor_plans, self.module_catalog)
        self.assertEqual(
            normalized["UI"]["required_intents"][0]["kind"],
            "api_endpoint",
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "kind_rewrite")

    def test_normalize_anchor_plan_kinds_preserves_true_external_api(self) -> None:
        anchor_plans = {
            "UI": {
                "provided_intents": [],
                "required_intents": [
                    {
                        "intent_local_id": "req_stripe",
                        "kind": "external_api",
                        "capability_name": "stripe_payment_intent_create",
                        "description": "third-party endpoint",
                        "inputs": [{"name": "request", "type_name": "StripeIntentRequest"}],
                        "outputs": [],
                        "error_modes": [],
                        "spec_ids": ["A2001"],
                        "confidence": 0.8,
                    }
                ],
            }
        }
        normalized, events = normalize_anchor_plan_kinds(anchor_plans, self.module_catalog)
        self.assertEqual(
            normalized["UI"]["required_intents"][0]["kind"],
            "external_api",
        )
        self.assertEqual(events, [])

    def test_enforce_leaf_dependency_policy_moves_required_intents(self) -> None:
        anchor_plans = {
            "DATA": {
                "provided_intents": [],
                "required_intents": [
                    {
                        "intent_local_id": "DATA_REQ_01",
                        "kind": "external_api",
                        "capability_name": "provider_call",
                        "description": "provider",
                        "inputs": [],
                        "outputs": [],
                        "error_modes": [],
                        "spec_ids": ["A1029"],
                        "confidence": 0.7,
                    }
                ],
            }
        }
        normalized, events = enforce_leaf_dependency_policy(
            anchor_plans,
            self.module_catalog,
            leaf_dependency_roles={"infra"},
            track_external_dependencies=True,
        )
        self.assertEqual(normalized["DATA"]["required_intents"], [])
        deps = normalized["DATA"].get("declared_external_dependencies", [])
        self.assertEqual(len(deps), 1)
        self.assertEqual(deps[0]["source_intent_local_id"], "DATA_REQ_01")
        self.assertEqual(events[0]["event_type"], "leaf_required_intents_auto_dropped")

    def test_score_intent_candidates_marks_adapter_for_type_mismatch(self) -> None:
        required_intent = {
            "intent_local_id": "req_core_calculation_service",
            "kind": "service_interface",
            "capability_name": "core calculation service invocation",
            "description": "calculate calories and macros",
            "inputs": [{"name": "canonical_nutrition_input", "type_name": "CanonicalNutritionInput"}],
            "outputs": [{"name": "calculation_result", "type_name": "NutritionCalculationResult"}],
            "error_modes": ["domain_validation_exception"],
            "spec_ids": ["A1015", "A1016"],
            "confidence": 0.9,
        }
        provided_intent = {
            "intent_local_id": "CORE_INTENT_NUTRITION_CALCULATION",
            "kind": "service_interface",
            "capability_name": "nutrition_calculation_pipeline",
            "description": "deterministic nutrition domain computation",
            "inputs": [
                {"name": "profile", "type_name": "NutritionProfile"},
                {"name": "macro_preset", "type_name": "MacroPreset"},
            ],
            "outputs": [{"name": "calculation_result", "type_name": "NutritionCalculationResult"}],
            "error_modes": ["profile_validation_failed"],
            "spec_ids": ["A1021"],
            "confidence": 0.95,
        }
        score = score_intent_candidates(required_intent, provided_intent)
        self.assertTrue(score["adapter_needed"])
        self.assertGreaterEqual(score["score"], 0.0)
        self.assertLessEqual(score["score"], 1.0)

    def test_build_normalized_intent_catalog_emits_auto_bind_candidate(self) -> None:
        anchor_plans = {
            "API": {
                "provided_intents": [],
                "required_intents": [
                    {
                        "intent_local_id": "API_REQ_1",
                        "kind": "service_interface",
                        "capability_name": "ComputeNutrition",
                        "description": "Compute nutrition result",
                        "inputs": [{"name": "profile", "type_name": "NutritionProfile"}],
                        "outputs": [{"name": "result", "type_name": "NutritionResult"}],
                        "error_modes": ["ValidationError"],
                        "spec_ids": ["SPEC-API-001"],
                        "confidence": 0.9,
                    }
                ],
            },
            "CORE": {
                "provided_intents": [
                    {
                        "intent_local_id": "CORE_PROV_1",
                        "kind": "service_interface",
                        "capability_name": "ComputeNutrition",
                        "description": "Compute nutrition result",
                        "inputs": [{"name": "profile", "type_name": "NutritionProfile"}],
                        "outputs": [{"name": "result", "type_name": "NutritionResult"}],
                        "error_modes": ["ValidationError"],
                        "spec_ids": ["SPEC-API-001"],
                        "confidence": 0.95,
                    }
                ],
                "required_intents": [],
            },
        }
        catalog = build_normalized_intent_catalog(
            anchor_plans,
            self.module_catalog,
            min_auto_bind_score=0.7,
            tie_margin=0.08,
        )
        rankings = catalog["required_to_provided_rankings"]
        self.assertEqual(len(rankings), 1)
        self.assertIsNotNone(rankings[0]["auto_bind_candidate"])
        self.assertEqual(
            rankings[0]["auto_bind_candidate"]["provided_ref"]["intent_local_id"],
            "CORE_PROV_1",
        )

    def test_normalize_for_linking_combines_kind_and_leaf_rules(self) -> None:
        anchor_plans = {
            "UI": {
                "provided_intents": [],
                "required_intents": [
                    {
                        "intent_local_id": "req_post_nutrition_calculate",
                        "kind": "external_api",
                        "capability_name": "post_api_v1_nutrition_calculate",
                        "description": "internal endpoint",
                        "inputs": [
                            {"name": "request", "type_name": "POST /api/v1/nutrition/calculate"}
                        ],
                        "outputs": [],
                        "error_modes": [],
                        "spec_ids": ["A1005"],
                        "confidence": 0.95,
                    }
                ],
            },
            "DATA": {
                "provided_intents": [],
                "required_intents": [
                    {
                        "intent_local_id": "DATA_REQ_01",
                        "kind": "external_api",
                        "capability_name": "provider_call",
                        "description": "provider",
                        "inputs": [],
                        "outputs": [],
                        "error_modes": [],
                        "spec_ids": ["A1029"],
                        "confidence": 0.7,
                    }
                ],
            },
        }
        normalized, report, catalog = normalize_for_linking(
            anchor_plans,
            self.module_catalog,
            leaf_dependency_roles={"infra"},
            track_external_dependencies=True,
            min_auto_bind_score=0.7,
            tie_margin=0.08,
        )
        self.assertEqual(normalized["UI"]["required_intents"][0]["kind"], "api_endpoint")
        self.assertEqual(normalized["DATA"]["required_intents"], [])
        self.assertTrue(report["counts"]["kind_rewrites"] >= 1)
        self.assertIn("required_to_provided_rankings", catalog)

    def test_score_intent_candidates_prefers_dependency_target_module(self) -> None:
        required_intent = {
            "intent_local_id": "dep.data.food_provider_adapter",
            "kind": "service_interface",
            "capability_name": "DATA food provider adapter",
            "description": "provider adapter boundary",
            "inputs": [{"name": "provider_request", "type_name": "object"}],
            "outputs": [{"name": "provider_response", "type_name": "object"}],
            "error_modes": ["provider_unavailable_exception"],
            "spec_ids": ["A1010", "A1017"],
            "confidence": 0.95,
        }
        matching_provider = {
            "intent_local_id": "data_food_search",
            "kind": "service_interface",
            "capability_name": "DATA food search workflow",
            "description": "provider search and mapping",
            "inputs": [{"name": "normalized_query", "type_name": "NormalizedFoodSearchQuery"}],
            "outputs": [{"name": "food_items", "type_name": "FoodItemDTO[]"}],
            "error_modes": ["provider_error_final"],
            "spec_ids": ["A1030"],
            "confidence": 0.95,
        }
        same_module_overlap_provider = {
            "intent_local_id": "api.startup_registry",
            "kind": "service_interface",
            "capability_name": "startup dependency registry handshake",
            "description": "checks dependency callability and startup state",
            "inputs": [{"name": "dependency_registry", "type_name": "object"}],
            "outputs": [{"name": "startup_component_state", "type_name": "object"}],
            "error_modes": ["degraded_startup_component_state"],
            "spec_ids": ["A1010"],
            "confidence": 0.98,
        }
        good = score_intent_candidates(
            required_intent,
            matching_provider,
            required_module_tag="API",
            provided_module_tag="DATA",
        )
        bad = score_intent_candidates(
            required_intent,
            same_module_overlap_provider,
            required_module_tag="API",
            provided_module_tag="API",
        )
        self.assertGreater(good["score"], bad["score"])
        self.assertEqual(good["score_breakdown"]["module_affinity_similarity"], 1.0)
        self.assertGreater(bad["score_breakdown"]["module_affinity_penalty"], 0.0)

    def test_build_normalized_intent_catalog_avoids_spec_overlap_misranking(self) -> None:
        anchor_plans = {
            "API": {
                "provided_intents": [
                    {
                        "intent_local_id": "api.startup_registry",
                        "kind": "service_interface",
                        "capability_name": "startup dependency registry handshake",
                        "description": "checks dependency callability and startup state",
                        "inputs": [{"name": "dependency_registry", "type_name": "object"}],
                        "outputs": [{"name": "startup_component_state", "type_name": "object"}],
                        "error_modes": ["degraded_startup_component_state"],
                        "spec_ids": ["A1010"],
                        "confidence": 0.98,
                    }
                ],
                "required_intents": [
                    {
                        "intent_local_id": "dep.core.calculation_service",
                        "kind": "service_interface",
                        "capability_name": "CORE nutrition calculation service",
                        "description": "calorie and macro computation",
                        "inputs": [{"name": "normalized_nutrition_input", "type_name": "object"}],
                        "outputs": [{"name": "calculation_result", "type_name": "object"}],
                        "error_modes": ["domain_validation_exception"],
                        "spec_ids": ["A1010", "A1015", "A1016"],
                        "confidence": 0.98,
                    }
                ],
            },
            "CORE": {
                "provided_intents": [
                    {
                        "intent_local_id": "core.nutrition_calculation_chain",
                        "kind": "service_interface",
                        "capability_name": "Compute Daily Nutrition Targets",
                        "description": "deterministic nutrition computation",
                        "inputs": [{"name": "validated_profile", "type_name": "ValidatedNutritionProfile"}],
                        "outputs": [{"name": "nutrition_result", "type_name": "NutritionCalculationResult"}],
                        "error_modes": ["unsupported_activity_level"],
                        "spec_ids": ["A1022"],
                        "confidence": 0.96,
                    }
                ],
                "required_intents": [],
            },
        }
        catalog = build_normalized_intent_catalog(
            anchor_plans,
            self.module_catalog,
            min_auto_bind_score=0.7,
            tie_margin=0.08,
        )
        ranking = catalog["required_to_provided_rankings"][0]
        top = ranking["candidates"][0]["provided_ref"]["intent_local_id"]
        self.assertEqual(top, "core.nutrition_calculation_chain")
        self.assertIsNotNone(ranking["auto_bind_candidate"])


if __name__ == "__main__":
    unittest.main()
