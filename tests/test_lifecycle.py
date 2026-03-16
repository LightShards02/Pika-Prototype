"""Tests for core.lifecycle."""

from __future__ import annotations

import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.context import RuntimeContext
from core.lifecycle import (
    _create_local_agent_temp_workspace,
    _emit_agent_conclusion,
    _backfill_missing_required_output_fields,
    _filter_output_to_schema_properties,
    get_agent_provider,
    get_api_config,
    get_local_command,
    get_local_exec_timeout_sec,
    get_local_model,
    get_reasoning_effort,
    get_schema_validation_retries,
    invoke_agent_local,
    invoke_agent_stub,
    invoke_agent_with_schema_retry,
    resolve_agent_artifacts_dir_for_command,
    resolve_agent_input_codebase_content_dir,
    resolve_agent_runs_dir_for_command,
    resolve_codebase_dir_path,
    resolve_manual_resolution_path_for_command,
    resolve_resolution_template_path_for_run,
    resolve_run_summary_path_for_command,
    sync_local_agent_workspace,
    validate_output_against_schema,
)


class EmitAgentConclusionTests(unittest.TestCase):
    """Tests for agent call conclusion output."""

    def test_emit_agent_conclusion_with_tokens(self) -> None:
        """Emits elapsed time and token usage to stderr."""
        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            _emit_agent_conclusion(
                "implement_anchor_planner",
                8.2,
                {"input_tokens": 4000, "cached_input_tokens": 200, "output_tokens": 850},
            )
        out = buf.getvalue()
        self.assertIn("[PIKA] Agent complete (implement_anchor_planner): 8.2s", out)
        self.assertIn("in=4200", out)
        self.assertIn("out=850", out)

    def test_emit_agent_conclusion_without_tokens(self) -> None:
        """Emits elapsed time and N/A token usage when token_usage is None."""
        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            _emit_agent_conclusion("implement_unified_planner", 12.3, None)
        out = buf.getvalue()
        self.assertIn("[PIKA] Agent complete (implement_unified_planner): 12.3s", out)
        self.assertIn("in=N/A", out)
        self.assertIn("out=N/A", out)


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

    def test_resolve_resolution_template_path_for_run(self) -> None:
        """Run-scoped template path uses base/command/run_id/manual_resolution/resolutions.yaml."""
        root = Path(__file__).parent.parent
        config = {"outputs": {"agent_runs_dir": {"path": "out/agent_runs", "no_overwrite": False}}}
        path = resolve_resolution_template_path_for_run(config, root, "map", "run-xyz")
        self.assertIn("agent_runs", path.parts)
        self.assertIn("map", path.parts)
        self.assertIn("run-xyz", path.parts)
        self.assertIn("manual_resolution", path.parts)
        self.assertEqual(path.name, "resolutions.yaml")


