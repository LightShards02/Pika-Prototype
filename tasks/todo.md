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
