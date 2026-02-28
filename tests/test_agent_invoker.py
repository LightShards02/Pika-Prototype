"""Tests for core.agent_invoker."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.agent_invoker import (
    _api_params_for_command,
    _parse_combined_prompt,
    check_codex_available,
    extract_json_from_text,
    render_prompt,
    run_api_invoke,
    run_local_exec,
)


class RenderPromptTests(unittest.TestCase):
    """Tests for render_prompt."""

    def test_substitutes_single_variable(self) -> None:
        """Template variables are substituted."""
        result = render_prompt(
            "Hello {{name}}",
            "Context: {{name}}",
            {"name": "World"},
        )
        self.assertIn("Hello World", result)
        self.assertIn("Context: World", result)

    def test_substitutes_multiple_variables(self) -> None:
        """Multiple placeholders are replaced."""
        result = render_prompt(
            "{{a}} and {{b}}",
            "{{b}} then {{a}}",
            {"a": "1", "b": "2"},
        )
        self.assertIn("1 and 2", result)
        self.assertIn("2 then 1", result)

    def test_combines_system_and_user(self) -> None:
        """Output includes [System] and [User] sections."""
        result = render_prompt("sys", "usr", {})
        self.assertIn("[System]", result)
        self.assertIn("sys", result)
        self.assertIn("[User]", result)
        self.assertIn("usr", result)

    def test_none_value_becomes_empty_string(self) -> None:
        """None values render as empty string."""
        result = render_prompt("x{{y}}z", "", {"y": None})
        self.assertIn("xz", result)


class ExtractJsonTests(unittest.TestCase):
    """Tests for extract_json_from_text."""

    def test_plain_json(self) -> None:
        """Plain JSON is parsed directly."""
        out = extract_json_from_text('{"handshake": "ok"}')
        self.assertEqual(out, {"handshake": "ok"})

    def test_json_in_code_block(self) -> None:
        """JSON inside ```json block is extracted."""
        text = 'Some text\n```json\n{"handshake": "ok"}\n```\nmore'
        out = extract_json_from_text(text)
        self.assertEqual(out, {"handshake": "ok"})

    def test_json_in_plain_code_block(self) -> None:
        """JSON inside ``` block (no json tag) is extracted."""
        text = '```\n{"handshake": "ok"}\n```'
        out = extract_json_from_text(text)
        self.assertEqual(out, {"handshake": "ok"})

    def test_invalid_raises(self) -> None:
        """Invalid text raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            extract_json_from_text("not json at all")
        self.assertIn("Could not extract", str(ctx.exception))


class CheckCodexAvailableTests(unittest.TestCase):
    """Tests for check_codex_available."""

    def test_returns_bool(self) -> None:
        """Returns True or False."""
        result = check_codex_available()
        self.assertIsInstance(result, bool)

    def test_nonexistent_command_returns_false(self) -> None:
        """Non-existent command returns False."""
        result = check_codex_available("_nonexistent_codex_command_xyz_")
        self.assertFalse(result)

    def test_uses_utf8_replace_for_subprocess_decode(self) -> None:
        """Availability check forces UTF-8 decode with replacement."""
        proc = MagicMock()
        proc.returncode = 0
        with patch("core.agent_invoker.subprocess.run", return_value=proc) as mock_run:
            result = check_codex_available("codex")
        self.assertTrue(result)
        _, kwargs = mock_run.call_args
        self.assertTrue(kwargs.get("text"))
        self.assertEqual(kwargs.get("encoding"), "utf-8")
        self.assertEqual(kwargs.get("errors"), "replace")