class ResolveCodebaseDirPathTests(unittest.TestCase):
    """Tests for resolve_codebase_dir_path."""

    def test_uses_explicit_override_path_when_existing(self) -> None:
        """When --codebase-dir points to an existing directory, return that directory."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            explicit = root / "custom_src"
            explicit.mkdir(parents=True, exist_ok=True)
            ctx = RuntimeContext(
                command="map",
                dry_run=False,
                verbose=False,
                command_only_validation=False,
                run_id="run-1",
                project_root=str(root),
                config_path=str(root / "config.yaml"),
                input_overrides={"codebase_dir": str(explicit)},
            )
            config = {"commands": {"map": {"inputs": {}}}}
            result = resolve_codebase_dir_path(config, root, ctx)
            self.assertEqual(result.resolve(), explicit.resolve())

    def test_uses_command_input_codebase_dir_when_set(self) -> None:
        """When commands.<cmd>.inputs.codebase_dir is set, resolve relative to project_root."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src"
            src.mkdir(parents=True, exist_ok=True)
            ctx = RuntimeContext(
                command="map",
                dry_run=False,
                verbose=False,
                command_only_validation=False,
                run_id="run-1",
                project_root=str(root),
                config_path=str(root / "config.yaml"),
                input_overrides={},
            )
            config = {"commands": {"map": {"inputs": {"codebase_dir": "src"}}}}
            result = resolve_codebase_dir_path(config, root, ctx)
            self.assertEqual(result.resolve(), src.resolve())

    def test_returns_project_root_when_not_configured(self) -> None:
        """When codebase_dir is not set, returns project_root."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = RuntimeContext(
                command="map",
                dry_run=False,
                verbose=False,
                command_only_validation=False,
                run_id="run-1",
                project_root=str(root),
                config_path=str(root / "config.yaml"),
                input_overrides={},
            )
            config = {"commands": {"map": {"inputs": {}}}}
            result = resolve_codebase_dir_path(config, root, ctx)
            self.assertEqual(result.resolve(), root.resolve())

    def test_returns_project_root_when_configured_dot(self) -> None:
        """When codebase_dir is '.', return project_root."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = RuntimeContext(
                command="map",
                dry_run=False,
                verbose=False,
                command_only_validation=False,
                run_id="run-1",
                project_root=str(root),
                config_path=str(root / "config.yaml"),
                input_overrides={"codebase_dir": "."},
            )
            config = {"commands": {"map": {"inputs": {}}}}
            result = resolve_codebase_dir_path(config, root, ctx)
            self.assertEqual(result.resolve(), root.resolve())

    def test_creates_missing_cli_codebase_path_when_not_exists(self) -> None:
        """When CLI --codebase-dir path does not exist, create it under project_root."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "missing_src"
            self.assertFalse(missing.exists())
            ctx = RuntimeContext(
                command="map",
                dry_run=False,
                verbose=False,
                command_only_validation=False,
                run_id="run-1",
                project_root=str(root),
                config_path=str(root / "config.yaml"),
                input_overrides={"codebase_dir": "missing_src"},
            )
            config = {"commands": {"map": {"inputs": {}}}}
            result = resolve_codebase_dir_path(config, root, ctx)
            self.assertEqual(result.resolve(), missing.resolve())
            self.assertTrue(missing.exists())

    def test_creates_missing_command_input_codebase_path_when_not_exists(self) -> None:
        """When commands.<cmd>.inputs.codebase_dir path does not exist, create it under project_root."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "missing_src"
            self.assertFalse(missing.exists())
            ctx = RuntimeContext(
                command="map",
                dry_run=False,
                verbose=False,
                command_only_validation=False,
                run_id="run-1",
                project_root=str(root),
                config_path=str(root / "config.yaml"),
                input_overrides={},
            )
            config = {"commands": {"map": {"inputs": {"codebase_dir": "missing_src"}}}}
            result = resolve_codebase_dir_path(config, root, ctx)
            self.assertEqual(result.resolve(), missing.resolve())
            self.assertTrue(missing.exists())


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


