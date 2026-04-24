"""Bridge between Pika and Loca: config translation, agent invocation, auth check.

Encapsulates all Loca imports so the rest of Pika only depends on this module.
Provides:
  - build_loca_config: Pika config dict -> LocaConfig
  - check_loca_available: verify auth/API key for the configured sub-provider
  - run_loca_agent: in-process agent invocation returning (json_dict, token_usage)
"""

from __future__ import annotations

import json
import logging
import logging
import os
import sys
from pathlib import Path
from typing import Any, Iterator

from loca.agent import Agent, AgentResult
from loca.config import LocaConfig
from loca.llm import get_llm_client
from loca.llm.base import (
    LLMClient,
    LLMResponse,
    StreamEnd,
    StreamEvent,
    TextBlock,
)
from loca.tools import build_default_registry

from core.agent_invoker import extract_json_from_text
from core.pika_config import get_pika_config

# Loca ``model.provider`` values Pika may select via workspace / pika.yaml.
_VALID_LOCAL_PROVIDER_SUB = frozenset({"openai", "openai-codex", "anthropic"})

_RUN_LOG = logging.getLogger("agent_cli.run")
_LOCA_SCHEMA_DEBUG_MAX_CHARS = 14_000


def _last_assistant_text_from_messages(messages: list[dict]) -> str:
    """Extract plain text from the last assistant message (Anthropic-style blocks)."""
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
            return " ".join(parts).strip()
    return ""


def _try_recover_json_from_result(result: AgentResult) -> dict[str, Any] | None:
    """Try to extract parseable JSON from a Loca result that failed schema validation.

    Returns a dict when JSON is recoverable (PIKA's filter+validate can handle
    extra-property stripping), or None when no valid JSON is available.
    """
    # Loca may have parsed the output even though schema validation failed.
    if result.json_output is not None and isinstance(result.json_output, dict):
        return result.json_output
    # Fall back to text extraction from the last assistant message.
    last_text = _last_assistant_text_from_messages(result.messages)
    if not last_text.strip():
        return None
    try:
        return extract_json_from_text(last_text)
    except (ValueError, json.JSONDecodeError):
        return None


def _emit_loca_schema_failure_debug(result: AgentResult) -> None:
    """When Loca's in-loop schema check fails, log always; stderr only if text is extractable."""
    excerpt = _last_assistant_text_from_messages(result.messages)
    if excerpt.strip():
        preview = excerpt[:_LOCA_SCHEMA_DEBUG_MAX_CHARS]
        if len(excerpt) > _LOCA_SCHEMA_DEBUG_MAX_CHARS:
            preview += (
                f"\n... [truncated, {len(excerpt) - _LOCA_SCHEMA_DEBUG_MAX_CHARS} more chars]"
            )
        try:
            sys.stderr.write(
                "[PIKA] Loca schema validation failed (before PIKA post-check).\n"
                "[PIKA] Last assistant message text (raw model output, may be truncated):\n"
                + preview
                + "\n"
            )
            sys.stderr.flush()
        except OSError:
            pass
        _RUN_LOG.warning(
            "Loca schema validation failed: %s | assistant excerpt (truncated): %s",
            result.error,
            excerpt[:4000],
        )
    else:
        # Capture raw assistant message structure for diagnostics.
        raw_content_info = ""
        for msg in reversed(result.messages):
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content")
            if isinstance(content, list):
                raw_content_info = (
                    f"assistant content blocks: {len(content)}, "
                    f"types: {[b.get('type', '?') for b in content if isinstance(b, dict)]}"
                )
            elif isinstance(content, str):
                raw_content_info = f"assistant content is str, len={len(content)}"
            else:
                raw_content_info = f"assistant content type: {type(content).__name__}"
            break
        if not raw_content_info:
            raw_content_info = f"no assistant message found ({len(result.messages)} messages total)"
        try:
            sys.stderr.write(
                f"[PIKA] Loca schema validation failed (no extractable text). "
                f"Diagnostic: {raw_content_info} | error: {result.error}\n"
            )
            sys.stderr.flush()
        except OSError:
            pass
        _RUN_LOG.warning(
            "Loca schema validation failed (no extractable assistant text in history): %s | diagnostic: %s",
            result.error,
            raw_content_info,
        )

