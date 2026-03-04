"""Agent invocation via api (remote HTTP), local (CLI subprocess), or stub.

Helper functions for invoking agents, rendering prompts, and checking local CLI availability.
Provider categories: api (chat completions API), local (e.g. Codex exec), stub (mock).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

try:
    import requests  # type: ignore
except ImportError:
    requests = None  # type: ignore

_SUBPROCESS_TEXT_ENCODING = "utf-8"
_SUBPROCESS_TEXT_ERRORS = "replace"


def _normalize_for_codex_response_format(schema_node: Any) -> Any:
    """Return schema transformed for Codex response_format compatibility.

    Codex local response_format requires object schemas to declare all property keys
    in `required`. We preserve field types and constraints, but upgrade any object
    node with `properties` to include a complete `required` list.
    """
    if isinstance(schema_node, list):
        return [_normalize_for_codex_response_format(item) for item in schema_node]
    if not isinstance(schema_node, dict):
        return schema_node

    normalized: dict[str, Any] = {
        key: _normalize_for_codex_response_format(value)
        for key, value in schema_node.items()
    }

    props = normalized.get("properties")
    has_props = isinstance(props, dict)
    has_composition = any(key in normalized for key in ("oneOf", "anyOf", "allOf"))
    node_type = normalized.get("type")

    if has_props:
        if node_type in (None, "object"):
            normalized["type"] = "object"
        normalized["required"] = list(props.keys())
        normalized["additionalProperties"] = False
    elif node_type == "object" and not has_composition:
        normalized["additionalProperties"] = False

    return normalized


def _prepare_codex_output_schema(output_schema_path: Path, output_path: Path) -> Path:
    """Write a Codex-compatible schema copy and return the path.

    Keeps the original schema untouched for internal jsonschema validation.
    """
    schema = json.loads(output_schema_path.read_text(encoding="utf-8"))
    normalized = _normalize_for_codex_response_format(schema)
    codex_schema_path = output_path.with_name(f"{output_schema_path.stem}.codex.schema.json")
    codex_schema_path.write_text(json.dumps(normalized, indent=2), encoding="utf-8")
    return codex_schema_path


def _get_local_ps1_path() -> Path:
    """Return local CLI .ps1 path from pika config (Windows)."""
    from core.pika_config import get_pika_config

    p = get_pika_config().get("local", {}).get("ps1_path_windows", "")
    return Path(p) if p else Path.home() / "AppData" / "Roaming" / "npm" / "codex.ps1"


def _get_heartbeat_interval() -> int:
    """Return heartbeat interval in seconds from pika config."""
    from core.pika_config import get_pika_config

    return int(get_pika_config().get("local", {}).get("heartbeat_interval_sec", 30))


def render_prompt(system_prompt: str, user_prompt: str, template_vars: dict[str, Any]) -> str:
    """Render system and user prompts with template variable substitution.

    Replaces {{var_name}} with template_vars[var_name]. Values are stringified.
    Combines system and user into a single prompt suitable for Codex exec.

    Args:
        system_prompt: System/instruction prompt with {{placeholders}}.
        user_prompt: User/content prompt with {{placeholders}}.
        template_vars: Mapping of variable names to values.

    Returns:
        Combined prompt with all placeholders substituted.
    """
    def substitute(text: str) -> str:
        result = text
        for key, value in template_vars.items():
            placeholder = "{{" + key + "}}"
            result = result.replace(placeholder, str(value) if value is not None else "")
        return result

    system = substitute(system_prompt)
    user = substitute(user_prompt)
    return f"[System]\n{system}\n\n[User]\n{user}"


def _resolve_local_command(command: str) -> str:
    """Resolve local command to the npm .ps1 path when using default on Windows."""
    if command == "codex" and sys.platform == "win32":
        ps1 = _get_local_ps1_path()
        if ps1.exists():
            return str(ps1)
    return command


def _build_local_cmd(command: str, args: list[str]) -> list[str]:
    """Build command list for subprocess. Invokes .ps1 via PowerShell on Windows."""
    resolved = _resolve_local_command(command)
    path = Path(resolved)
    if path.suffix.lower() == ".ps1" and path.exists():
        return [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(path.resolve()),
            *args,
        ]
    return [resolved, *args]


def check_local_available(command: str = "codex") -> bool:
    """Check if local CLI (e.g. Codex) is installed and reachable.

    Runs `codex login status` which exits 0 when authenticated.
    Also accepts `codex --version` or similar for basic availability.

    Args:
        command: Executable name or path (default: codex).
                On Windows, defaults to npm codex.ps1 when available.

    Returns:
        True if local CLI runs successfully, False otherwise.
    """
    try:
        cmd = _build_local_cmd(command, ["login", "status"])
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding=_SUBPROCESS_TEXT_ENCODING,
            errors=_SUBPROCESS_TEXT_ERRORS,
            timeout=10,
        )
        return proc.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def check_codex_available(command: str = "codex") -> bool:
    """Alias for check_local_available. Kept for backward compatibility."""
    return check_local_available(command)


def extract_json_from_text(text: str) -> dict[str, Any]:
    """Extract JSON object from text that may contain markdown code fences.

    Looks for ```json ... ``` or ``` ... ``` blocks first, then tries
    parsing the whole text as JSON.

    Args:
        text: Raw text possibly containing JSON.

    Returns:
        Parsed JSON object.

    Raises:
        ValueError: If no valid JSON object could be extracted.
    """
    text = text.strip()
    # Try ```json ... ``` block
    json_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if json_block:
        try:
            return json.loads(json_block.group(1).strip())
        except json.JSONDecodeError:
            pass
    # Try parsing whole text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try to find {...} in text
    brace_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError("Could not extract valid JSON from agent output")


def _parse_combined_prompt(combined: str) -> tuple[str, str]:
    """Parse combined [System]/[User] prompt into system and user parts.

    Args:
        combined: Output of render_prompt (e.g. "[System]\\n...\\n\\n[User]\\n...").

    Returns:
        (system_content, user_content) tuple.
    """
    if "[System]" in combined and "[User]" in combined:
        idx = combined.index("[User]")
        system_part = combined[len("[System]"):idx].strip()
        user_part = combined[idx + len("[User]"):].strip()
        return (system_part, user_part)
    return ("", combined)


def _get_api_config() -> dict[str, Any]:
    """Return api section from pika config."""
    from core.pika_config import get_pika_config

    return get_pika_config().get("api", {})


def _api_params_for_command(command: str | None) -> dict[str, Any]:
    """Return generation params tuned for the given command.

    Code mapping (map) benefits from lower temperature and top_p for
    consistent, deterministic structured output. Other commands use defaults.
    """
    api_cfg = _get_api_config()
    if command == "map":
        m = api_cfg.get("map", {})
        return {
            "max_tokens": m.get("max_tokens", 32768),
            "temperature": m.get("temperature", 0.1),
            "top_p": m.get("top_p", 0.95),
        }
    d = api_cfg.get("default", {})
    return {
        "max_tokens": d.get("max_tokens", 16384),
        "temperature": d.get("temperature", 0.7),
        "top_p": d.get("top_p", 1.0),
    }


def run_api_invoke(
    prompt: str,
    *,
    api_key: str,
    url: str | None = None,
    model: str | None = None,
    command: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    stream: bool = False,
    stream_output: bool = False,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Invoke Kimi K2.5 via NVIDIA API and return parsed JSON output.

    Sends system and user prompts as chat messages. Uses chat_template_kwargs
    with thinking=True for extended reasoning when supported by the model.

    When command is "map" (code mapping), uses lower temperature and top_p
    for consistent, deterministic structured output. Override via explicit args.

    Args:
        prompt: Combined prompt (output of render_prompt with [System] and [User]).
        api_key: API Bearer token.
        url: Chat completions API URL.
        model: Model ID (e.g. moonshotai/kimi-k2.5).
        command: PIKA command name (e.g. map, implement). Tunes params for code mapping when "map".
        max_tokens: Override max tokens. Default varies by command.
        temperature: Override temperature. Default: 0.1 for map, 0.7 otherwise.
        top_p: Override top_p. Default: 0.95 for map, 1.0 otherwise.
        stream: If True, request streaming from API (collects full response).
        stream_output: If True, print streamed chunks to stderr.
        output_path: Optional path to write raw response for debugging.

    Returns:
        Parsed JSON object extracted from model response.

    Raises:
        RuntimeError: If requests is not installed or API call fails.
        ValueError: If response cannot be parsed as JSON.
    """
    if requests is None:
        raise RuntimeError(
            "API provider requires the 'requests' package. Install with: pip install requests"
        )

    api_cfg = _get_api_config()
    url = url or api_cfg.get("url", "https://integrate.api.nvidia.com/v1/chat/completions")
    model = model or api_cfg.get("model", "moonshotai/kimi-k2.5")

    cmd_params = _api_params_for_command(command)
    max_tokens = max_tokens if max_tokens is not None else cmd_params["max_tokens"]
    temperature = temperature if temperature is not None else cmd_params["temperature"]
    top_p = top_p if top_p is not None else cmd_params["top_p"]

    system_part, user_part = _parse_combined_prompt(prompt)
    messages: list[dict[str, str]] = []
    if system_part:
        messages.append({"role": "system", "content": system_part})
    messages.append({"role": "user", "content": user_part})

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "text/event-stream" if stream else "application/json",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "stream": stream,
        "chat_template_kwargs": {"thinking": True},
    }

    timeout = api_cfg.get("request_timeout_sec", 600)
    response = requests.post(url, headers=headers, json=payload, timeout=timeout)

    if not response.ok:
        raise RuntimeError(
            f"API request failed ({response.status_code}): {response.text[:500]}"
        )

    if stream:
        content_parts: list[str] = []
        for line in response.iter_lines():
            if line:
                decoded = line.decode("utf-8")
                if stream_output:
                    try:
                        sys.stderr.write(decoded + "\n")
                        sys.stderr.flush()
                    except OSError:
                        pass
                if decoded.startswith("data: "):
                    data_str = decoded[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        choices = chunk.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            part = delta.get("content") or delta.get("text", "")
                            if part:
                                content_parts.append(part)
                    except json.JSONDecodeError:
                        pass
        raw_content = "".join(content_parts)
    else:
        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            raise ValueError("API returned no choices")
        msg = choices[0].get("message", {})
        raw_content = msg.get("content") or msg.get("text", "") or ""

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(raw_content, encoding="utf-8")

    return extract_json_from_text(raw_content)


def _stream_output(
    pipe: Any,
    dest: Any,
    prefix: str = "",
    capture: list[str] | None = None,
) -> None:
    """Read lines from pipe and write to dest. Used for streaming subprocess output."""
    try:
        for line in iter(pipe.readline, ""):
            if line:
                if capture is not None:
                    capture.append(prefix + line)
                dest.write(prefix + line)
                dest.flush()
    except (ValueError, OSError):
        pass
    finally:
        try:
            pipe.close()
        except OSError:
            pass


def _heartbeat_thread(proc: subprocess.Popen[Any], stop: threading.Event) -> None:
    """Print periodic heartbeat while process runs. Stops when process exits or stop is set."""
    interval = _get_heartbeat_interval()
    elapsed = 0
    while not stop.is_set() and proc.poll() is None:
        time.sleep(interval)
        if stop.is_set() or proc.poll() is not None:
            break
        elapsed += interval
        msg = f"[PIKA] Agent running... ({elapsed}s)\n"
        try:
            sys.stderr.write(msg)
            sys.stderr.flush()
        except OSError:
            break


def _is_codex_output_schema_error(stderr_text: str) -> bool:
    """Return True when stderr indicates Codex rejected response_format schema."""
    haystack = (stderr_text or "").lower()
    return (
        "invalid schema for response_format" in haystack
        or "codex_output_schema" in haystack
        or "invalid_json_schema" in haystack
    )


def run_local_exec(
    prompt: str,
    output_schema_path: Path,
    workspace: Path,
    output_path: Path,
    *,
    command: str = "codex",
    timeout: int | None = 300,
    stream_output: bool = True,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    """Run local CLI (e.g. Codex exec) non-interactively and return parsed JSON output.

    Uses `codex exec` with --output-schema and --output-last-message.
    The schema passed to Codex is a compatibility-normalized copy; the original
    schema remains authoritative for internal jsonschema validation/retries.
    If Codex rejects the provided schema as invalid_json_schema, retries once
    without --output-schema and relies on local post-validation.
    Requires --yolo or similar for non-interactive runs (no approval prompts).

    When stream_output is True, Codex stdout/stderr are printed to the terminal
    in real time, and a periodic heartbeat ("Agent running... (30s)") is shown
    when Codex produces no output. Keeps visibility without flooding.

    Args:
        prompt: Full prompt text (system + user combined).
        output_schema_path: Path to JSON Schema file for expected output.
        workspace: Working directory for Codex (--cd).
        output_path: Path to write Codex's final message.
        command: Codex executable name.
        timeout: Max seconds to wait (default 300). None = no limit.
        stream_output: If True, stream Codex output to terminal and show heartbeat.
        reasoning_effort: Codex model_reasoning_effort (low, medium, high, xhigh). Passed as --config.

    Returns:
        Parsed JSON from Codex output.

    Raises:
        FileNotFoundError: If codex command not found.
        subprocess.CalledProcessError: If codex exits non-zero.
        ValueError: If output cannot be parsed as JSON.
    """
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    schema_str = ""
    if output_schema_path.exists():
        codex_schema_path = _prepare_codex_output_schema(output_schema_path, output_path)
        schema_str = str(codex_schema_path.resolve())
    workspace_str = str(workspace.resolve())

    exec_args_base = [
        "exec",
        "--cd", workspace_str,
        "--dangerously-bypass-approvals-and-sandbox",
        "--skip-git-repo-check",
        "--output-last-message", str(output_path),
    ]
    if reasoning_effort and reasoning_effort in ("low", "medium", "high", "xhigh"):
        # Codex expects value as JSON string, e.g. model_reasoning_effort='"high"'
        exec_args_base = exec_args_base + [
            "--config", f'model_reasoning_effort=\'"{reasoning_effort}"\''
        ]
    exec_args = list(exec_args_base)
    if schema_str:
        exec_args.extend(["--output-schema", schema_str])

    cmd = _build_local_cmd(command, exec_args)

    if stream_output:
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding=_SUBPROCESS_TEXT_ENCODING,
            errors=_SUBPROCESS_TEXT_ERRORS,
            cwd=workspace_str,
        )
        stop_heartbeat = threading.Event()
        t_stdout = threading.Thread(
            target=_stream_output,
            args=(proc.stdout, sys.stdout, "", stdout_lines),
            daemon=True,
        )
        t_stderr = threading.Thread(
            target=_stream_output,
            args=(proc.stderr, sys.stderr, "", stderr_lines),
            daemon=True,
        )
        t_heartbeat = threading.Thread(
            target=_heartbeat_thread,
            args=(proc, stop_heartbeat),
            daemon=True,
        )
        t_stdout.start()
        t_stderr.start()
        t_heartbeat.start()
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            stop_heartbeat.set()
            raise
        stop_heartbeat.set()
        t_stdout.join(timeout=1)
        t_stderr.join(timeout=1)
        t_heartbeat.join(timeout=1)
        returncode = proc.returncode
        stderr_captured = "".join(stderr_lines)
    else:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding=_SUBPROCESS_TEXT_ENCODING,
            errors=_SUBPROCESS_TEXT_ERRORS,
            timeout=timeout,
            cwd=workspace_str,
        )
        returncode = proc.returncode
        stderr_captured = proc.stderr or ""

    if (
        returncode != 0
        and schema_str
        and _is_codex_output_schema_error(stderr_captured)
    ):
        retry_cmd = _build_local_cmd(command, exec_args_base)
        proc = subprocess.run(
            retry_cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding=_SUBPROCESS_TEXT_ENCODING,
            errors=_SUBPROCESS_TEXT_ERRORS,
            timeout=timeout,
            cwd=workspace_str,
        )
        returncode = proc.returncode
        stderr_captured = proc.stderr or stderr_captured
        cmd = retry_cmd

    if returncode != 0:
        raise subprocess.CalledProcessError(
            returncode,
            cmd,
            output=None if stream_output else (proc.stdout if hasattr(proc, "stdout") else None),
            stderr=stderr_captured or "See terminal output above",
        )

    if not output_path.exists():
        if not stream_output and hasattr(proc, "stdout") and proc.stdout:
            raw = proc.stdout.strip()
            if raw:
                return extract_json_from_text(raw)
        raise ValueError("Codex produced no output and did not write output file")

    raw = output_path.read_text(encoding="utf-8")
    return extract_json_from_text(raw)