class GetLocalExecTimeoutTests(unittest.TestCase):
    """Tests for get_local_exec_timeout_sec."""

    def test_uses_workspace_override(self) -> None:
        """Workspace agent.local_exec_timeout_sec overrides pika defaults."""
        config = {"agent": {"local_exec_timeout_sec": 1234}}
        self.assertEqual(get_local_exec_timeout_sec(config), 1234)

    def test_falls_back_to_pika_default(self) -> None:
        """When workspace override is absent, uses pika local.exec_timeout_sec."""
        with patch(
            "core.pika_config.get_pika_config",
            return_value={"local": {"exec_timeout_sec": 777}},
        ):
            self.assertEqual(get_local_exec_timeout_sec({"agent": {}}), 777)

    def test_invalid_values_fall_back_to_hard_default(self) -> None:
        """Invalid workspace+pika values fall back to 600 seconds."""
        with patch(
            "core.pika_config.get_pika_config",
            return_value={"local": {"exec_timeout_sec": "bad"}},
        ):
            self.assertEqual(
                get_local_exec_timeout_sec({"agent": {"local_exec_timeout_sec": -1}}),
                600,
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


class GetLocalModelTests(unittest.TestCase):
    """Tests for get_local_model."""

    def test_project_override_string(self) -> None:
        """Project config local_model (string) overrides pika for all prompts."""
        config = {"agent": {"local_model": "gpt-5-codex"}}
        with patch("core.pika_config.get_pika_config") as m:
            m.return_value = {"local": {"model": {"default": "gpt-4-codex"}}}
            self.assertEqual(get_local_model(config, "implement_from_specs"), "gpt-5-codex")
            self.assertEqual(get_local_model(config, "map_spec_to_code"), "gpt-5-codex")

    def test_project_override_per_prompt(self) -> None:
        """Project config local_model (object) overrides pika per prompt."""
        config = {
            "agent": {
                "local_model": {
                    "implement_from_specs": "gpt-4-codex",
                    "default": "gpt-5-codex",
                }
            }
        }
        with patch("core.pika_config.get_pika_config") as m:
            m.return_value = {"local": {"model": {"default": "gpt-5-codex"}}}
            self.assertEqual(get_local_model(config, "implement_from_specs"), "gpt-4-codex")
            self.assertEqual(get_local_model(config, "map_spec_to_code"), "gpt-5-codex")

    def test_pika_fallback_string(self) -> None:
        """Pika local.model (string) used when project has no override."""
        config = {}
        with patch("core.pika_config.get_pika_config") as m:
            m.return_value = {"local": {"model": "gpt-5-codex"}}
            self.assertEqual(get_local_model(config, "implement_from_specs"), "gpt-5-codex")

    def test_pika_fallback_per_prompt(self) -> None:
        """Pika local.model (object) used per prompt when project has no override."""
        config = {}
        with patch("core.pika_config.get_pika_config") as m:
            m.return_value = {
                "local": {
                    "model": {
                        "default": "gpt-5-codex",
                        "implement_from_specs": "gpt-4-codex",
                    }
                }
            }
            self.assertEqual(get_local_model(config, "implement_from_specs"), "gpt-4-codex")
            self.assertEqual(get_local_model(config, "map_spec_to_code"), "gpt-5-codex")

    def test_ignores_empty_string_falls_back_to_pika(self) -> None:
        """Project local_model empty string falls back to pika."""
        config = {"agent": {"local_model": "   "}}
        with patch("core.pika_config.get_pika_config") as m:
            m.return_value = {"local": {"model": "gpt-5-codex"}}
            self.assertEqual(get_local_model(config, "implement_from_specs"), "gpt-5-codex")


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


class LocalAgentTempWorkspaceFallbackTests(unittest.TestCase):
    """Tests for local agent temp workspace fallback behavior."""

    def test_create_workspace_falls_back_to_project_local_base_when_primary_inaccessible(self) -> None:
        """When primary base workspace probe fails, fallback base under project root is used."""
        root = Path("C:/pika-test-root")
        primary_base = Path("C:/pika-temp-primary")
        fallback_base = (root / "out" / "local_agent_temp").resolve()
        config: dict[str, object] = {}

        with patch("core.lifecycle.Path.mkdir"):
            with patch("core.lifecycle._cleanup_stale_local_agent_workspaces"):
                with patch(
                    "core.lifecycle._resolve_local_agent_temp_base_dir",
                    return_value=primary_base,
                ):
                    with patch(
                        "core.lifecycle._create_local_agent_workspace_dir",
                        side_effect=[
                            primary_base / "ws1",
                            fallback_base / "ws2",
                        ],
                    ):
                        with patch(
                            "core.lifecycle._probe_local_agent_temp_workspace_access",
                            side_effect=[PermissionError("denied"), None],
                        ):
                            workspace = _create_local_agent_temp_workspace(
                                config,  # type: ignore[arg-type]
                                root,
                                command="implement",
                                run_id="run-1",
                                prompt_name="shared",
                            )

        self.assertEqual(workspace, fallback_base / "ws2")


class SyncLocalAgentWorkspaceTests(unittest.TestCase):
    """Tests for local workspace synchronization behavior."""

    def test_sync_skips_unreadable_source_entry_and_copies_readable_entries(self) -> None:
        """Unreadable source entries should be skipped without failing sync."""
        source = Path("C:/src")
        workspace = Path("C:/ws")
        readable = source / "readable.txt"
        blocked = source / ".pytest_cache"
        stale = workspace / "stale.txt"

        def fake_iterdir(path_obj: Path) -> list[Path]:
            if path_obj == workspace:
                return [stale]
            if path_obj == source:
                return [readable, blocked]
            return []

        def fake_exists(path_obj: Path) -> bool:
            return path_obj == source

        def fake_is_dir(path_obj: Path) -> bool:
            if path_obj in (source, workspace):
                return True
            if path_obj == blocked:
                raise PermissionError("denied")
            return False

        with patch.object(Path, "resolve", lambda path_obj: path_obj):
            with patch.object(Path, "exists", fake_exists):
                with patch.object(Path, "is_dir", fake_is_dir):
                    with patch.object(Path, "mkdir"):
                        with patch.object(Path, "iterdir", fake_iterdir):
                            with patch.object(Path, "unlink"):
                                with patch("core.lifecycle._is_path_within", return_value=False):
                                    with patch("core.lifecycle.shutil.copytree") as mock_copytree:
                                        with patch("core.lifecycle.shutil.copy2") as mock_copy2:
                                            sync_local_agent_workspace(source, workspace)

        mock_copy2.assert_called_once_with(readable, workspace / "readable.txt")
        mock_copytree.assert_not_called()


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


class InvokeAgentLocalIsolationTests(unittest.TestCase):
    """Tests for local-agent isolated temp workspace execution."""

    def test_invoke_agent_local_passes_workspace_timeout_override(self) -> None:
        """invoke_agent_local forwards agent.local_exec_timeout_sec to run_local_exec."""
        tmp = _test_tmpdir()
        try:
            root = tmp
            schema_path = root / "schema.json"
            schema_path.write_text('{"type":"object"}', encoding="utf-8")
            captured: dict[str, object] = {}

            class _PromptSpec:
                system_prompt = "System {{value}}"
                user_prompt = "User {{value}}"

            class _Registry:
                def get(self, prompt_name: str) -> _PromptSpec:
                    return _PromptSpec()

                def get_schema_path(self, prompt_name: str) -> Path:
                    return schema_path

            def _fake_run_local_exec(*args: object, **kwargs: object) -> tuple[dict[str, object], dict[str, int]]:
                output_path = kwargs.get("output_path")
                assert isinstance(output_path, Path)
                captured["timeout"] = kwargs.get("timeout")
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text('{"status":"ok"}', encoding="utf-8")
                return (
                    {"status": "ok"},
                    {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1},
                )

            config = {
                "agent": {
                    "provider": "local",
                    "local_command": "codex",
                    "stream_output": False,
                    "local_exec_timeout_sec": 1200,
                }
            }
            ctx = RuntimeContext(
                command="map",
                dry_run=False,
                verbose=False,
                command_only_validation=False,
                run_id="run-local-timeout",
                project_root=str(root),
                config_path=str(root / "config.yaml"),
            )
            with patch("core.lifecycle.load_prompt_registry", return_value=_Registry()):
                with patch("core.lifecycle.run_local_exec", side_effect=_fake_run_local_exec):
                    invoke_agent_local(
                        prompt_name="map_spec_to_code",
                        template_vars={"value": "x"},
                        schema_path=schema_path,
                        config=config,
                        ctx=ctx,
                    )
            self.assertEqual(captured.get("timeout"), 1200)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_invoke_agent_local_fails_fast_when_local_auth_unavailable(self) -> None:
        """Local invoke raises clear error when codex auth/login is unavailable."""
        root = Path("C:/proj")
        schema_path = Path("C:/schema.json")
        workspace = Path("C:/workspace")

        class _PromptSpec:
            system_prompt = "System {{value}}"
            user_prompt = "User {{value}}"

        class _Registry:
            def get(self, prompt_name: str) -> _PromptSpec:
                return _PromptSpec()

            def get_schema_path(self, prompt_name: str) -> Path:
                return schema_path

        config = {
            "agent": {
                "provider": "local",
                "local_command": "codex",
                "stream_output": False,
            }
        }
        ctx = RuntimeContext(
            command="map",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-local-auth-unavailable",
            project_root=str(root),
            config_path=str(root / "config.yaml"),
        )

        with patch("core.lifecycle.Path.mkdir"):
            with patch("core.lifecycle.load_prompt_registry", return_value=_Registry()):
                with patch("core.lifecycle.check_local_available", return_value=False):
                    with patch("core.lifecycle.run_local_exec") as mock_exec:
                        with patch.object(Path, "exists", lambda p: p == schema_path):
                            with self.assertRaises(RuntimeError) as exc_ctx:
                                invoke_agent_local(
                                    prompt_name="map_spec_to_code",
                                    template_vars={"value": "x"},
                                    schema_path=schema_path,
                                    config=config,
                                    ctx=ctx,
                                    local_workspace_override=workspace,
                                )
                        mock_exec.assert_not_called()
        self.assertIn("codex login", str(exc_ctx.exception))

    def test_invoke_agent_local_uses_isolated_workspace_and_cleans_up(self) -> None:
        """Local invoke runs outside project root and cleans temp workspace after completion."""
        tmp = _test_tmpdir()
        try:
            root = tmp
            schema_path = root / "schema.json"
            schema_path.write_text('{"type":"object"}', encoding="utf-8")
            captured: dict[str, Path] = {}

            class _PromptSpec:
                system_prompt = "System {{value}}"
                user_prompt = "User {{value}}"

            class _Registry:
                def get(self, prompt_name: str) -> _PromptSpec:
                    return _PromptSpec()

                def get_schema_path(self, prompt_name: str) -> Path:
                    return schema_path

            def _fake_run_local_exec(*args: object, **kwargs: object) -> tuple[dict[str, object], dict[str, int]]:
                workspace = kwargs.get("workspace")
                output_path = kwargs.get("output_path")
                assert isinstance(workspace, Path)
                assert isinstance(output_path, Path)
                captured["workspace"] = workspace
                captured["output_path"] = output_path
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text('{"status":"ok"}', encoding="utf-8")
                return (
                    {"status": "ok"},
                    {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1},
                )

            config = {
                "agent": {
                    "provider": "local",
                    "local_command": "codex",
                    "stream_output": False,
                }
            }
            ctx = RuntimeContext(
                command="map",
                dry_run=False,
                verbose=False,
                command_only_validation=False,
                run_id="run-local-iso",
                project_root=str(root),
                config_path=str(root / "config.yaml"),
            )
            with patch("core.lifecycle.load_prompt_registry", return_value=_Registry()):
                with patch("core.lifecycle.run_local_exec", side_effect=_fake_run_local_exec):
                    result = invoke_agent_local(
                        prompt_name="map_spec_to_code",
                        template_vars={"value": "x"},
                        schema_path=schema_path,
                        config=config,
                        ctx=ctx,
                    )

            self.assertEqual(result, {"status": "ok"})
            self.assertIn("workspace", captured)
            workspace = captured["workspace"]
            self.assertNotEqual(workspace.resolve(), root.resolve())
            self.assertFalse(workspace.exists(), "Isolated temp workspace should be cleaned")

            canonical_output = (
                resolve_agent_artifacts_dir_for_command(
                    config,
                    root,
                    "map",
                    "run-local-iso",
                )
                / "local_output.json"
            )
            self.assertTrue(canonical_output.exists())
            self.assertEqual(canonical_output.read_text(encoding="utf-8"), '{"status":"ok"}')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_invoke_agent_local_uses_workspace_override_without_cleanup(self) -> None:
        """When override is provided, local invoke uses it and does not auto-clean it."""
        tmp = _test_tmpdir()
        try:
            root = tmp
            shared_workspace = root / "shared-local-workspace"
            shared_workspace.mkdir(parents=True, exist_ok=True)
            schema_path = root / "schema.json"
            schema_path.write_text('{"type":"object"}', encoding="utf-8")
            captured: dict[str, Path] = {}

            class _PromptSpec:
                system_prompt = "System {{value}}"
                user_prompt = "User {{value}}"

            class _Registry:
                def get(self, prompt_name: str) -> _PromptSpec:
                    return _PromptSpec()

                def get_schema_path(self, prompt_name: str) -> Path:
                    return schema_path

            def _fake_run_local_exec(*args: object, **kwargs: object) -> tuple[dict[str, object], dict[str, int]]:
                workspace = kwargs.get("workspace")
                output_path = kwargs.get("output_path")
                assert isinstance(workspace, Path)
                assert isinstance(output_path, Path)
                captured["workspace"] = workspace
                captured["output_path"] = output_path
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text('{"status":"ok"}', encoding="utf-8")
                return (
                    {"status": "ok"},
                    {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1},
                )

            config = {
                "agent": {
                    "provider": "local",
                    "local_command": "codex",
                    "stream_output": False,
                }
            }
            ctx = RuntimeContext(
                command="map",
                dry_run=False,
                verbose=False,
                command_only_validation=False,
                run_id="run-local-override",
                project_root=str(root),
                config_path=str(root / "config.yaml"),
            )
            with patch("core.lifecycle.load_prompt_registry", return_value=_Registry()):
                with patch("core.lifecycle.run_local_exec", side_effect=_fake_run_local_exec):
                    with patch("core.lifecycle._create_local_agent_temp_workspace") as mock_create_temp:
                        result = invoke_agent_local(
                            prompt_name="map_spec_to_code",
                            template_vars={"value": "x"},
                            schema_path=schema_path,
                            config=config,
                            ctx=ctx,
                            local_workspace_override=shared_workspace,
                        )
                        mock_create_temp.assert_not_called()

            self.assertEqual(result, {"status": "ok"})
            self.assertEqual(captured["workspace"].resolve(), shared_workspace.resolve())
            self.assertTrue(shared_workspace.exists(), "Override workspace should not be auto-cleaned")

            canonical_output = (
                resolve_agent_artifacts_dir_for_command(
                    config,
                    root,
                    "map",
                    "run-local-override",
                )
                / "local_output.json"
            )
            self.assertTrue(canonical_output.exists())
            self.assertEqual(canonical_output.read_text(encoding="utf-8"), '{"status":"ok"}')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ControlVocabInjectionTests(unittest.TestCase):
    """Tests for control_vocab_section injection into template_vars."""

    def test_invoke_injects_control_vocab_when_configured(self) -> None:
        """invoke_agent_with_schema_retry injects control_vocab_section when project.control_vocab_path is set."""
        tmp = _test_tmpdir()
        try:
            root = tmp
            vocab_path = root / "vocab.yaml"
            vocab_path.write_text("""version: 1
categories:
  domain:
    - term: spec_id
      definition: Stable spec identifier.
""", encoding="utf-8")
            config = {
                "project": {
                    "name": "x",
                    "root_dir": ".",
                    "state": {
                        "design_spec_path": "out/state/DESIGN-SPEC.csv",
                        "id_registry_path": "out/state/id_registry.json",
                        "sads_id_mapping_path": "out/state/sads_id_mapping.json",
                    },
                    "control_vocab_path": "vocab.yaml",
                },
                "agent": {"provider": "stub"},
                "prompts": {"prompt_file": "prompts/PROMPT.yaml"},
                "schemas": {},
                "commands": {},
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
                "design_spec_rows_csv": "spec_id,subunit\nA1,S1\n",
                "run_summary_file": "-",
            }
            captured_vars: list[dict] = []
            original_stub = invoke_agent_stub

            def capturing_stub(*args: object, **kwargs: object) -> object:
                tv = kwargs.get("template_vars", {})
                if isinstance(tv, dict):
                    captured_vars.append(dict(tv))
                return original_stub(*args, **kwargs)

            with patch(
                "core.lifecycle.invoke_agent_stub",
                side_effect=capturing_stub,
            ):
                invoke_agent_with_schema_retry(
                    prompt_name="map_spec_to_code",
                    template_vars=template_vars,
                    schema_path=None,
                    config=config,
                    ctx=ctx,
                )
            self.assertGreater(len(captured_vars), 0)
            passed_vars = captured_vars[0]
            self.assertIn("control_vocab_section", passed_vars)
            self.assertIn("Controlled Vocabulary:", passed_vars["control_vocab_section"])
            self.assertIn("- spec_id: Stable spec identifier.", passed_vars["control_vocab_section"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_invoke_does_not_overwrite_handler_provided_control_vocab(self) -> None:
        """When handler already supplies control_vocab_section, lifecycle does not overwrite it."""
        tmp = _test_tmpdir()
        try:
            root = tmp
            config = {
                "project": {
                    "name": "x",
                    "root_dir": ".",
                    "state": {
                        "design_spec_path": "out/state/DESIGN-SPEC.csv",
                        "id_registry_path": "out/state/id_registry.json",
                        "sads_id_mapping_path": "out/state/sads_id_mapping.json",
                    },
                    "control_vocab_path": "vocab.yaml",
                },
                "agent": {"provider": "stub"},
                "prompts": {"prompt_file": "prompts/PROMPT.yaml"},
                "schemas": {},
                "commands": {},
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
            handler_provided = "Handler-provided vocab section"
            template_vars = {
                "control_vocab_section": handler_provided,
                "design_spec_rows_csv": "spec_id,subunit\nA1,S1\n",
                "run_summary_file": "-",
            }
            result = invoke_agent_with_schema_retry(
                prompt_name="map_spec_to_code",
                template_vars=template_vars,
                schema_path=None,
                config=config,
                ctx=ctx,
            )
            self.assertIsNotNone(result)
            self.assertEqual(template_vars["control_vocab_section"], handler_provided)
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
