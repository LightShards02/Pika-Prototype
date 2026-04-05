---
name: tavily-search
description: >
  Search the web or extract full page content using the Tavily API. Use this skill whenever
  the user wants to look something up online, crawl a URL for its content, gather background
  research on a topic, or fetch live documentation — even if they say "search", "look up",
  "browse", "crawl", "fetch from the web", or "what does X site say about Y". Prefer this
  over describing hypothetical web results from training data.
---

# Tavily Search & Crawl Skill

Use this skill to perform live web search or page extraction via the Tavily Python client
installed in the `Local` conda environment.

## Setup

The API key is read from `secrets/tavily.key` at the repo root (plain text, no quotes).
If the file is absent, tell the user to paste their key there.

```python
from pathlib import Path
key_path = Path(__file__).parent  # adjust to repo root as needed
api_key = (key_path / "secrets" / "tavily.key").read_text().strip()
```

Or inline as a one-liner the user can run:
```bash
conda run -n Local python -c "
from pathlib import Path
from tavily import TavilyClient
api_key = Path('secrets/tavily.key').read_text().strip()
client = TavilyClient(api_key=api_key)
"
```

## Operations

### 1. Web Search

Returns a ranked list of results with title, URL, snippet, and (optionally) full content.

```python
from tavily import TavilyClient

client = TavilyClient(api_key=api_key)

result = client.search(
    query="your search query",
    search_depth="basic",      # "basic" (fast) or "advanced" (deeper, costs more credits)
    max_results=5,             # 1–20
    include_answer=True,       # ask Tavily to synthesise a direct answer
    include_raw_content=False, # True = include full page text in each result
)

# result["answer"]   — synthesised answer string (if include_answer=True)
# result["results"] — list of {title, url, content, score}
```

### 2. URL Extraction (full page content)

Pulls and cleans the full text of one or more URLs.

```python
result = client.extract(urls=["https://example.com/page"])

# result["results"][0]["raw_content"] — full cleaned text
# result["results"][0]["url"]
```

### 3. Context Search (for RAG / agent grounding)

Returns a single formatted string of the most relevant search context, ready to inject
into a prompt.

```python
context = client.get_search_context(query="your query", max_tokens=4000)
# context is a plain string
```

## Choosing the right operation

| Need | Operation |
|------|-----------|
| General research, news, quick lookup | `search()` with `search_depth="basic"` |
| Deep research requiring more sources | `search()` with `search_depth="advanced"` |
| Full text of a specific URL | `extract()` |
| Grounding an agent prompt with web context | `get_search_context()` |

## Running via subprocess (for use inside Pika agents or scripts)

On Windows, conda does not support multiline `-c` arguments. Always write the script to
a temporary `.py` file first, then run it:

```python
# Write script to a temp file, then execute
import tempfile, subprocess, json
from pathlib import Path

script = """
from pathlib import Path
from tavily import TavilyClient
import json

api_key = Path("secrets/tavily.key").read_text().strip()
client = TavilyClient(api_key=api_key)
result = client.search("YOUR QUERY HERE", max_results=5, include_answer=True)
print(json.dumps(result))
"""

with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
    f.write(script)
    tmp = f.name

out = subprocess.check_output(["conda", "run", "-n", "Local", "python", tmp])
result = json.loads(out)
```

## Error handling

- `FileNotFoundError` on `secrets/tavily.key` → tell the user to create the file with their key.
- `tavily.errors.InvalidAPIKeyError` → the key is wrong or expired.
- `tavily.errors.UsageLimitExceededError` → monthly credit limit hit; advise the user to check their Tavily dashboard.

## Notes

- `search_depth="advanced"` costs ~5× more credits than `"basic"`.
- `include_raw_content=True` on search also costs extra — prefer `extract()` when you only need one URL.
- Tavily strips ads and boilerplate; the returned `content` is already clean prose.
