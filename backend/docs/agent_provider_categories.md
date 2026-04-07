# Agent Provider Categories

PIKA supports two provider categories: **local** and **stub**. Each has its own config section and parameters.

## Categories

| Category | Description | Example implementations |
|----------|-------------|-------------------------|
| **local** | Loca in-process LLM agent | Anthropic Messages API, OpenAI-compatible API, or ChatGPT Codex via Loca |
| **stub** | Mock agent for testing | Deterministic stub outputs |

## Config Structure

### pika.yaml (PIKA-level defaults)

```yaml
# local: Loca in-process agent
local:
  provider_sub: openai-codex   # openai | anthropic | openai-codex
  model:
    default:
      name: gpt-5.3-codex
      reasoning_effort: medium
      temperature: null
      top_p: null
      web_search: false
      model_verbosity: null
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
  # default:
  #   name: gpt-5-codex
  # provider_sub: openai-codex  # workspace key matches pika.yaml local.provider_sub
  # implement_from_specs:
  #   name: gpt-5.3-codex-spark
  #   reasoning_effort: xhigh
```