@unittest.skipUnless(
    check_codex_available(),
    "Codex CLI not available (run 'codex login status' to check)",
)
class RunLocalExecIntegrationTests(unittest.TestCase):
    """Integration tests that require Codex CLI. Skipped if Codex unavailable."""

    def test_handshake_simple_schema(self) -> None:
        """Local exec returns JSON that validates against simple handshake schema."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schema_path = root / "handshake.schema.json"
            schema_path.write_text(
                '{"type":"object","required":["handshake"],'
                '"properties":{"handshake":{"type":"string"}},"additionalProperties":false}',
                encoding="utf-8",
            )
            output_path = root / "out" / "local_output.txt"

            prompt = (
                "Return only valid JSON with no other text. "
                'Output exactly: {"handshake":"ok"}'
            )

            result = run_local_exec(
                prompt=prompt,
                output_schema_path=schema_path,
                workspace=root,
                output_path=output_path,
                timeout=60,
            )

            self.assertIn("handshake", result)
            self.assertEqual(result["handshake"], "ok")


class ParseCombinedPromptTests(unittest.TestCase):
    """Tests for _parse_combined_prompt."""

    def test_parses_system_and_user(self) -> None:
        """Extracts system and user parts from combined prompt."""
        combined = "[System]\nHello system\n\n[User]\nHello user"
        system, user = _parse_combined_prompt(combined)
        self.assertEqual(system, "Hello system")
        self.assertEqual(user, "Hello user")

    def test_fallback_when_no_markers(self) -> None:
        """When no [System]/[User], returns empty system and full as user."""
        combined = "Just some text"
        system, user = _parse_combined_prompt(combined)
        self.assertEqual(system, "")
        self.assertEqual(user, "Just some text")


class ApiParamsForCommandTests(unittest.TestCase):
    """Tests for _api_params_for_command."""

    def test_map_uses_lower_temperature_and_top_p(self) -> None:
        """Code mapping uses lower temp/top_p for deterministic output."""
        params = _api_params_for_command("map")
        self.assertEqual(params["temperature"], 0.1)
        self.assertEqual(params["top_p"], 0.95)
        self.assertEqual(params["max_tokens"], 32768)

    def test_other_commands_use_defaults(self) -> None:
        """Non-map commands use default params."""
        params = _api_params_for_command("implement")
        self.assertEqual(params["temperature"], 0.7)
        self.assertEqual(params["top_p"], 1.0)
        self.assertEqual(params["max_tokens"], 16384)

    def test_none_command_uses_defaults(self) -> None:
        """None command uses default params."""
        params = _api_params_for_command(None)
        self.assertEqual(params["temperature"], 0.7)


class RunApiInvokeTests(unittest.TestCase):
    """Tests for run_api_invoke (mocked)."""

    def test_parses_json_from_response(self) -> None:
        """Extracts and parses JSON from API response content."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "choices": [
                {"message": {"content": '{"handshake": "ok"}'}}
            ]
        }

        with patch("core.agent_invoker.requests") as mock_requests:
            mock_requests.post.return_value = mock_response
            result = run_api_invoke(
                "[System]\nHi\n\n[User]\nHello",
                api_key="test-key",
            )
            self.assertEqual(result, {"handshake": "ok"})

    def test_raises_when_requests_missing(self) -> None:
        """Raises clear error when requests is not installed."""
        with patch("core.agent_invoker.requests", None):
            with self.assertRaises(RuntimeError) as ctx:
                run_api_invoke("prompt", api_key="x")
            self.assertIn("requests", str(ctx.exception))

    def test_raises_on_api_error(self) -> None:
        """Raises when API returns non-OK status."""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        with patch("core.agent_invoker.requests") as mock_requests:
            mock_requests.post.return_value = mock_response
            with self.assertRaises(RuntimeError) as ctx:
                run_api_invoke("prompt", api_key="x")
            self.assertIn("401", str(ctx.exception))


class RunLocalExecSubprocessDecodeTests(unittest.TestCase):
    """Tests for subprocess decode settings in run_local_exec."""

    def test_non_stream_uses_utf8_replace_for_subprocess_decode(self) -> None:
        """Non-stream local exec uses UTF-8 decode with replacement on Windows-safe path."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schema_path = root / "schema.json"
            schema_path.write_text(
                '{"type":"object","required":["handshake"],'
                '"properties":{"handshake":{"type":"string"}},"additionalProperties":false}',
                encoding="utf-8",
            )
            output_path = root / "out" / "local_output.txt"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text('{"handshake":"ok"}', encoding="utf-8")

            proc = MagicMock()
            proc.returncode = 0
            proc.stderr = ""
            proc.stdout = ""

            with patch("core.agent_invoker.subprocess.run", return_value=proc) as mock_run:
                out = run_local_exec(
                    prompt="Return JSON",
                    output_schema_path=schema_path,
                    workspace=root,
                    output_path=output_path,
                    stream_output=False,
                    timeout=10,
                )

            self.assertEqual(out, {"handshake": "ok"})
            _, kwargs = mock_run.call_args
            self.assertTrue(kwargs.get("text"))
            self.assertEqual(kwargs.get("encoding"), "utf-8")
            self.assertEqual(kwargs.get("errors"), "replace")