# Loca ``model.provider`` values Pika may select via workspace / pika.yaml.
_VALID_LOCAL_PROVIDER_SUB = frozenset({"openai", "openai-codex", "anthropic"})

_RUN_LOG = logging.getLogger("agent_cli.run")
_LOCA_SCHEMA_DEBUG_MAX_CHARS = 14_000


def _last_assistant_text_from_messages(messages: list[dict]) -> str:
    """Extract plain text from the last assistant message (Anthropic-style blocks)."""
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
            return " ".join(parts).strip()
    return ""


def _try_recover_json_from_result(result: AgentResult) -> dict[str, Any] | None:
    """Try to extract parseable JSON from a Loca result that failed schema validation.

    Returns a dict when JSON is recoverable (PIKA's filter+validate can handle
    extra-property stripping), or None when no valid JSON is available.
    """
    # Loca may have parsed the output even though schema validation failed.
    if result.json_output is not None and isinstance(result.json_output, dict):
        return result.json_output
    # Fall back to text extraction from the last assistant message.
    last_text = _last_assistant_text_from_messages(result.messages)
    if not last_text.strip():
        return None
    try:
        return extract_json_from_text(last_text)
    except (ValueError, json.JSONDecodeError):
        return None


def _emit_loca_schema_failure_debug(result: AgentResult) -> None:
    """When Loca's in-loop schema check fails, log always; stderr only if text is extractable."""
    excerpt = _last_assistant_text_from_messages(result.messages)
    if excerpt.strip():
        preview = excerpt[:_LOCA_SCHEMA_DEBUG_MAX_CHARS]
        if len(excerpt) > _LOCA_SCHEMA_DEBUG_MAX_CHARS:
            preview += (
                f"\n... [truncated, {len(excerpt) - _LOCA_SCHEMA_DEBUG_MAX_CHARS} more chars]"
            )
        try:
            sys.stderr.write(
                "[PIKA] Loca schema validation failed (before PIKA post-check).\n"
                "[PIKA] Last assistant message text (raw model output, may be truncated):\n"
                + preview
                + "\n"
            )
            sys.stderr.flush()
        except OSError:
            pass
        _RUN_LOG.warning(
            "Loca schema validation failed: %s | assistant excerpt (truncated): %s",
            result.error,
            excerpt[:4000],
        )
    else:
        # Capture raw assistant message structure for diagnostics.
        raw_content_info = ""
        for msg in reversed(result.messages):
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content")
            if isinstance(content, list):
                raw_content_info = (
                    f"assistant content blocks: {len(content)}, "
                    f"types: {[b.get('type', '?') for b in content if isinstance(b, dict)]}"
                )
            elif isinstance(content, str):
                raw_content_info = f"assistant content is str, len={len(content)}"
            else:
                raw_content_info = f"assistant content type: {type(content).__name__}"
            break
        if not raw_content_info:
            raw_content_info = f"no assistant message found ({len(result.messages)} messages total)"
        try:
            sys.stderr.write(
                f"[PIKA] Loca schema validation failed (no extractable text). "
                f"Diagnostic: {raw_content_info} | error: {result.error}\n"
            )
            sys.stderr.flush()
        except OSError:
            pass
        _RUN_LOG.warning(
            "Loca schema validation failed (no extractable assistant text in history): %s | diagnostic: %s",
            result.error,
            raw_content_info,
        )


# ---------------------------------------------------------------------------
# Usage tracking wrapper
# ---------------------------------------------------------------------------

