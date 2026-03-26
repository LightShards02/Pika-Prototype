# Agent Provider Categories

PIKA supports two provider categories: **local** and **stub**. Each has its own config section and parameters.

## Categories

| Category | Description | Example implementations |
|----------|-------------|-------------------------|
| **local** | Loca in-process LLM agent | OpenAI Codex, OpenAI API via Loca |
| **stub** | Mock agent for testing | Deterministic stub outputs |

## Config Structure

### pika.yaml (PIKA-level defaults)

```yaml
# local: Loca in-process agent
local:
  command: codex
  provider_sub: openai-codex   # openai (API key) or openai-codex (ChatGPT OAuth)
  model:
    default: gpt-5.3-codex
  exec_timeout_sec: 600

# stub: Mock agent
stub:
  plan_proposed_sads: out/agent_artifacts/stub/plan_proposed_sads.csv
```

### Workspace config (agent section)

```yaml
agent:
  provider: stub   # stub | local
  schema_validation_retries: 3
  stream_output: true

  # When provider is local (Loca):
  # local_model: gpt-5-codex
  # local_provider: openai-codex
  # reasoning_effort:
  #   default: medium
```
