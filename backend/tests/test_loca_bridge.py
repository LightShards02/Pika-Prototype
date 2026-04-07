"""Tests for core.loca_bridge."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Import agent_invoker first to avoid circular import when loca_bridge
# imports from it at module level.
from core import agent_invoker  # noqa: F401

from core.loca_bridge import (
    _UsageTrackingLLM,
    _get_local_base_url,
    _get_local_provider_sub,
    _get_local_temperature,
    _get_local_top_p,
    _map_reasoning_effort,
    build_loca_config,
    check_loca_available,
    run_loca_agent,
)


class MapReasoningEffortTests(unittest.TestCase):
    """Tests for _map_reasoning_effort."""

    def test_low(self) -> None:
        self.assertEqual(_map_reasoning_effort("low"), "low")

    def test_medium(self) -> None:
        self.assertEqual(_map_reasoning_effort("medium"), "medium")

    def test_high(self) -> None:
        self.assertEqual(_map_reasoning_effort("high"), "high")

    def test_xhigh_maps_to_high(self) -> None:
        self.assertEqual(_map_reasoning_effort("xhigh"), "high")

    def test_invalid_returns_none(self) -> None:
        self.assertIsNone(_map_reasoning_effort("ultra"))


class GetLocalProviderSubTests(unittest.TestCase):
    """Tests for _get_local_provider_sub."""

    @patch("core.loca_bridge.get_pika_config")
    def test_defaults_to_openai_codex(self, mock_pika: MagicMock) -> None:
        mock_pika.return_value = {"local": {}}
        self.assertEqual(_get_local_provider_sub({}), "openai-codex")

    @patch("core.loca_bridge.get_pika_config")
    def test_workspace_override(self, mock_pika: MagicMock) -> None:
        mock_pika.return_value = {"local": {"provider_sub": "openai-codex"}}
        config = {"agent": {"provider_sub": "openai"}}
        self.assertEqual(_get_local_provider_sub(config), "openai")

    @patch("core.loca_bridge.get_pika_config")
    def test_pika_default(self, mock_pika: MagicMock) -> None:
        mock_pika.return_value = {"local": {"provider_sub": "openai"}}
        self.assertEqual(_get_local_provider_sub({}), "openai")

    @patch("core.loca_bridge.get_pika_config")
    def test_anthropic_from_pika(self, mock_pika: MagicMock) -> None:
        mock_pika.return_value = {"local": {"provider_sub": "anthropic"}}
        self.assertEqual(_get_local_provider_sub({}), "anthropic")

    @patch("core.loca_bridge.get_pika_config")
    def test_anthropic_workspace_override(self, mock_pika: MagicMock) -> None:
        mock_pika.return_value = {"local": {"provider_sub": "openai-codex"}}
        config = {"agent": {"provider_sub": "anthropic"}}
        self.assertEqual(_get_local_provider_sub(config), "anthropic")

    @patch("core.loca_bridge.get_pika_config")
    def test_invalid_value_falls_to_default(self, mock_pika: MagicMock) -> None:
        mock_pika.return_value = {"local": {"provider_sub": "invalid"}}
        self.assertEqual(_get_local_provider_sub({}), "openai-codex")


class GetLocalTemperatureTests(unittest.TestCase):
    """Tests for _get_local_temperature."""

    @patch("core.loca_bridge.get_pika_config")
    def test_returns_none_when_not_set(self, mock_pika: MagicMock) -> None:
        mock_pika.return_value = {"local": {}}
        self.assertIsNone(_get_local_temperature({}, "map_spec_to_code"))

    @patch("core.loca_bridge.get_pika_config")
    def test_workspace_override(self, mock_pika: MagicMock) -> None:
        mock_pika.return_value = {"local": {"model": {"default": {"name": "gpt-5.3-codex", "temperature": 0.5}}}}
        config = {"agent": {"map_spec_to_code": {"temperature": 0.8}}}
        self.assertAlmostEqual(_get_local_temperature(config, "map_spec_to_code"), 0.8)

    @patch("core.lifecycle.get_pika_config")
    @patch("core.loca_bridge.get_pika_config")
    def test_pika_default(self, mock_bridge_pika: MagicMock, mock_lifecycle_pika: MagicMock) -> None:
        pika_cfg = {"local": {"model": {"default": {"name": "gpt-5.3-codex", "temperature": 0.3}}}}
        mock_bridge_pika.return_value = pika_cfg
        mock_lifecycle_pika.return_value = pika_cfg
        self.assertAlmostEqual(_get_local_temperature({}, "map_spec_to_code"), 0.3)

    @patch("core.loca_bridge.get_pika_config")
    def test_null_pika_value_returns_none(self, mock_pika: MagicMock) -> None:
        mock_pika.return_value = {"local": {"model": {"default": {"name": "gpt-5.3-codex", "temperature": None}}}}
        self.assertIsNone(_get_local_temperature({}, "map_spec_to_code"))


class GetLocalTopPTests(unittest.TestCase):
    """Tests for _get_local_top_p."""

    @patch("core.loca_bridge.get_pika_config")
    def test_returns_none_when_not_set(self, mock_pika: MagicMock) -> None:
        mock_pika.return_value = {"local": {}}
        self.assertIsNone(_get_local_top_p({}, "map_spec_to_code"))

    @patch("core.loca_bridge.get_pika_config")
    def test_workspace_override(self, mock_pika: MagicMock) -> None:
        mock_pika.return_value = {"local": {"model": {"default": {"name": "gpt-5.3-codex"}}}}
        config = {"agent": {"map_spec_to_code": {"top_p": 0.9}}}
        self.assertAlmostEqual(_get_local_top_p(config, "map_spec_to_code"), 0.9)

    @patch("core.lifecycle.get_pika_config")
    @patch("core.loca_bridge.get_pika_config")
    def test_pika_default(self, mock_bridge_pika: MagicMock, mock_lifecycle_pika: MagicMock) -> None:
        pika_cfg = {"local": {"model": {"default": {"name": "gpt-5.3-codex", "top_p": 0.7}}}}
        mock_bridge_pika.return_value = pika_cfg
        mock_lifecycle_pika.return_value = pika_cfg
        self.assertAlmostEqual(_get_local_top_p({}, "map_spec_to_code"), 0.7)


class GetLocalBaseUrlTests(unittest.TestCase):
    """Tests for _get_local_base_url."""

    @patch("core.lifecycle._get_effective_local_agent_profile")
    def test_returns_none_when_not_set(self, mock_profile: MagicMock) -> None:
        mock_profile.return_value = {"name": "gpt-5.3-codex"}
        self.assertIsNone(_get_local_base_url({}, "map_spec_to_code"))

    @patch("core.lifecycle._get_effective_local_agent_profile")
    def test_returns_none_when_null(self, mock_profile: MagicMock) -> None:
        mock_profile.return_value = {"name": "gpt-5.3-codex", "base_url": None}
        self.assertIsNone(_get_local_base_url({}, "map_spec_to_code"))

    @patch("core.lifecycle._get_effective_local_agent_profile")
    def test_returns_url_when_set(self, mock_profile: MagicMock) -> None:
        mock_profile.return_value = {"name": "gpt-5.3-codex", "base_url": "https://api.example.com/v1"}
        self.assertEqual(_get_local_base_url({}, "map_spec_to_code"), "https://api.example.com/v1")

    @patch("core.lifecycle._get_effective_local_agent_profile")
    def test_whitespace_stripped(self, mock_profile: MagicMock) -> None:
        mock_profile.return_value = {"name": "gpt-5.3-codex", "base_url": "  https://api.example.com/v1  "}
        self.assertEqual(_get_local_base_url({}, "map_spec_to_code"), "https://api.example.com/v1")

    @patch("core.lifecycle._get_effective_local_agent_profile")
    def test_empty_string_returns_none(self, mock_profile: MagicMock) -> None:
        mock_profile.return_value = {"name": "gpt-5.3-codex", "base_url": ""}
        self.assertIsNone(_get_local_base_url({}, "map_spec_to_code"))

    @patch("core.lifecycle.get_pika_config")
    def test_base_url_from_pika_model_profiles(self, mock_pika: MagicMock) -> None:
        """base_url in pika.yaml local.model must survive profile normalization."""
        mock_pika.return_value = {
            "local": {
                "model": {
                    "default": {
                        "name": "kimi-k2.5",
                        "base_url": "https://api.moonshot.ai/v1",
                    },
                    "map_spec_to_code": {"name": "gpt-5.3-codex"},
                }
            }
        }
        config = {"agent": {}}
        self.assertEqual(
            _get_local_base_url(config, "map_spec_to_code"),
            "https://api.moonshot.ai/v1",
        )

    @patch("core.lifecycle.get_pika_config")
    def test_base_url_workspace_overrides_pika(self, mock_pika: MagicMock) -> None:
        mock_pika.return_value = {
            "local": {
                "model": {
                    "default": {
                        "name": "kimi-k2.5",
                        "base_url": "https://api.moonshot.ai/v1",
                    },
                }
            }
        }
        config = {
            "agent": {
                "default": {"base_url": "https://api.other.example/v1"},
            }
        }
        self.assertEqual(
            _get_local_base_url(config, "map_spec_to_code"),
            "https://api.other.example/v1",
        )


class BuildLocaConfigTests(unittest.TestCase):
    """Tests for build_loca_config."""

    @patch("core.loca_bridge.get_pika_config")
    @patch("core.lifecycle.get_pika_config")
    def test_defaults(self, mock_lifecycle_pika: MagicMock, mock_bridge_pika: MagicMock) -> None:
        pika_cfg = {
            "local": {
                "provider_sub": "openai-codex",
                "model": {"default": {"name": "gpt-5.3-codex", "reasoning_effort": "medium"}},
                "exec_timeout_sec": 600,
            },
        }
        mock_lifecycle_pika.return_value = pika_cfg
        mock_bridge_pika.return_value = pika_cfg

        config = {"agent": {}}
        workspace = Path("/tmp/test-workspace")

        loca_cfg = build_loca_config(config, "map_spec_to_code", workspace)

        self.assertEqual(loca_cfg.model.provider, "openai-codex")
        self.assertEqual(loca_cfg.model.name, "gpt-5.3-codex")
        self.assertEqual(loca_cfg.model.reasoning_effort, "medium")
        self.assertIsNone(loca_cfg.model.temperature)
        self.assertIsNone(loca_cfg.model.top_p)
        self.assertIsNone(loca_cfg.model.base_url)
        self.assertEqual(loca_cfg.agent.max_schema_retries, 0)
        self.assertIn("test-workspace", loca_cfg.sandbox.working_dir)

    @patch("core.loca_bridge.get_pika_config")
    @patch("core.lifecycle.get_pika_config")
    def test_temperature_top_p_passthrough(self, mock_lifecycle_pika: MagicMock, mock_bridge_pika: MagicMock) -> None:
        pika_cfg = {
            "local": {
                "provider_sub": "openai",
                "model": {"default": {"name": "gpt-4o", "reasoning_effort": "medium"}},
                "exec_timeout_sec": 300,
            },
        }
        mock_lifecycle_pika.return_value = pika_cfg
        mock_bridge_pika.return_value = pika_cfg

        config = {
            "agent": {
                "provider_sub": "openai",
                "map_spec_to_code": {
                    "temperature": 0.5,
                    "top_p": 0.9,
                },
            },
        }
        workspace = Path("/tmp/test-workspace")

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            loca_cfg = build_loca_config(config, "map_spec_to_code", workspace)

        self.assertEqual(loca_cfg.model.provider, "openai")
        self.assertAlmostEqual(loca_cfg.model.temperature, 0.5)
        self.assertAlmostEqual(loca_cfg.model.top_p, 0.9)

    @patch("core.loca_bridge.get_pika_config")
    @patch("core.lifecycle.get_pika_config")
    def test_openai_base_url_from_pika_model_default(
        self, mock_lifecycle_pika: MagicMock, mock_bridge_pika: MagicMock
    ) -> None:
        """Moonshot-style base_url in pika local.model.default reaches Loca config."""
        pika_cfg = {
            "local": {
                "provider_sub": "openai",
                "model": {
                    "default": {
                        "name": "kimi-k2.5",
                        "base_url": "https://api.moonshot.ai/v1",
                    },
                    "map_spec_to_code": {"name": "kimi-k2.5"},
                },
                "exec_timeout_sec": 600,
            },
        }
        mock_lifecycle_pika.return_value = pika_cfg
        mock_bridge_pika.return_value = pika_cfg

        config = {"agent": {"provider_sub": "openai"}}
        workspace = Path("/tmp/test-workspace")

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            loca_cfg = build_loca_config(config, "map_spec_to_code", workspace)

        self.assertEqual(loca_cfg.model.provider, "openai")
        self.assertEqual(loca_cfg.model.base_url, "https://api.moonshot.ai/v1")

    @patch("core.loca_bridge.get_pika_config")
    @patch("core.lifecycle.get_pika_config")
    def test_anthropic_api_key_and_base_url(
        self, mock_lifecycle_pika: MagicMock, mock_bridge_pika: MagicMock
    ) -> None:
        """Anthropic sub-provider resolves ANTHROPIC_API_KEY and optional base_url."""
        pika_cfg = {
            "local": {
                "provider_sub": "anthropic",
                "model": {
                    "default": {
                        "name": "claude-sonnet-4-6",
                        "base_url": "https://proxy.example/v1",
                    },
                },
                "exec_timeout_sec": 600,
            },
        }
        mock_lifecycle_pika.return_value = pika_cfg
        mock_bridge_pika.return_value = pika_cfg

        config = {"agent": {"provider_sub": "anthropic"}}
        workspace = Path("/tmp/test-workspace")

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            loca_cfg = build_loca_config(config, "map_spec_to_code", workspace)

        self.assertEqual(loca_cfg.model.provider, "anthropic")
        self.assertEqual(loca_cfg.model.api_key, "sk-ant-test")
        self.assertEqual(loca_cfg.model.base_url, "https://proxy.example/v1")

    @patch("core.loca_bridge.get_pika_config")
    @patch("core.lifecycle.get_pika_config")
    def test_openai_api_key_from_moonshot_env_when_openai_unset(
        self, mock_lifecycle_pika: MagicMock, mock_bridge_pika: MagicMock
    ) -> None:
        """Kimi docs use MOONSHOT_API_KEY; Loca ignores it when Pika passes ''."""
        pika_cfg = {
            "local": {
                "provider_sub": "openai",
                "model": {"default": {"name": "kimi-k2.5", "reasoning_effort": "medium"}},
                "exec_timeout_sec": 600,
            },
        }
        mock_lifecycle_pika.return_value = pika_cfg
        mock_bridge_pika.return_value = pika_cfg
        env = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "MOONSHOT_API_KEY")}
        with patch.dict(os.environ, env, clear=True):
            with patch.dict(os.environ, {"MOONSHOT_API_KEY": "sk-ms-from-moonshot"}):
                loca_cfg = build_loca_config(
                    {"agent": {"provider_sub": "openai"}},
                    "map_spec_to_code",
                    Path("/tmp/test-workspace"),
                )
        self.assertEqual(loca_cfg.model.api_key, "sk-ms-from-moonshot")

    @patch("core.loca_bridge._get_local_base_url")
    @patch("core.loca_bridge.get_pika_config")
    @patch("core.lifecycle.get_pika_config")
    def test_base_url_passthrough(self, mock_lifecycle_pika: MagicMock, mock_bridge_pika: MagicMock, mock_base_url: MagicMock) -> None:
        pika_cfg = {
            "local": {
                "provider_sub": "openai",
                "model": {"default": {"name": "gpt-4o", "reasoning_effort": "medium"}},
                "exec_timeout_sec": 300,
            },
        }
        mock_lifecycle_pika.return_value = pika_cfg
        mock_bridge_pika.return_value = pika_cfg
        mock_base_url.return_value = "https://custom-api.example.com/v1"

        config = {
            "agent": {
                "provider_sub": "openai",
                "map_spec_to_code": {
                    "base_url": "https://custom-api.example.com/v1",
                },
            },
        }
        workspace = Path("/tmp/test-workspace")

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            loca_cfg = build_loca_config(config, "map_spec_to_code", workspace)

        self.assertEqual(loca_cfg.model.provider, "openai")
        self.assertEqual(loca_cfg.model.base_url, "https://custom-api.example.com/v1")

    @patch("core.loca_bridge.get_pika_config")
    @patch("core.lifecycle.get_pika_config")
    def test_null_reasoning_effort_passes_through_temperature_top_p(
        self, mock_lifecycle_pika: MagicMock, mock_bridge_pika: MagicMock
    ) -> None:
        """Explicit null reasoning_effort yields None for Loca so sampling params apply."""
        pika_cfg = {
            "local": {
                "provider_sub": "openai-codex",
                "model": {
                    "default": {"name": "gpt-5.3-codex", "reasoning_effort": "medium"},
                    "map_spec_to_code": {
                        "reasoning_effort": None,
                        "temperature": 0.4,
                        "top_p": 0.88,
                    },
                },
                "exec_timeout_sec": 600,
            },
        }
        mock_lifecycle_pika.return_value = pika_cfg
        mock_bridge_pika.return_value = pika_cfg

        loca_cfg = build_loca_config({}, "map_spec_to_code", Path("/tmp/ws"))
        self.assertIsNone(loca_cfg.model.reasoning_effort)
        self.assertAlmostEqual(loca_cfg.model.temperature, 0.4)
        self.assertAlmostEqual(loca_cfg.model.top_p, 0.88)

    @patch("core.loca_bridge.get_pika_config")
    @patch("core.lifecycle.get_pika_config")
    def test_xhigh_reasoning_maps_to_high(self, mock_lifecycle_pika: MagicMock, mock_bridge_pika: MagicMock) -> None:
        pika_cfg = {
            "local": {
                "model": {"default": {"name": "gpt-5.3-codex", "reasoning_effort": "xhigh"}},
                "exec_timeout_sec": 600,
            },
        }
        mock_lifecycle_pika.return_value = pika_cfg
        mock_bridge_pika.return_value = pika_cfg

        loca_cfg = build_loca_config({}, "map_spec_to_code", Path("/tmp/ws"))
        self.assertEqual(loca_cfg.model.reasoning_effort, "high")


class CheckLocaAvailableTests(unittest.TestCase):
    """Tests for check_loca_available."""

    def test_openai_with_key(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            self.assertTrue(check_loca_available("openai"))

    def test_openai_without_key(self) -> None:
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("OPENAI_API_KEY", "MOONSHOT_API_KEY")
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertFalse(check_loca_available("openai"))

    def test_openai_moonshot_env_only(self) -> None:
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("OPENAI_API_KEY", "MOONSHOT_API_KEY")
        }
        with patch.dict(os.environ, env, clear=True):
            with patch.dict(os.environ, {"MOONSHOT_API_KEY": "sk-ms"}):
                self.assertTrue(check_loca_available("openai"))

    def test_openai_prefers_openai_key_over_moonshot(self) -> None:
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("OPENAI_API_KEY", "MOONSHOT_API_KEY")
        }
        with patch.dict(os.environ, env, clear=True):
            with patch.dict(
                os.environ,
                {"OPENAI_API_KEY": "sk-openai", "MOONSHOT_API_KEY": "sk-ms"},
            ):
                self.assertTrue(check_loca_available("openai"))

    def test_anthropic_with_key(self) -> None:
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            self.assertTrue(check_loca_available("anthropic"))

    def test_anthropic_without_key(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            self.assertFalse(check_loca_available("anthropic"))

    @patch("loca.auth.get_valid_token", return_value={"access": "tok", "accountId": "acc"})
    def test_codex_with_token(self, _mock: MagicMock) -> None:
        self.assertTrue(check_loca_available("openai-codex"))

    @patch("loca.auth.get_valid_token", return_value=None)
    def test_codex_without_token(self, _mock: MagicMock) -> None:
        self.assertFalse(check_loca_available("openai-codex"))

    def test_unknown_provider(self) -> None:
        self.assertFalse(check_loca_available("unknown"))


class UsageTrackingLLMTests(unittest.TestCase):
    """Tests for _UsageTrackingLLM."""

    def test_accumulates_chat_usage(self) -> None:
        from loca.llm.base import LLMResponse, TextBlock

        mock_inner = MagicMock()
        mock_inner.chat.return_value = LLMResponse(
            content=[TextBlock(text="hi")],
            stop_reason="end_turn",
            input_tokens=100,
            output_tokens=50,
        )

        tracked = _UsageTrackingLLM(mock_inner)
        tracked.chat([], [], "sys")
        tracked.chat([], [], "sys")

        self.assertEqual(tracked.total_input_tokens, 200)
        self.assertEqual(tracked.total_output_tokens, 100)

    def test_accumulates_stream_usage(self) -> None:
        from loca.llm.base import LLMResponse, StreamEnd, TextDelta

        mock_inner = MagicMock()
        mock_inner.stream_chat.return_value = iter([
            TextDelta(text="hello"),
            StreamEnd(response=LLMResponse(
                content=[], stop_reason="end_turn",
                input_tokens=80, output_tokens=30,
            )),
        ])

        tracked = _UsageTrackingLLM(mock_inner)
        events = list(tracked.stream_chat([], [], "sys"))

        self.assertEqual(len(events), 2)
        self.assertEqual(tracked.total_input_tokens, 80)
        self.assertEqual(tracked.total_output_tokens, 30)


class RunLocaAgentTests(unittest.TestCase):
    """Tests for run_loca_agent."""

    @patch("core.loca_bridge.build_default_registry")
    @patch("core.loca_bridge.get_llm_client")
    def test_success_with_json_output(self, mock_get_client: MagicMock, mock_registry: MagicMock) -> None:
        from loca.agent import AgentResult
        from loca.config import LocaConfig
        from loca.llm.base import LLMResponse, TextBlock

        mock_llm = MagicMock()
        mock_get_client.return_value = mock_llm
        mock_registry.return_value = MagicMock()

        mock_result = AgentResult(
            messages=[],
            stop_reason="end_turn",
            turns=1,
            json_output={"status": "ok", "items": []},
        )

        with patch("core.loca_bridge.Agent") as MockAgent:
            MockAgent.return_value.run.return_value = mock_result
            loca_cfg = LocaConfig()

            result, usage = run_loca_agent(
                system_prompt="sys",
                user_prompt="user",
                loca_config=loca_cfg,
                stream_output=False,
            )

        self.assertEqual(result, {"status": "ok", "items": []})

    @patch("core.loca_bridge.build_default_registry")
    @patch("core.loca_bridge.get_llm_client")
    def test_error_raises_invocation_error(self, mock_get_client: MagicMock, mock_registry: MagicMock) -> None:
        from core.lifecycle import AgentInvocationError
        from loca.agent import AgentResult
        from loca.config import LocaConfig

        mock_get_client.return_value = MagicMock()
        mock_registry.return_value = MagicMock()

        mock_result = AgentResult(
            messages=[],
            stop_reason="error",
            turns=1,
            error="API timeout",
        )

        with patch("core.loca_bridge.Agent") as MockAgent:
            MockAgent.return_value.run.return_value = mock_result
            loca_cfg = LocaConfig()

            with self.assertRaises(AgentInvocationError) as ctx:
                run_loca_agent(
                    system_prompt="sys",
                    user_prompt="user",
                    loca_config=loca_cfg,
                    stream_output=False,
                )

            self.assertIn("API timeout", str(ctx.exception))

    @patch("core.loca_bridge.build_default_registry")
    @patch("core.loca_bridge.get_llm_client")
    def test_max_turns_raises_invocation_error(self, mock_get_client: MagicMock, mock_registry: MagicMock) -> None:
        from core.lifecycle import AgentInvocationError
        from loca.agent import AgentResult
        from loca.config import LocaConfig

        mock_get_client.return_value = MagicMock()
        mock_registry.return_value = MagicMock()

        mock_result = AgentResult(
            messages=[],
            stop_reason="max_turns",
            turns=30,
        )

        with patch("core.loca_bridge.Agent") as MockAgent:
            MockAgent.return_value.run.return_value = mock_result
            loca_cfg = LocaConfig()

            with self.assertRaises(AgentInvocationError) as ctx:
                run_loca_agent(
                    system_prompt="sys",
                    user_prompt="user",
                    loca_config=loca_cfg,
                    stream_output=False,
                )

            self.assertIn("max turns", str(ctx.exception))

    @patch("core.loca_bridge.build_default_registry")
    @patch("core.loca_bridge.get_llm_client")
    def test_schema_error_raises_value_error(self, mock_get_client: MagicMock, mock_registry: MagicMock) -> None:
        from loca.agent import AgentResult
        from loca.config import LocaConfig

        mock_get_client.return_value = MagicMock()
        mock_registry.return_value = MagicMock()

        mock_result = AgentResult(
            messages=[],
            stop_reason="schema_error",
            turns=2,
            error="missing required field 'items'",
        )

        with patch("core.loca_bridge.Agent") as MockAgent:
            MockAgent.return_value.run.return_value = mock_result
            loca_cfg = LocaConfig()

            with self.assertRaises(ValueError):
                run_loca_agent(
                    system_prompt="sys",
                    user_prompt="user",
                    loca_config=loca_cfg,
                    stream_output=False,
                )

    @patch("core.loca_bridge.build_default_registry")
    @patch("core.loca_bridge.get_llm_client")
    def test_schema_error_recovers_when_json_extractable(self, mock_get_client: MagicMock, mock_registry: MagicMock) -> None:
        """When Loca schema_error fires but JSON is in messages, return output for PIKA filter."""
        from loca.agent import AgentResult
        from loca.config import LocaConfig

        mock_get_client.return_value = MagicMock()
        mock_registry.return_value = MagicMock()

        # Agent returned valid JSON with extra properties that Loca's strict schema rejected
        mock_result = AgentResult(
            messages=[
                {"role": "assistant", "content": [
                    {"type": "text", "text": '{"manual_resolution_items": [], "extra_field": true}'}
                ]}
            ],
            stop_reason="schema_error",
            turns=1,
            error="Additional properties are not allowed ('extra_field' was unexpected)",
        )

        with patch("core.loca_bridge.Agent") as MockAgent:
            MockAgent.return_value.run.return_value = mock_result
            loca_cfg = LocaConfig()

            output, usage = run_loca_agent(
                system_prompt="sys",
                user_prompt="user",
                loca_config=loca_cfg,
                stream_output=False,
            )
            self.assertEqual(output, {"manual_resolution_items": [], "extra_field": True})

    @patch("core.loca_bridge.build_default_registry")
    @patch("core.loca_bridge.get_llm_client")
    def test_schema_error_recovers_from_json_output(self, mock_get_client: MagicMock, mock_registry: MagicMock) -> None:
        """When Loca schema_error fires but json_output is populated, return it."""
        from loca.agent import AgentResult
        from loca.config import LocaConfig

        mock_get_client.return_value = MagicMock()
        mock_registry.return_value = MagicMock()

        mock_result = AgentResult(
            messages=[],
            stop_reason="schema_error",
            turns=1,
            error="Additional properties are not allowed",
            json_output={"manual_resolution_items": [], "notes": "extra"},
        )

        with patch("core.loca_bridge.Agent") as MockAgent:
            MockAgent.return_value.run.return_value = mock_result
            loca_cfg = LocaConfig()

            output, usage = run_loca_agent(
                system_prompt="sys",
                user_prompt="user",
                loca_config=loca_cfg,
                stream_output=False,
            )
            self.assertEqual(output, {"manual_resolution_items": [], "notes": "extra"})

    @patch("core.loca_bridge.build_default_registry")
    @patch("core.loca_bridge.get_llm_client")
    def test_fallback_text_extraction(self, mock_get_client: MagicMock, mock_registry: MagicMock) -> None:
        from loca.agent import AgentResult
        from loca.config import LocaConfig

        mock_get_client.return_value = MagicMock()
        mock_registry.return_value = MagicMock()

        mock_result = AgentResult(
            messages=[
                {"role": "user", "content": "do stuff"},
                {"role": "assistant", "content": [
                    {"type": "text", "text": '{"result": "done"}'},
                ]},
            ],
            stop_reason="end_turn",
            turns=1,
            json_output=None,
        )

        with patch("core.loca_bridge.Agent") as MockAgent:
            MockAgent.return_value.run.return_value = mock_result
            loca_cfg = LocaConfig()

            result, _ = run_loca_agent(
                system_prompt="sys",
                user_prompt="user",
                loca_config=loca_cfg,
                stream_output=False,
            )

        self.assertEqual(result, {"result": "done"})


if __name__ == "__main__":
    unittest.main()