class _UsageTrackingLLM(LLMClient):
    """Wraps an LLMClient to accumulate token usage across multi-turn calls.

    The Loca Agent does not aggregate usage across turns. This wrapper
    intercepts every chat/stream_chat call and sums input/output tokens.
    """

    def __init__(self, inner: LLMClient) -> None:
        self._inner = inner
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0

    def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str = "",
        max_tokens: int = 8096,
        json_schema: dict | None = None,
    ) -> LLMResponse:
        """Delegate to inner client and accumulate token usage."""
        response = self._inner.chat(messages, tools, system, max_tokens, json_schema)
        self.total_input_tokens += response.input_tokens
        self.total_output_tokens += response.output_tokens
        return response

    def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str = "",
        max_tokens: int = 8096,
    ) -> Iterator[StreamEvent]:
        """Delegate to inner client, intercept StreamEnd for usage."""
        for event in self._inner.stream_chat(messages, tools, system, max_tokens):
            if isinstance(event, StreamEnd):
                self.total_input_tokens += event.response.input_tokens
                self.total_output_tokens += event.response.output_tokens
            yield event


# ---------------------------------------------------------------------------
# Config translation
# ---------------------------------------------------------------------------

def _get_local_provider_sub(config: dict[str, Any]) -> str:
    """Return Loca provider sub-type: 'openai', 'openai-codex', or 'anthropic'.

    Resolution: workspace ``agent.provider_sub`` -> pika ``local.provider_sub`` -> 'openai-codex'.
    """
    agent = config.get("agent")
    if isinstance(agent, dict):
        val = agent.get("provider_sub")
        if isinstance(val, str) and val in _VALID_LOCAL_PROVIDER_SUB:
            return val

    pika_local = get_pika_config().get("local", {})
    val = pika_local.get("provider_sub")
    if isinstance(val, str) and val in _VALID_LOCAL_PROVIDER_SUB:
        return val
    return "openai-codex"


def _get_local_temperature(config: dict[str, Any], prompt_name: str) -> float | None:
    """Return temperature for the effective local agent profile.

    Resolution is delegated to lifecycle's merged agent-profile helper.
    Returns ``None`` when the provider default should be used.
    """
    from core.lifecycle import _get_effective_local_agent_profile

    value = _get_effective_local_agent_profile(config, prompt_name).get("temperature")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _get_local_top_p(config: dict[str, Any], prompt_name: str) -> float | None:
    """Return top_p for the effective local agent profile.

    Resolution is delegated to lifecycle's merged agent-profile helper.
    Returns ``None`` when the provider default should be used.
    """
    from core.lifecycle import _get_effective_local_agent_profile

    value = _get_effective_local_agent_profile(config, prompt_name).get("top_p")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _get_local_base_url(config: dict[str, Any], prompt_name: str) -> str | None:
    """Return base_url for the effective local agent profile.

    Resolution is delegated to lifecycle's merged agent-profile helper.
    Returns ``None`` when the provider default should be used.

    Used for ``openai`` (OpenAI-compatible root) and ``anthropic`` (Messages API
    base). Ignored for ``openai-codex`` (Codex uses the official endpoint).
    """
    from core.lifecycle import _get_effective_local_agent_profile

    value = _get_effective_local_agent_profile(config, prompt_name).get("base_url")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _get_local_base_url(config: dict[str, Any], prompt_name: str) -> str | None:
    """Return base_url for the effective local agent profile.

    Resolution is delegated to lifecycle's merged agent-profile helper.
    Returns ``None`` when the provider default should be used.

    Used for ``openai`` (OpenAI-compatible root) and ``anthropic`` (Messages API
    base). Ignored for ``openai-codex`` (Codex uses the official endpoint).
    """
    from core.lifecycle import _get_effective_local_agent_profile

    value = _get_effective_local_agent_profile(config, prompt_name).get("base_url")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _map_reasoning_effort(effort: str) -> str | None:
    """Map Pika reasoning_effort to Loca's accepted values.

    Loca accepts: low, medium, high. Pika also supports xhigh which maps to high.
    Returns None when effort is not a valid reasoning string.
    """
    mapping = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high"}
    return mapping.get(effort)


