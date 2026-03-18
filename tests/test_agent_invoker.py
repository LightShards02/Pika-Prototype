"""Tests for core.agent_invoker."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.agent_invoker import (
    _api_params_for_command,
    _normalize_for_codex_response_format,
    _parse_codex_token_usage,
    _stream_reasoning_callback,
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

            result, _ = run_local_exec(
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


class CodexSchemaNormalizationTests(unittest.TestCase):
    """Tests for Codex response-format schema normalization."""

    def test_object_with_properties_requires_all_property_keys(self) -> None:
        """Normalizer expands required to include every property key."""
        source = {
            "type": "object",
            "properties": {
                "item": {
                    "type": "object",
                    "properties": {
                        "required_field": {"type": "string"},
                        "optional_field": {"type": "string"},
                    },
                    "required": ["required_field"],
                }
            },
            "required": ["item"],
            "additionalProperties": False,
        }

        normalized = _normalize_for_codex_response_format(source)
        item_schema = normalized["properties"]["item"]
        self.assertEqual(item_schema["required"], ["required_field", "optional_field"])
        self.assertEqual(item_schema["additionalProperties"], False)

    def test_plain_object_without_composition_forces_additional_properties_false(self) -> None:
        """Object schemas without composition must set additionalProperties=false."""
        source = {"type": "object"}
        normalized = _normalize_for_codex_response_format(source)
        self.assertEqual(normalized["additionalProperties"], False)


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
            result, usage = run_api_invoke(
                "[System]\nHi\n\n[User]\nHello",
                api_key="test-key",
            )
            self.assertEqual(result, {"handshake": "ok"})
            self.assertIsNone(usage)

    def test_returns_usage_when_present(self) -> None:
        """Returns usage dict when API response includes usage."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "choices": [
                {"message": {"content": '{"handshake": "ok"}'}}
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }

        with patch("core.agent_invoker.requests") as mock_requests:
            mock_requests.post.return_value = mock_response
            result, usage = run_api_invoke(
                "[System]\nHi\n\n[User]\nHello",
                api_key="test-key",
            )
            self.assertEqual(result, {"handshake": "ok"})
            self.assertIsNotNone(usage)
            self.assertEqual(usage["input_tokens"], 100)
            self.assertEqual(usage["output_tokens"], 50)

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
                out, _ = run_local_exec(
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

    def test_non_stream_writes_codex_compatible_schema_copy(self) -> None:
        """run_local_exec passes a normalized schema copy to --output-schema."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schema_path = root / "schema.json"
            source_schema = {
                "type": "object",
                "properties": {
                    "item": {
                        "type": "object",
                        "properties": {
                            "required_field": {"type": "string"},
                            "optional_field": {"type": "string"},
                        },
                        "required": ["required_field"],
                        "additionalProperties": False,
                    }
                },
                "required": ["item"],
                "additionalProperties": False,
            }
            schema_path.write_text(json.dumps(source_schema), encoding="utf-8")

            output_path = root / "out" / "local_output.txt"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text('{"handshake":"ok"}', encoding="utf-8")

            proc = MagicMock()
            proc.returncode = 0
            proc.stderr = ""
            proc.stdout = ""

            with patch("core.agent_invoker.subprocess.run", return_value=proc) as mock_run:
                run_local_exec(
                    prompt="Return JSON",
                    output_schema_path=schema_path,
                    workspace=root,
                    output_path=output_path,
                    stream_output=False,
                    timeout=10,
                )

            cmd = mock_run.call_args[0][0]
            schema_idx = cmd.index("--output-schema") + 1
            codex_schema_path = Path(cmd[schema_idx])
            self.assertTrue(codex_schema_path.exists())
            normalized = json.loads(codex_schema_path.read_text(encoding="utf-8"))
            item_required = normalized["properties"]["item"]["required"]
            self.assertEqual(item_required, ["required_field", "optional_field"])

            original = json.loads(schema_path.read_text(encoding="utf-8"))
            self.assertEqual(original["properties"]["item"]["required"], ["required_field"])

    def test_non_stream_retries_without_schema_on_invalid_json_schema(self) -> None:
        """When Codex rejects response_format schema, run_local_exec retries once without it."""
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

            proc_fail = MagicMock()
            proc_fail.returncode = 1
            proc_fail.stderr = (
                "Invalid schema for response_format 'codex_output_schema': "
                "code=invalid_json_schema"
            )
            proc_fail.stdout = ""

            proc_ok = MagicMock()
            proc_ok.returncode = 0
            proc_ok.stderr = ""
            proc_ok.stdout = ""

            with patch(
                "core.agent_invoker.subprocess.run",
                side_effect=[proc_fail, proc_ok],
            ) as mock_run:
                out, _ = run_local_exec(
                    prompt="Return JSON",
                    output_schema_path=schema_path,
                    workspace=root,
                    output_path=output_path,
                    stream_output=False,
                    timeout=10,
                )

            self.assertEqual(out, {"handshake": "ok"})
            self.assertEqual(mock_run.call_count, 2)
            first_cmd = mock_run.call_args_list[0][0][0]
            second_cmd = mock_run.call_args_list[1][0][0]
            self.assertIn("--output-schema", first_cmd)
            self.assertNotIn("--output-schema", second_cmd)

class ParseCodexTokenUsageTests(unittest.TestCase):
    """Tests for _parse_codex_token_usage."""

    def test_extracts_last_turn_completed_usage(self) -> None:
        """Parses turn.completed events and returns last usage."""
        jsonl = (
            '{"type":"thread.started","thread_id":"abc"}\n'
            '{"type":"turn.started"}\n'
            '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":50,"output_tokens":25}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":200,"cached_input_tokens":100,"output_tokens":50}}\n'
        )
        usage = _parse_codex_token_usage(jsonl)
        self.assertIsNotNone(usage)
        self.assertEqual(usage["input_tokens"], 200)
        self.assertEqual(usage["cached_input_tokens"], 100)
        self.assertEqual(usage["output_tokens"], 50)

    def test_returns_none_when_no_turn_completed(self) -> None:
        """Returns None when no turn.completed in stream."""
        jsonl = '{"type":"thread.started"}\n{"type":"turn.started"}\n'
        self.assertIsNone(_parse_codex_token_usage(jsonl))

    def test_returns_none_for_empty_string(self) -> None:
        """Returns None for empty input."""
        self.assertIsNone(_parse_codex_token_usage(""))

    def test_handles_malformed_lines_gracefully(self) -> None:
        """Skips malformed JSON lines and still parses valid turn.completed."""
        jsonl = (
            'not json\n'
            '{"type":"turn.completed","usage":{"input_tokens":42,"cached_input_tokens":0,"output_tokens":10}}\n'
        )
        usage = _parse_codex_token_usage(jsonl)
        self.assertIsNotNone(usage)
        self.assertEqual(usage["input_tokens"], 42)
        self.assertEqual(usage["output_tokens"], 10)


class StreamReasoningCallbackTests(unittest.TestCase):
    """Tests for _stream_reasoning_callback."""

    def test_prints_reasoning_item_to_stderr(self) -> None:
        """item.completed with type=reasoning prints item.text to stderr."""
        import io
        import sys

        line = '{"type":"item.completed","item":{"id":"item_1","type":"reasoning","text":"Analyzing the request."}}\n'
        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            _stream_reasoning_callback(line)
        out = buf.getvalue()
        self.assertIn("[PIKA] Reasoning: Analyzing the request.", out)

    def test_ignores_non_reasoning_items(self) -> None:
        """Non-reasoning items do not print."""
        import io
        import sys

        line = '{"type":"item.completed","item":{"id":"item_2","type":"agent_message","text":"Done."}}\n'
        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            _stream_reasoning_callback(line)
        self.assertEqual(buf.getvalue(), "")


class RunLocalExecJsonFlagTests(unittest.TestCase):
    """Tests that run_local_exec adds --json and model_reasoning_summary."""

    def test_model_reasoning_summary_concise_in_exec_args(self) -> None:
        """Codex exec is invoked with model_reasoning_summary=concise."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schema_path = root / "schema.json"
            schema_path.write_text(
                '{"type":"object","required":["x"],"properties":{"x":{"type":"string"}},"additionalProperties":false}',
                encoding="utf-8",
            )
            output_path = root / "out" / "local_output.txt"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text('{"x":"y"}', encoding="utf-8")

            proc = MagicMock()
            proc.returncode = 0
            proc.stderr = ""
            proc.stdout = '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":0,"output_tokens":20}}\n'

            with patch("core.agent_invoker.subprocess.run", return_value=proc) as mock_run:
                run_local_exec(
                    prompt="Return JSON",
                    output_schema_path=schema_path,
                    workspace=root,
                    output_path=output_path,
                    stream_output=False,
                    timeout=10,
                )

            cmd = mock_run.call_args[0][0]
            config_args = [a for a in cmd if a == "--config" or (isinstance(a, str) and "model_reasoning_summary" in a)]
            self.assertIn("model_reasoning_summary", " ".join(config_args))

    def test_json_flag_in_exec_args(self) -> None:
        """Codex exec is invoked with --json for token usage capture."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schema_path = root / "schema.json"
            schema_path.write_text(
                '{"type":"object","required":["x"],"properties":{"x":{"type":"string"}},"additionalProperties":false}',
                encoding="utf-8",
            )
            output_path = root / "out" / "local_output.txt"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text('{"x":"y"}', encoding="utf-8")

            proc = MagicMock()
            proc.returncode = 0
            proc.stderr = ""
            proc.stdout = '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":0,"output_tokens":20}}\n'

            with patch("core.agent_invoker.subprocess.run", return_value=proc) as mock_run:
                result, token_usage = run_local_exec(
                    prompt="Return JSON",
                    output_schema_path=schema_path,
                    workspace=root,
                    output_path=output_path,
                    stream_output=False,
                    timeout=10,
                )

            self.assertEqual(result, {"x": "y"})
            self.assertIsNotNone(token_usage)
            self.assertEqual(token_usage["input_tokens"], 100)
            self.assertEqual(token_usage["output_tokens"], 20)
            cmd = mock_run.call_args[0][0]
            self.assertIn("--json", cmd)

    def test_model_flag_in_exec_args_when_set(self) -> None:
        """Codex exec is invoked with --model when model param is set."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schema_path = root / "schema.json"
            schema_path.write_text(
                '{"type":"object","required":["x"],"properties":{"x":{"type":"string"}},"additionalProperties":false}',
                encoding="utf-8",
            )
            output_path = root / "out" / "local_output.txt"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text('{"x":"y"}', encoding="utf-8")

            proc = MagicMock()
            proc.returncode = 0
            proc.stderr = ""
            proc.stdout = '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":0,"output_tokens":20}}\n'

            with patch("core.agent_invoker.subprocess.run", return_value=proc) as mock_run:
                run_local_exec(
                    prompt="Return JSON",
                    output_schema_path=schema_path,
                    workspace=root,
                    output_path=output_path,
                    stream_output=False,
                    timeout=10,
                    model="gpt-5-codex",
                )

            cmd = mock_run.call_args[0][0]
            self.assertIn("--model", cmd)
            model_idx = cmd.index("--model")
            self.assertEqual(cmd[model_idx + 1], "gpt-5-codex")
