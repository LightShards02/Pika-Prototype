"""Tests for core.loca_bridge."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.loca_bridge import (
    _UsageTrackingLLM,
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
        config = {"agent": {"local_provider": "openai"}}
        self.assertEqual(_get_local_provider_sub(config), "openai")

    @patch("core.loca_bridge.get_pika_config")
    def test_pika_default(self, mock_pika: MagicMock) -> None:
        mock_pika.return_value = {"local": {"provider_sub": "openai"}}
        self.assertEqual(_get_local_provider_sub({}), "openai")

    @patch("core.loca_bridge.get_pika_config")
    def test_invalid_value_falls_to_default(self, mock_pika: MagicMock) -> None:
        mock_pika.return_value = {"local": {"provider_sub": "invalid"}}
        self.assertEqual(_get_local_provider_sub({}), "openai-codex")


class GetLocalTemperatureTests(unittest.TestCase):
    """Tests for _get_local_temperature."""

    @patch("core.loca_bridge.get_pika_config")
    def test_returns_none_when_not_set(self, mock_pika: MagicMock) -> None:
        mock_pika.return_value = {"local": {}}
        self.assertIsNone(_get_local_temperature({}))

    @patch("core.loca_bridge.get_pika_config")
    def test_workspace_override(self, mock_pika: MagicMock) -> None:
        mock_pika.return_value = {"local": {"temperature": 0.5}}
        config = {"agent": {"local_temperature": 0.8}}
        self.assertAlmostEqual(_get_local_temperature(config), 0.8)

    @patch("core.loca_bridge.get_pika_config")
    def test_pika_default(self, mock_pika: MagicMock) -> None:
        mock_pika.return_value = {"local": {"temperature": 0.3}}
        self.assertAlmostEqual(_get_local_temperature({}), 0.3)

    @patch("core.loca_bridge.get_pika_config")
    def test_null_pika_value_returns_none(self, mock_pika: MagicMock) -> None:
        mock_pika.return_value = {"local": {"temperature": None}}
        self.assertIsNone(_get_local_temperature({}))


class GetLocalTopPTests(unittest.TestCase):
    """Tests for _get_local_top_p."""

    @patch("core.loca_bridge.get_pika_config")
    def test_returns_none_when_not_set(self, mock_pika: MagicMock) -> None:
        mock_pika.return_value = {"local": {}}
        self.assertIsNone(_get_local_top_p({}))

    @patch("core.loca_bridge.get_pika_config")
    def test_workspace_override(self, mock_pika: MagicMock) -> None:
        mock_pika.return_value = {"local": {}}
        config = {"agent": {"local_top_p": 0.9}}
        self.assertAlmostEqual(_get_local_top_p(config), 0.9)

    @patch("core.loca_bridge.get_pika_config")
    def test_pika_default(self, mock_pika: MagicMock) -> None:
        mock_pika.return_value = {"local": {"top_p": 0.7}}
        self.assertAlmostEqual(_get_local_top_p({}), 0.7)


class BuildLocaConfigTests(unittest.TestCase):
    """Tests for build_loca_config."""

    @patch("core.loca_bridge.get_pika_config")
    @patch("core.lifecycle.get_pika_config")
    def test_defaults(self, mock_lifecycle_pika: MagicMock, mock_bridge_pika: MagicMock) -> None:
        pika_cfg = {
            "local": {
                "provider_sub": "openai-codex",
                "model": {"default": "gpt-5.3-codex"},
                "reasoning_effort": {"default": "medium"},
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
        self.assertEqual(loca_cfg.agent.max_schema_retries, 0)
        self.assertIn("test-workspace", loca_cfg.sandbox.working_dir)

    @patch("core.loca_bridge.get_pika_config")
    @patch("core.lifecycle.get_pika_config")
    def test_temperature_top_p_passthrough(self, mock_lifecycle_pika: MagicMock, mock_bridge_pika: MagicMock) -> None:
        pika_cfg = {
            "local": {
                "provider_sub": "openai",
                "model": {"default": "gpt-4o"},
                "reasoning_effort": {"default": "medium"},
                "exec_timeout_sec": 300,
            },
        }
        mock_lifecycle_pika.return_value = pika_cfg
        mock_bridge_pika.return_value = pika_cfg

        config = {
            "agent": {
                "local_provider": "openai",
                "local_temperature": 0.5,
                "local_top_p": 0.9,
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
    def test_xhigh_reasoning_maps_to_high(self, mock_lifecycle_pika: MagicMock, mock_bridge_pika: MagicMock) -> None:
        pika_cfg = {
            "local": {
                "model": {"default": "gpt-5.3-codex"},
                "reasoning_effort": {"default": "xhigh"},
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
        with patch.dict(os.environ, {}, clear=True):
            env = os.environ.copy()
            env.pop("OPENAI_API_KEY", None)
            with patch.dict(os.environ, env, clear=True):
                self.assertFalse(check_loca_available("openai"))

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