def _resolve_openai_compatible_api_key() -> str:
    """Return the API key for Loca's ``openai`` provider.

    Loca only backfills from ``OPENAI_API_KEY`` when ``api_key`` is omitted; Pika
    passes ``api_key`` explicitly, so an empty string would otherwise skip
    Moonshot's documented ``MOONSHOT_API_KEY`` and yield 401s.

    Precedence: ``OPENAI_API_KEY``, then ``MOONSHOT_API_KEY``. Values are
    stripped of leading/trailing whitespace.

    Returns:
        Non-empty key string, or empty when neither variable yields a value.
    """
    for var in ("OPENAI_API_KEY", "MOONSHOT_API_KEY"):
        raw = os.environ.get(var, "")
        if isinstance(raw, str):
            stripped = raw.strip()
            if stripped:
                return stripped
    return ""


def _resolve_anthropic_api_key() -> str:
    """Return the API key for Loca's ``anthropic`` provider.

    Loca backfills from ``ANTHROPIC_API_KEY`` when ``api_key`` is omitted; Pika
    passes ``api_key`` explicitly so we mirror the openai env resolution here.

    Returns:
        Non-empty key string, or empty when the variable is unset or blank.
    """
    raw = os.environ.get("ANTHROPIC_API_KEY", "")
    if isinstance(raw, str):
        stripped = raw.strip()
        if stripped:
            return stripped
    return ""


def _resolve_openai_compatible_api_key() -> str:
    """Return the API key for Loca's ``openai`` provider.

    Loca only backfills from ``OPENAI_API_KEY`` when ``api_key`` is omitted; Pika
    passes ``api_key`` explicitly, so an empty string would otherwise skip
    Moonshot's documented ``MOONSHOT_API_KEY`` and yield 401s.

    Precedence: ``OPENAI_API_KEY``, then ``MOONSHOT_API_KEY``. Values are
    stripped of leading/trailing whitespace.

    Returns:
        Non-empty key string, or empty when neither variable yields a value.
    """
    for var in ("OPENAI_API_KEY", "MOONSHOT_API_KEY"):
        raw = os.environ.get(var, "")
        if isinstance(raw, str):
            stripped = raw.strip()
            if stripped:
                return stripped
    return ""


def _resolve_anthropic_api_key() -> str:
    """Return the API key for Loca's ``anthropic`` provider.

    Loca backfills from ``ANTHROPIC_API_KEY`` when ``api_key`` is omitted; Pika
    passes ``api_key`` explicitly so we mirror the openai env resolution here.

    Returns:
        Non-empty key string, or empty when the variable is unset or blank.
    """
    raw = os.environ.get("ANTHROPIC_API_KEY", "")
    if isinstance(raw, str):
        stripped = raw.strip()
        if stripped:
            return stripped
    return ""


