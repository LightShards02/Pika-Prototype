# TODO

Active session checklist for multi-step work. Longer historical logs were moved to `archive/todo/Apr22/todo.md`.

- [x] Review `PROJECT_CONTEXT.md`, `AGENTS.md`, and relevant lessons before proposing architecture.
- [x] Define the fixed PIKA constraints that must hold inside a larger regulated workflow.
- [x] Brainstorm an end-to-end regulated SDLC/test/delivery workflow with PIKA inserted at concrete control points.
- [x] Summarize recommended platform extensions, operating model options, and open design questions.

Review:
- Brainstorm anchored to current PIKA constraints from `PROJECT_CONTEXT.md`: deterministic document/code application, schema-validated agent outputs, blocking manual resolution, and CLI/desktop-app operator surfaces.

Current session:
- [x] Locate the current presentation source and confirm the editable artifact.
- [x] Inspect the existing slide deck structure so retained slides stay consistent.
- [x] Redesign the deck to the requested slide 0-9 flow with simple visuals and placeholders.
- [x] Verify the updated deck file structure and summarize the new slide content.

Review:
- Generated `PIKA-Executive-Overview-redesigned.pptx` from the current deck, kept timestamped backups, and verified the revised slides by exporting all 10 slides through PowerPoint COM to PNG previews under `out/deck-preview/`.

Current session:
- [x] Confirm that the current "page 9" corresponds to the `9 / 10` slide in the redesigned deck.
- [x] Replace only the current page 9 content with brief descriptions of the CLI, desktop app, and VS Code IDE plugin.
- [x] Verify the updated page 9 render without changing any other slide.

Review:
- Created `PIKA-Executive-Overview-redesigned-page9-updated.pptx` as a slide-9-only derivative because the original redesigned deck file was locked for in-place overwrite. Verified the updated `9 / 10` slide by exporting preview images under `out/deck-preview-page9-update/`.

Current session:
- [x] Recover only page 4 of the current redesigned deck to match the provided screenshot.
- [x] Verify the recovered page 4 render without changing any other slide.

Review:
- Created a page-4-only derivative from the current redesigned deck and verified the recovered slide render under `out/deck-preview-page4-recovery/Slide4.PNG`.

Current session — Refine consolidation + Nairb-derived improvements (#1, #4 scoped, #5):
- [ ] M1: Author `spec_quality_auditor_output.schema.json` (full mode) and `spec_quality_auditor_triage_output.schema.json` (triage mode). New MR-item shape carries `concern_kinds[]`, `consequence_class`, `worst_case`, optional `verification_method`, optional `vague_phrases`, optional `untestable_reason`, optional `suggested_test_type`. Single-spec items only.
- [ ] M2: Add `spec_quality_auditor` block to `prompts/PROMPT.yaml`. Lift ambiguity detector's cross-spec reference resolution and Step 2 appendix-consistency rules into Stage 1 under `concern_kind: unresolvable_reference`. Add #5 implementation_leak vs legitimate_constraint split. Add #1 consequence_class + worst_case demand on every MR item. Strengthen AC honesty rule (compensates for skipping #3). Delete `spec_ambiguity_detector` and `spec_testability_enricher` blocks once tests pass.
- [ ] M3: Rename pika.yaml `commands.refine.prompt_names.ambiguity_detector` and `testability_enricher` → single `quality_auditor`. Update `schema_map`. Refactor `_run_refine_agents` to single-agent N-replica flow. Replace `_merge_all_items` compound-merger logic with a flat group-by-spec-id pass. Surface severity rollup in `_report_refine_step`. Resume path raises `ResumeError` on legacy cached outputs (no compat shim).
- [ ] M4: Grep for `spec_change_merger` callers; if only the compound-options flow uses it, delete the agent + prompt + config key. Update `core/resolution.py` resolution-template generator to surface `consequence_class` and `worst_case` inline.
- [ ] M5: Update `tests/test_refine_handler.py` config asserts. Add tests: `implementation_leak` suggests removal not rewrite; `legitimate_constraint` populates `verification_method`; `consequence_class` propagates to `agent_review.json`; resume on legacy schema raises ResumeError. Update `docs/refine-checks-execution-order.md` and `AGENTS.md`.
- [ ] Smoke: run an end-to-end `pika refine` against a real workspace before declaring the consolidation done (model-invocation lesson).

---

Current session — REST API migration (phase-as-independent-run):
- [x] M1: REST API skeleton + phase catalog + `format.normalize` end-to-end. Merged in `287e009`.
- [x] M2a: extract refine phase functions. Merged in `4e6d984`.
- [x] M2b: REST surface for refine phases (SSE + manual-block + lock + cancel). Merged in `f9baf2a`.
- [x] M3: `implement.unified-planner` REST phase. Merged in `65bccd5`.
- [x] M4: `map.match` REST phase + central path-traversal hardening across M2a/M3/M4 cache-replay paths. Merged in `3c95f74` (merge `a9bc092`). 11 handler tests + 9 API tests including live SSE progress assertion. 5 review rounds — each found a real Tier-1 (traversal, exception wrap, subunits-only post-merge equivalence, SSE coverage).
- [skip] M5: login OAuth — skipped per user direction.
- [x] M6: workspace memory layer (4-file: memory.md, lessons.md, tasks.md, gaps.md). Merged in `31f22f2` (merge `3990c81`). 15 memory_store + 9 workspace_memory API + 6 state_read API + 3 phase injection + 1 /edit memory injection = 34 new tests, plus 14 prompts wired with `{{memory}}` placeholder. Per-workspace lock on PUT writes. Bootstrap on POST /v1/workspaces (idempotent). `/state/{path}` with traversal/directory/missing/file distinctions. 4 review rounds; final 2 caught real bugs (lock + content-type + directory target), pushed back on Codex's "out of scope" cross-handler injection (Codex accepted in r3/r4 as justified). Codex reviewer infrastructure under `backend/scripts/codex_review/` now tracked in main (committed `d6e8cab`).

Polish-pass follow-ups deferred (Codex non-blockings):
- [ ] `backend/api/phase_runs.py` registry reads use no lock while writes are locked.
- [ ] `RuntimeContext.config_path` hardcoded to `<workspace>/config.yaml`.
- [ ] `_load_stage_file` mtime heuristic → deterministic filename priority.
- [ ] `progress_dropped` dedicated SSE event type.
- [ ] `_step_enabled` / `_step_value` local duplication in M3 phase module.
- [ ] Trim verbose docstring in `handlers/implement/planner/__init__.py`.
- [ ] Promote `_get_map_config` / `_get_prompt_name` to public aliases in `handlers/map.py` (same pattern as M2a's `apply_structural_edits` and M2b's `invoke_spec_editor`).

Per user direction: `plan.design`, `resolve_plan.organize`, `review.audit`, and the legacy `/resolve` REST surface are explicitly out of scope. Remaining milestones: M5 login OAuth (small), M6 memory layer, M7-M8 chat orchestrator (router + curator), M9 desktop cutover, M10 hardening + OpenAPI + compaction.
