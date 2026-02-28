# Agent Provider Categories

PIKA supports three provider categories: **api**, **local**, and **stub**. Each has its own config section and parameters.

## Categories

| Category | Description | Example implementations |
|----------|-------------|-------------------------|
| **api** | Remote HTTP chat completions API | Kimi (NVIDIA), OpenAI, etc. |
| **local** | Local CLI subprocess | Codex exec |
| **stub** | Mock agent for testing | Deterministic stub outputs |

## Config Structure

### pika.yaml (PIKA-level defaults)

```yaml
# api: Remote chat completions API
api:
  url: https://integrate.api.nvidia.com/v1/chat/completions
  model: moonshotai/kimi-k2.5
  api_key_env: NVIDIA_API_KEY
  request_timeout_sec: 600
  map:      # Params for map command (lower temp for deterministic output)
    max_tokens: 32768
    temperature: 0.1
    top_p: 0.95
  default:  # Params for other commands
    max_tokens: 16384
    temperature: 0.7
    top_p: 1.0

# local: Local CLI subprocess
local:
  command: codex
  ps1_path_windows: ...   # Windows: path to .ps1 when installed via npm
  heartbeat_interval_sec: 30
  exec_timeout_sec: 600

# stub: Mock agent
stub:
  plan_proposed_sads: out/agent_artifacts/stub/plan_proposed_sads.csv
```

### Workspace config (agent section)

```yaml
agent:
  provider: stub   # stub | api | local
  schema_validation_retries: 3
  stream_output: true

  # When provider is local:
  local_command: codex

  # When provider is api:
  api_key_env: NVIDIA_API_KEY
  api_url: https://integrate.api.nvidia.com/v1/chat/completions
  api_model: moonshotai/kimi-k2.5
```

## Migration from [kimi, codex, stub]

| Old | New |
|-----|-----|
| `provider: kimi` | `provider: api` |
| `provider: codex` | `provider: local` |
| `provider: stub` | `provider: stub` (unchanged) |
| `codex_command` | `local_command` |
| `kimi_api_key_env` | `api_key_env` |
| `kimi_model` | `api_model` |
| `kimi_url` | `api_url` |