def build_loca_config(
    pika_config: dict[str, Any],
    prompt_name: str,
    workspace_dir: Path,
) -> LocaConfig:
    """Build a LocaConfig from Pika's config dict.

    Maps Pika provider, model, reasoning_effort, temperature, top_p,
    timeout, and workspace settings into Loca's Pydantic config.

    Args:
        pika_config: Merged workspace + pika config dict.
        prompt_name: Current prompt name (resolved through the normalized agent profile).
        workspace_dir: Absolute path to the isolated agent workspace.

    Returns:
        Fully constructed LocaConfig ready for get_llm_client / build_default_registry.
    """
    # Lazy import to reuse lifecycle helpers without circular dependency
    from core.lifecycle import get_local_model, get_reasoning_effort, get_local_exec_timeout_sec

    provider_sub = _get_local_provider_sub(pika_config)
    model_name = get_local_model(pika_config, prompt_name)
    raw_effort = get_reasoning_effort(pika_config, prompt_name)
    reasoning_effort = (
        None if raw_effort is None else _map_reasoning_effort(raw_effort)
    )
    temperature = _get_local_temperature(pika_config, prompt_name)
    top_p = _get_local_top_p(pika_config, prompt_name)
    base_url = _get_local_base_url(pika_config, prompt_name)
    base_url = _get_local_base_url(pika_config, prompt_name)
    timeout = get_local_exec_timeout_sec(pika_config)

    # Resolve API key (Codex uses OAuth internally)
    # Resolve API key (Codex uses OAuth internally)
    api_key = ""
    if provider_sub == "openai":
        api_key = _resolve_openai_compatible_api_key()
    elif provider_sub == "anthropic":
        api_key = _resolve_anthropic_api_key()
        api_key = _resolve_openai_compatible_api_key()
    elif provider_sub == "anthropic":
        api_key = _resolve_anthropic_api_key()

    # Build stream setting from pika config
    stream = True
    agent = pika_config.get("agent")
    if isinstance(agent, dict) and "stream_output" in agent:
        stream = bool(agent.get("stream_output", True))

    config_dict: dict[str, Any] = {
        "model": {
            "provider": provider_sub,
            "name": model_name,
            "api_key": api_key,
            "temperature": temperature,
            "top_p": top_p,
            "reasoning_effort": reasoning_effort,
            "base_url": base_url,
            "base_url": base_url,
        },
        "agent": {
            "max_turns": 30,
            "max_output_bytes": 131_072,
            "timeout_seconds": min(timeout, 600),
            "max_schema_retries": 0,  # Pika handles retries externally
        },
        "sandbox": {
            "mode": "full_auto",
            "working_dir": str(workspace_dir.resolve()),
        },
        "output": {
            "format": "plain",
            "show_tool_calls": True,
            "stream": stream,
        },
    }

    return LocaConfig.model_validate(config_dict)


# ---------------------------------------------------------------------------
# Auth / availability check
# ---------------------------------------------------------------------------

def check_loca_available(provider_sub: str | None = None) -> bool:
    """Check if Loca can authenticate for the given sub-provider.

    Args:
        provider_sub: 'openai', 'anthropic', or 'openai-codex'. Defaults to 'openai-codex'.
        provider_sub: 'openai', 'anthropic', or 'openai-codex'. Defaults to 'openai-codex'.

    Returns:
        True if credentials are available, False otherwise.
    """
    provider_sub = provider_sub or "openai-codex"

    if provider_sub == "openai":
        return bool(_resolve_openai_compatible_api_key())

    if provider_sub == "anthropic":
        return bool(_resolve_anthropic_api_key())
        return bool(_resolve_openai_compatible_api_key())

    if provider_sub == "anthropic":
        return bool(_resolve_anthropic_api_key())

    if provider_sub == "openai-codex":
        try:
            from loca.auth import get_valid_token
            return get_valid_token() is not None
        except Exception:
            return False

    return False


# ---------------------------------------------------------------------------
# Agent invocation
# ---------------------------------------------------------------------------

