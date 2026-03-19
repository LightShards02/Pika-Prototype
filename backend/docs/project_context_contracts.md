# PROJECT_CONTEXT.md Contract

**Single source of truth:** This document is parsed at runtime by `core/contracts.py` for preflight validation. Required sections are read from the table below. Do not duplicate these definitions in code.

Required for commands that use project context (plan, map, implement). The PROJECT_CONTEXT.md file must contain at least the following non-empty sections:

## Required Sections

| Section   | Required | Meaning |
|-----------|----------|---------|
| Purpose   | Yes      | Non-empty content under a heading containing "Purpose" (e.g. `### Purpose`). |
| Overview  | Yes      | Non-empty content under a heading containing "Overview" (e.g. `### Overview` or `### Workflow Overview`). |
| Workflow  | Yes      | Non-empty content under a heading containing "Workflow" (e.g. `### Workflow` or `### Workflow Overview`). |

- Section headings are matched case-insensitively.
- A single heading such as `### Workflow Overview` may satisfy both Overview and Workflow.
- Content is non-empty if it contains at least one non-whitespace character after the heading.
