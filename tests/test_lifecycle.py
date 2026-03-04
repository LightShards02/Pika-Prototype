"""Tests for core.lifecycle."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from core.context import RuntimeContext
from core.lifecycle import (
    _backfill_missing_required_output_fields,
    _filter_output_to_schema_properties,
    get_agent_provider,
    get_api_config,
    get_local_command,
    get_reasoning_effort,
    get_schema_validation_retries,
    invoke_agent_stub,
    invoke_agent_with_schema_retry,
    resolve_agent_artifacts_dir_for_command,
    resolve_agent_input_codebase_content_dir,
    resolve_agent_runs_dir_for_command,
    resolve_manual_resolution_path_for_command,
    resolve_run_summary_path_for_command,
    validate_output_against_schema,
)


class CommandAwareResolveTests(unittest.TestCase):
    """Tests for command-aware output path resolution."""

    def test_resolve_agent_runs_dir_for_command(self) -> None:
        """agent_runs uses base/command/run_id structure."""
        root = Path(__file__).parent.parent
        config = {"outputs": {"agent_runs_dir": {"path": "out/agent_runs", "no_overwrite": False}}}
        # Without run_id
        path = resolve_agent_runs_dir_for_command(config, root, "map")
        self.assertIn("agent_runs", path.parts)
        self.assertIn("map", path.parts)
        self.assertEqual(path.name, "map")
        # With run_id
        path = resolve_agent_runs_dir_for_command(config, root, "implement", "run-123")
        self.assertIn("agent_runs", path.parts)
        self.assertIn("implement", path.parts)
        self.assertEqual(path.name, "run-123")

    def test_resolve_agent_artifacts_dir_for_command(self) -> None:
        """agent_artifacts uses base/command/run_id structure."""
        root = Path(__file__).parent.parent
        config = {"outputs": {"agent_artifacts_dir": {"path": "out/agent_artifacts", "no_overwrite": False}}}
        path = resolve_agent_artifacts_dir_for_command(config, root, "plan", "run-abc")
        self.assertIn("agent_artifacts", path.parts)
        self.assertIn("plan", path.parts)
        self.assertEqual(path.name, "run-abc")

    def test_resolve_run_summary_path_for_command(self) -> None:
        """run_summary uses base/command/run_summary.jsonl."""
        root = Path(__file__).parent.parent
        config = {"outputs": {"agent_runs_dir": {"path": "out/agent_runs", "no_overwrite": False}}}
        path = resolve_run_summary_path_for_command(config, root, "map")
        self.assertIn("agent_runs", path.parts)
        self.assertIn("map", path.parts)
        self.assertEqual(path.name, "run_summary.jsonl")

    def test_resolve_manual_resolution_path_for_command(self) -> None:
        """manual_resolution uses base/command/manual_resolution.csv."""
        root = Path(__file__).parent.parent
        config = {"outputs": {"agent_runs_dir": {"path": "out/agent_runs", "no_overwrite": False}}}
        path = resolve_manual_resolution_path_for_command(config, root, "resolve_plan")
        self.assertIn("agent_runs", path.parts)
        self.assertIn("resolve_plan", path.parts)
        self.assertEqual(path.name, "manual_resolution.csv")


class LifecycleTests(unittest.TestCase):
    """Test cases for lifecycle helpers."""

    def test_get_schema_validation_retries_default(self) -> None:
        """When agent section missing, returns 0."""
        self.assertEqual(get_schema_validation_retries({}), 0)
        self.assertEqual(get_schema_validation_retries({"agent": None}), 0)

    def test_get_schema_validation_retries_from_config(self) -> None:
        """Returns schema_validation_retries from agent config."""
        self.assertEqual(
            get_schema_validation_retries({"agent": {"schema_validation_retries": 0}}),
            0,
        )
        self.assertEqual(
            get_schema_validation_retries({"agent": {"schema_validation_retries": 2}}),
            2,
        )
        self.assertEqual(
            get_schema_validation_retries({"agent": {"schema_validation_retries": 5}}),
            5,
        )

    def test_get_schema_validation_retries_invalid_fallback(self) -> None:
        """Invalid values fall back to 0."""
        self.assertEqual(
            get_schema_validation_retries({"agent": {"schema_validation_retries": -1}}),
            0,
        )
        self.assertEqual(
            get_schema_validation_retries({"agent": {"schema_validation_retries": "x"}}),
            0,
        )
        self.assertEqual(
            get_schema_validation_retries({"agent": {}}),
            0,
        )


class AgentProviderTests(unittest.TestCase):
    """Tests for get_agent_provider and get_local_command."""

    def test_get_agent_provider_default(self) -> None:
        """Missing agent config returns stub."""
        self.assertEqual(get_agent_provider({}), "stub")
        self.assertEqual(get_agent_provider({"agent": None}), "stub")

    def test_get_agent_provider_from_config(self) -> None:
        """Returns provider from config."""
        self.assertEqual(
            get_agent_provider({"agent": {"provider": "stub"}}),
            "stub",
        )
        self.assertEqual(
            get_agent_provider({"agent": {"provider": "local"}}),
            "local",
        )
        self.assertEqual(
            get_agent_provider({"agent": {"provider": "api"}}),
            "api",
        )

    def test_get_agent_provider_invalid_fallback(self) -> None:
        """Invalid provider falls back to stub."""
        self.assertEqual(
            get_agent_provider({"agent": {"provider": "unknown"}}),
            "stub",
        )

    def test_get_local_command_default(self) -> None:
        """Missing config returns codex (from pika defaults)."""
        self.assertEqual(get_local_command({}), "codex")

    def test_get_local_command_from_config(self) -> None:
        """Returns local_command from config."""
        self.assertEqual(
            get_local_command({"agent": {"local_command": "codex"}}),
            "codex",
        )


class GetReasoningEffortTests(unittest.TestCase):
    """Tests for get_reasoning_effort."""

    def test_project_override_prompt_specific(self) -> None:
        """Project config prompt-specific overrides pika."""
        config = {
            "agent": {
                "reasoning_effort": {
                    "implement_from_specs": "xhigh",
                    "map_spec_to_code": "low",
                }
            }
        }
        self.assertEqual(get_reasoning_effort(config, "implement_from_specs"), "xhigh")
        self.assertEqual(get_reasoning_effort(config, "map_spec_to_code"), "low")

    def test_project_override_default(self) -> None:
        """Project config default applies to unknown prompts."""
        config = {"agent": {"reasoning_effort": {"default": "high"}}}
        self.assertEqual(get_reasoning_effort(config, "unknown_prompt"), "high")

    def test_pika_defaults(self) -> None:
        """Pika defaults apply when no project override."""
        config = {}
        # implement_from_specs defaults to high in pika
        self.assertEqual(get_reasoning_effort(config, "implement_from_specs"), "high")
        # map_spec_to_code defaults to medium in pika
        self.assertEqual(get_reasoning_effort(config, "map_spec_to_code"), "medium")

    def test_fallback_medium(self) -> None:
        """Unknown prompt with no config falls back to medium."""
        config = {}
        self.assertEqual(get_reasoning_effort(config, "nonexistent_prompt"), "medium")


class ApiConfigTests(unittest.TestCase):
    """Tests for get_api_config helpers."""

    def test_get_api_config_returns_url_and_model(self) -> None:
        """When API key is set, returns url and model from pika defaults."""
        import os

        os.environ["NVIDIA_API_KEY"] = "test-key"
        try:
            cfg = get_api_config({"agent": {}})
            self.assertIn("nvidia.com", cfg["url"])
            self.assertIn("kimi", cfg["model"])
            self.assertEqual(cfg["api_key"], "test-key")
        finally:
            os.environ.pop("NVIDIA_API_KEY", None)

    def test_get_api_config_uses_workspace_overrides(self) -> None:
        """Uses api_url and api_model from workspace config when set."""
        import os

        os.environ["CUSTOM_KIMI_KEY"] = "secret123"
        try:
            cfg = get_api_config({
                "agent": {
                    "api_key_env": "CUSTOM_KIMI_KEY",
                    "api_url": "https://custom.example.com/v1",
                    "api_model": "custom/model",
                }
            })
            self.assertEqual(cfg["api_key"], "secret123")
            self.assertEqual(cfg["url"], "https://custom.example.com/v1")
            self.assertEqual(cfg["model"], "custom/model")
        finally:
            os.environ.pop("CUSTOM_KIMI_KEY", None)

    def test_get_api_config_raises_when_key_missing(self) -> None:
        """Raises when api_key_env is not set."""
        import os

        orig = os.environ.pop("NVIDIA_API_KEY", None)
        try:
            with self.assertRaises(RuntimeError) as ctx:
                get_api_config({"agent": {"provider": "api"}})
            self.assertIn("NVIDIA_API_KEY", str(ctx.exception))
        finally:
            if orig is not None:
                os.environ["NVIDIA_API_KEY"] = orig


class InvokeAgentStubTests(unittest.TestCase):
    """Tests for invoke_agent_stub."""

    def test_map_stub_returns_mappings_for_all_spec_ids_from_csv(self) -> None:
        """Map stub parses design_spec_rows_csv and returns one mapping per spec_id."""
        ctx = RuntimeContext(
            command="map",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="test-run",
            project_root="/tmp",
            config_path="/tmp/config.yaml",
        )
        template_vars = {
            "design_spec_rows_csv": "spec_id,subunit,title\nA1,S1,Foo\nA2,S1,Bar\nA3,S2,Baz\n",
            "run_summary_file": "/tmp/run.jsonl",
        }
        result = invoke_agent_stub("map_spec_to_code", template_vars, ctx=ctx)
        self.assertIn("mappings", result)
        mappings = result["mappings"]
        self.assertIsInstance(mappings, dict)
        self.assertIn("A1", mappings)
        self.assertIn("A2", mappings)
        self.assertIn("A3", mappings)
        for sid, m in mappings.items():
            self.assertEqual(m["status"], "unmapped")
            self.assertEqual(m["code_refs"], [])
            self.assertEqual(m["assumptions"], "Stub")

    def test_map_stub_fallback_when_csv_empty(self) -> None:
        """Map stub returns A1 when design_spec_rows_csv is empty."""
        ctx = RuntimeContext(
            command="map",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="test-run",
            project_root="/tmp",
            config_path="/tmp/config.yaml",
        )
        result = invoke_agent_stub("map_spec_to_code", {}, ctx=ctx)
        self.assertIn("mappings", result)
        self.assertEqual(list(result["mappings"].keys()), ["A1"])


def _test_tmpdir() -> Path:
    """Return a temp dir inside the project for sandbox-friendly tests."""
    base = Path(__file__).resolve().parent.parent / "out" / "test-lifecycle"
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="lifecycle-", dir=str(base)))


class ResolveAgentInputCodebaseContentDirTests(unittest.TestCase):
    """Tests for resolve_agent_input_codebase_content_dir."""

    def test_fallback_to_default_when_not_configured(self) -> None:
        """When not configured, uses pika default out/agent_input/codebase_content."""
        tmp = _test_tmpdir()
        try:
            root = tmp
            result = resolve_agent_input_codebase_content_dir({}, root)
            self.assertEqual(result, root / "out" / "agent_input" / "codebase_content")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_uses_config_when_configured(self) -> None:
        """Uses commands.map.outputs.agent_input_codebase_content_dir when set."""
        tmp = _test_tmpdir()
        try:
            root = tmp
            config = {
                "commands": {
                    "map": {
                        "outputs": {
                            "agent_input_codebase_content_dir": {
                                "path": "custom/agent_input",
                                "no_overwrite": False,
                            }
                        }
                    }
                }
            }
            result = resolve_agent_input_codebase_content_dir(
                config, root, command="map"
            )
            self.assertEqual(result, root / "custom" / "agent_input")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class CodebaseContentWriteTests(unittest.TestCase):
    """Tests for codebase_content write before agent invocation."""

    def test_invoke_writes_codebase_content_when_present(self) -> None:
        """invoke_agent_with_schema_retry writes codebase_content to configured dir."""
        tmp = _test_tmpdir()
        try:
            root = tmp
            out_dir = root / "out" / "agent_input" / "codebase_content"
            config = {
                "outputs": {
                    "agent_input_codebase_content_dir": {
                        "path": "out/agent_input/codebase_content",
                        "no_overwrite": False,
                    }
                },
                "agent": {"provider": "stub"},
                "prompts": {"prompt_file": "prompts/PROMPT.yaml"},
                "schemas": {},
                "commands": {},
                "inputs": {"project_context_filename": "PROJECT_CONTEXT.md"},
                "id_generation": {},
                "csv_contracts": {},
                "logging": {},
            }
            ctx = RuntimeContext(
                command="map",
                dry_run=False,
                verbose=False,
                command_only_validation=False,
                run_id="run-123",
                project_root=str(root),
                config_path=str(root / "config.yaml"),
            )
            template_vars = {
                "codebase_content": "# Codebase Snapshot\n\n## File Tree\n\nfoo.py",
                "design_spec_rows_csv": "spec_id,subunit\nA1,S1\n",
                "run_summary_file": "-",
            }
            invoke_agent_with_schema_retry(
                prompt_name="map_spec_to_code",
                template_vars=template_vars,
                schema_path=None,
                config=config,
                ctx=ctx,
            )
            out_path = out_dir / "run-123" / "codebase_content_map.md"
            self.assertTrue(out_path.exists(), f"Expected {out_path} to exist")
            self.assertIn("# Codebase Snapshot", out_path.read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_invoke_skips_write_when_codebase_content_empty(self) -> None:
        """No file written when codebase_content is empty."""
        tmp = _test_tmpdir()
        try:
            root = tmp
            out_dir = root / "out" / "agent_input" / "codebase_content"
            config = {
                "outputs": {
                    "agent_input_codebase_content_dir": {
                        "path": "out/agent_input/codebase_content",
                        "no_overwrite": False,
                    }
                },
                "agent": {"provider": "stub"},
                "prompts": {"prompt_file": "prompts/PROMPT.yaml"},
                "schemas": {},
                "commands": {},
                "inputs": {"project_context_filename": "PROJECT_CONTEXT.md"},
                "id_generation": {},
                "csv_contracts": {},
                "logging": {},
            }
            ctx = RuntimeContext(
                command="map",
                dry_run=False,
                verbose=False,
                command_only_validation=False,
                run_id="run-456",
                project_root=str(root),
                config_path=str(root / "config.yaml"),
            )
            template_vars = {
                "codebase_content": "",
                "design_spec_rows_csv": "spec_id,subunit\nA1,S1\n",
                "run_summary_file": "-",
            }
            invoke_agent_with_schema_retry(
                prompt_name="map_spec_to_code",
                template_vars=template_vars,
                schema_path=None,
                config=config,
                ctx=ctx,
            )
            run_subdir = out_dir / "run-456"
            self.assertFalse(
                run_subdir.exists(),
                "Should not create run subdir when codebase_content is empty",
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class FilterAndBackfillTests(unittest.TestCase):
    """Tests for filter and backfill before schema validation."""

    _MAP_SCHEMA = {
        "properties": {
            "manual_resolution_items": {"type": "array"},
            "run_summary": {"type": "object"},
            "created_at": {"type": "string"},
            "mappings": {"type": "array"},
        },
        "required": ["manual_resolution_items", "run_summary", "created_at", "mappings"],
    }

    def test_filter_strips_extra_summary(self) -> None:
        """Output with top-level summary; after filter, summary is gone, other keys preserved."""
        output = {
            "manual_resolution_items": [],
            "run_summary": {"command": "agent map", "status": "success", "summary": "x", "blocking_items": 0, "storage_file": "-"},
            "created_at": "2024-01-01T00:00:00Z",
            "mappings": [],
            "summary": {"total_specs": 8, "mapped_count": 0},
        }
        result = _filter_output_to_schema_properties(output, self._MAP_SCHEMA)
        self.assertNotIn("summary", result)
        self.assertEqual(result["manual_resolution_items"], [])
        self.assertEqual(result["mappings"], [])

    def test_filter_preserves_schema_properties(self) -> None:
        """Output with only schema keys; unchanged after filter."""
        output = {
            "manual_resolution_items": [],
            "run_summary": {"command": "agent map", "status": "success", "summary": "x", "blocking_items": 0, "storage_file": "-"},
            "created_at": "2024-01-01T00:00:00Z",
            "mappings": [],
        }
        result = _filter_output_to_schema_properties(output, self._MAP_SCHEMA)
        self.assertEqual(set(result.keys()), set(output.keys()))
        self.assertEqual(result, output)

    def test_filter_strips_multiple_extras(self) -> None:
        """Output with summary, foo, bar; all stripped."""
        output = {
            "manual_resolution_items": [],
            "run_summary": {"command": "agent map", "status": "success", "summary": "x", "blocking_items": 0, "storage_file": "-"},
            "created_at": "2024-01-01T00:00:00Z",
            "mappings": [],
            "summary": {},
            "foo": 1,
            "bar": "x",
        }
        result = _filter_output_to_schema_properties(output, self._MAP_SCHEMA)
        self.assertNotIn("summary", result)
        self.assertNotIn("foo", result)
        self.assertNotIn("bar", result)
        self.assertEqual(len(result), 4)

    def test_backfill_adds_run_summary_when_missing(self) -> None:
        """Output missing run_summary; backfill adds minimal valid run_summary."""
        output = {
            "manual_resolution_items": [],
            "created_at": "2024-01-01T00:00:00Z",
            "mappings": [],
        }
        result = _backfill_missing_required_output_fields(
            output, self._MAP_SCHEMA, command="map"
        )
        self.assertIn("run_summary", result)
        self.assertEqual(result["run_summary"]["command"], "agent map")
        self.assertEqual(result["run_summary"]["status"], "success")
        self.assertEqual(result["run_summary"]["summary"], "(auto-generated)")

    def test_backfill_adds_created_at_when_missing(self) -> None:
        """Output missing created_at; backfill adds ISO timestamp."""
        output = {
            "manual_resolution_items": [],
            "run_summary": {"command": "agent map", "status": "success", "summary": "x", "blocking_items": 0, "storage_file": "-"},
            "mappings": [],
        }
        result = _backfill_missing_required_output_fields(
            output, self._MAP_SCHEMA, command="map"
        )
        self.assertIn("created_at", result)
        self.assertIn("T", result["created_at"])
        # Format: YYYY-MM-DDTHH:MM:SS UTC+X
        self.assertRegex(result["created_at"], r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2} UTC[+-]\d{1,2}(:\d{2})?$")

    def test_backfill_does_not_overwrite_present(self) -> None:
        """Output has run_summary; backfill leaves it unchanged."""
        output = {
            "manual_resolution_items": [],
            "run_summary": {"command": "agent map", "status": "partial", "summary": "Mapped 5 specs", "blocking_items": 0, "storage_file": "/tmp/x"},
            "created_at": "2024-01-01T00:00:00Z",
            "mappings": [],
        }
        result = _backfill_missing_required_output_fields(
            output, self._MAP_SCHEMA, command="map"
        )
        self.assertEqual(result["run_summary"]["status"], "partial")
        self.assertEqual(result["run_summary"]["summary"], "Mapped 5 specs")

    def test_validate_passes_after_filter_and_backfill(self) -> None:
        """Full flow: output with summary + missing run_summary/created_at; filter+backfill+validate passes."""
        schema_path = Path(__file__).resolve().parent.parent / "schemas" / "agent_outputs" / "index_output.schema.json"
        self.assertTrue(schema_path.exists(), f"Schema not found: {schema_path}")
        output = {
            "manual_resolution_items": [],
            "mappings": [
                {"spec_id": "A1", "status": "unmapped", "code_refs": [], "assumptions": "Test"},
            ],
            "summary": {"total_specs": 1, "mapped_count": 0},
        }
        result = validate_output_against_schema(
            output, schema_path, command="map"
        )
        self.assertNotIn("summary", result)
        self.assertIn("run_summary", result)
        self.assertIn("created_at", result)
        self.assertEqual(len(result["mappings"]), 1)
        self.assertEqual(result["mappings"][0]["spec_id"], "A1")


if __name__ == "__main__":
    unittest.main()