def run_loca_agent(
    system_prompt: str,
    user_prompt: str,
    *,
    loca_config: LocaConfig,
    json_schema: dict | None = None,
    stream_output: bool = True,
    stream_reasoning: bool = False,
) -> tuple[dict[str, Any], dict[str, int] | None]:
    """Run Loca Agent in-process and return parsed JSON output + token usage.

    Creates LLM client, tool registry, and Agent. Runs the agent loop
    synchronously and extracts the result.

    Args:
        system_prompt: System prompt text.
        user_prompt: User prompt text.
        loca_config: Fully built LocaConfig.
        json_schema: Optional JSON schema for structured output enforcement.
        stream_output: If True, stream agent text to stderr.
        stream_reasoning: If True, log tool calls to stderr.

    Returns:
        Tuple of (parsed JSON dict, token_usage dict or None).
        token_usage has input_tokens, cached_input_tokens, output_tokens.

    Raises:
        AgentInvocationError: On agent errors or max turns exceeded.
        ValueError: On schema validation failure (triggers Pika retry).
    """
    from core.lifecycle import AgentInvocationError

    # Build LLM client with usage tracking
    llm_client = get_llm_client(loca_config)
    tracked_llm = _UsageTrackingLLM(llm_client)

    # Build tool registry
    tool_registry = build_default_registry(loca_config)

    # Callbacks
    def on_text_delta(text: str) -> None:
        if stream_output:
            try:
                sys.stderr.write(text)
                sys.stderr.flush()
            except OSError:
                pass

    def on_tool_call(name: str, input_dict: dict) -> None:
        if stream_reasoning:
            try:
                args_preview = json.dumps(input_dict, separators=(",", ":"))
                if len(args_preview) > 200:
                    args_preview = args_preview[:200] + "..."
                sys.stderr.write(f"[PIKA] Tool: {name}({args_preview})\n")
                sys.stderr.flush()
            except OSError:
                pass

    def on_tool_result(name: str, result_text: str) -> None:
        if stream_reasoning:
            try:
                preview = result_text[:200] + "..." if len(result_text) > 200 else result_text
                sys.stderr.write(f"[PIKA] Result ({name}): {preview}\n")
                sys.stderr.flush()
            except OSError:
                pass

    # Create and run agent
    agent = Agent(
        llm=tracked_llm,
        tools=tool_registry,
        system=system_prompt,
        max_turns=loca_config.agent.max_turns,
        stream=stream_output,
        on_text_delta=on_text_delta,
        on_tool_call=on_tool_call,
        on_tool_result=on_tool_result,
        json_schema=json_schema,
        max_schema_retries=0,  # Pika handles retries externally
    )

    result: AgentResult = agent.run(user_prompt)

    # Map stop_reason to Pika behavior
    if result.stop_reason == "error":
        raise AgentInvocationError(
            f"Loca agent error: {result.error or 'unknown error'}"
        )
    if result.stop_reason == "max_turns":
        raise AgentInvocationError(
            f"Loca agent exceeded max turns ({result.turns})"
        )
    if result.stop_reason == "schema_error":
        _emit_loca_schema_failure_debug(result)
        # Attempt recovery: Loca rejects extra properties that PIKA's
        # _filter_output_to_schema_properties would strip.  If we can
        # extract parseable JSON, return it and let PIKA filter+validate.
        recovered = _try_recover_json_from_result(result)
        if recovered is not None:
            _RUN_LOG.info(
                "Loca schema validation failed but JSON was recoverable; "
                "deferring to PIKA filter+validate pipeline."
            )
            json_output = recovered
        else:
            raise ValueError(
                f"Loca schema validation failed: {result.error or 'unknown'}"
            )
    elif result.json_output is not None:
        _emit_loca_schema_failure_debug(result)
        # Attempt recovery: Loca rejects extra properties that PIKA's
        # _filter_output_to_schema_properties would strip.  If we can
        # extract parseable JSON, return it and let PIKA filter+validate.
        recovered = _try_recover_json_from_result(result)
        if recovered is not None:
            _RUN_LOG.info(
                "Loca schema validation failed but JSON was recoverable; "
                "deferring to PIKA filter+validate pipeline."
            )
            json_output = recovered
        else:
            raise ValueError(
                f"Loca schema validation failed: {result.error or 'unknown'}"
            )
    elif result.json_output is not None:
        json_output = result.json_output
    else:
        # Fall back to extracting JSON from last text block
        last_text = _last_assistant_text_from_messages(result.messages)
        last_text = _last_assistant_text_from_messages(result.messages)
        if not last_text.strip():
            raise ValueError("Loca agent produced no output")
        json_output = extract_json_from_text(last_text)

    # Build token usage
    token_usage: dict[str, int] | None = None
    if tracked_llm.total_input_tokens > 0 or tracked_llm.total_output_tokens > 0:
        token_usage = {
            "input_tokens": tracked_llm.total_input_tokens,
            "cached_input_tokens": 0,
            "output_tokens": tracked_llm.total_output_tokens,
        }

    return json_output, token_usage
