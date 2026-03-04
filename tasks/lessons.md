# Lessons

- Session start: no prior lessons recorded.
- Pattern: Wording updates for drafting standards were previously interpreted too narrowly.
  Rule: When the user requests an exact standards sentence change, apply the requested phrasing verbatim to all active copies of that skill definition.
- Pattern: Cross-module interaction specs were not explicitly required to be split by module ownership.
  Rule: For any interaction across two modules, always create paired specs: sender-side trigger/payload spec and receiver-side handling/response spec.
- Pattern: Subunit values were too granular and fragmented across related rows in the same workflow.
  Rule: Use generalized subunit buckets and assign the same subunit value to all rows that belong to one workflow part (for example `user_management`, `history_management`, `export_management`).
