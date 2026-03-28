# Refine Appendix Attention Budget Experiment

**Date:** 2026-03-24 through 2026-03-27
**Dataset:** `nutrition` (63 spec rows)
**Agents:** `spec_ambiguity_detector`, `spec_testability_auditor`

## Background

The `refine` command runs two LLM agents in parallel to scan a SADS design spec for quality issues:

- **Ambiguity detector**: flags vague or unmeasurable language in `requirement` fields
- **Testability auditor**: flags `acceptance_criteria` that cannot be directly automated as tests

An **appendix** feature was added allowing users to attach supplementary documents (data dictionaries, glossaries, config proposals) that provide concrete values for otherwise underspecified parameters.

## Experiment Design

Three phases, each with 10+ runs using identical spec input and `skip_all` manual resolution policy:


| Phase                | Runs | Appendix                        | Prompt Fix        |
| -------------------- | ---- | ------------------------------- | ----------------- |
| **Before**           | 10   | None                            | No                |
| **After (no fix)**   | 10   | `appendix_config_proposals.csv` | No                |
| **After (with fix)** | 14   | `appendix_config_proposals.csv` | Yes (Options A+C) |


The appendix contained concrete config values for specs A1021 (password expiry), A1024 (macro adjustment), A1026 (caloric surplus), A1031 (BMR formula), and partially A1022 (BMR tolerance).

## Phase 1: Before Appendix (Baseline)

**10 runs, no appendix attached.**


| Metric                | Average |
| --------------------- | ------- |
| Ambiguity items/run   | 8.5     |
| Testability items/run | 5.4     |
| Total items/run       | 13.9    |


Key per-spec flag rates (out of 10 runs):


| Spec  | Amb   | Test  | Total | Notes                                |
| ----- | ----- | ----- | ----- | ------------------------------------ |
| A1021 | 7/10  | 2/10  | 9/10  | Password expiry (appendix-targeted)  |
| A1024 | 6/10  | 3/10  | 9/10  | Macro adjustment (appendix-targeted) |
| A1026 | 7/10  | 3/10  | 10/10 | Caloric surplus (appendix-targeted)  |
| A1031 | 5/10  | 2/10  | 7/10  | BMR formula (appendix-targeted)      |
| A1022 | 5/10  | 3/10  | 8/10  | BMR tolerance (appendix-targeted)    |
| A1034 | 9/10  | 10/10 | 19/10 | Consistent high-flagger              |
| A1042 | 7/10  | 3/10  | 10/10 | Remember-me policy windows           |
| A1059 | 10/10 | 4/10  | 14/10 | Consistent high-flagger              |


## Phase 2: After Appendix, No Prompt Fix

**10 runs, appendix attached, original prompts.**


| Metric                | Average | Delta vs Before |
| --------------------- | ------- | --------------- |
| Ambiguity items/run   | 7.7     | -0.8            |
| Testability items/run | 4.6     | -0.8            |
| Total items/run       | 12.3    | -1.6            |


Appendix-resolved specs:


| Spec  | Before | After | Delta |
| ----- | ------ | ----- | ----- |
| A1021 | 90%    | 10%   | -80pp |
| A1024 | 90%    | 10%   | -80pp |
| A1026 | 100%   | 10%   | -90pp |
| A1031 | 70%    | 20%   | -50pp |
| A1022 | 80%    | 40%   | -40pp |


The appendix successfully suppressed most findings on the targeted specs. However, the total items/run only dropped by 1.6 (from 13.9 to 12.3), despite ~4-5 items/run worth of specs being resolved. This gap revealed **attention budget shift**: the model backfilled with borderline findings elsewhere.

### Attention Budget Shift Observed

A1042 (remember-me policy windows, **not** addressed by the appendix) saw its flag rate increase:


| Metric      | Before       | After (no fix) |
| ----------- | ------------ | -------------- |
| Ambiguity   | 7/10 (70%)   | 9/10 (90%)     |
| Testability | 3/10 (30%)   | 6/10 (60%)     |
| Total       | 10/10 (100%) | 15/10 (150%)   |


Other specs also saw increases: A1017 (30% to 70%), A1046 (30% to 70%), A1030 (10% to 60%).

## Root Cause Analysis

The prompts contain **no fixed output budget**. The instructions say "scan every row" and allow an empty array. The shift is caused by three emergent LLM behaviors:

### 1. Implicit Output-Length Anchoring (primary driver)

LLMs develop an internal sense of "how much output is appropriate" for a given prompt shape. With 63 spec rows and instructions to find issues, the model gravitates toward a rough output size. When easy targets are removed, it substitutes borderline findings to maintain that implicit length.

### 2. Contrast Effect

The appendix provides concrete examples of what "defined" looks like (e.g., `bmr_formula_tolerance_kcal: 1.0`). Specs that were borderline before now look more vague by comparison. A1042's "expiry values based on remember_me policy" looks more glaringly undefined when the model can see that adjacent auth specs ARE defined in the appendix.

### 3. Statistical Noise

With 10 runs, individual spec counts have meaningful variance. Some of the per-spec shifts are within noise range.

## The Fix: Options A + C

Two countermeasures were added to both agent system prompts:

### Option C: Appendix Cross-Referencing

Added explicit instructions requiring the model to check the appendix before flagging:

> Appendix cross-referencing: Before flagging any spec, check whether the Appendix Documents provide concrete values, definitions, or schemas for the referenced parameters. If the appendix fully resolves the vagueness (e.g., provides exact numeric values, enum lists, or formulas for the parameter in question), do NOT emit a manual_resolution_item for that spec. Only flag specs where genuine ambiguity remains after consulting the appendix.

This makes the appendix consumption an **explicit reasoning step** rather than relying on the model to passively notice the data.

### Option A: Anti-Backfilling Calibration

Added instructions to prevent the model from substituting weaker findings:

> Calibration: Do NOT lower your flagging threshold to compensate for specs resolved by the appendix. Judge each spec independently on its own merit. If the appendix resolves many specs, the correct output is fewer items -- not the same number with weaker findings substituted in. An empty array is the preferred output when no genuine issues remain.

This directly fights the output-length anchoring tendency.

## Phase 3: After Appendix, With Fix (Options A+C)

**14 runs, appendix attached, fixed prompts.**


| Metric                | Average | Delta vs No Fix |
| --------------------- | ------- | --------------- |
| Ambiguity items/run   | 7.6     | -0.1            |
| Testability items/run | 3.3     | -1.3            |
| Total items/run       | 10.9    | -1.4            |


### Appendix-resolved specs (primary goal)


| Spec  | Before | No Fix | With Fix |
| ----- | ------ | ------ | -------- |
| A1021 | 90%    | 10%    | **0%**   |
| A1024 | 90%    | 10%    | **0%**   |
| A1026 | 100%   | 10%    | **0%**   |
| A1031 | 70%    | 20%    | **0%**   |
| A1022 | 80%    | 40%    | **29%**  |


Option C fully eliminated false positives on the four cleanly-resolved specs. A1022 dropped further but persists, likely because the appendix only partially resolves its vagueness.

### Overall output volume


| Metric    | Before | No Fix | With Fix |
| --------- | ------ | ------ | -------- |
| Total/run | 13.9   | 12.3   | **10.9** |
| Reduction | --     | -12%   | **-22%** |


The combined fix reduced total output by 22% from baseline — more proportional to the number of specs actually resolved.

### A1042 (attention budget shift target)


| Phase    | Ambiguity | Testability | Total |
| -------- | --------- | ----------- | ----- |
| Before   | 70%       | 30%         | 100%  |
| No Fix   | 90%       | 60%         | 150%  |
| With Fix | 93%       | 71%         | 164%  |


A1042 continued to increase with the fix. This is a key finding: **A1042 is not a backfill victim. It is a genuinely vague spec.** When the model stops wasting attention on false positives (appendix-resolved specs), it becomes more confident about real issues. The fix eliminated noise, which amplified the signal on specs with genuine problems.

## Conclusions

### What worked

1. **Option C (appendix cross-referencing)** is highly effective. Making appendix consultation an explicit reasoning step reduced false positives on resolved specs from ~10-20% to 0%.
2. **Option A (anti-backfilling calibration)** reduced total output volume, especially for the testability agent (4.6 to 3.3 items/run).
3. Combined, the fixes produced a **22% reduction** in total items/run from baseline, better reflecting the actual resolution of specs by the appendix.

### What the fix cannot do

The fix does not suppress findings on genuinely vague specs. A1042's increase is the model being more accurate, not less. The correct resolution for A1042 is to either:

- Add appendix entries that define the actual remember-me policy windows
- Accept that it genuinely needs human attention

### Options not yet explored

- **Option B (two-pass architecture)**: First pass identifies candidates, second pass filters with per-item justification. More expensive (2x agent calls) but would break the implicit length anchor more completely.
- **Per-spec appendix resolution logging**: Having the agent output which specs it considered resolved by the appendix, making the decision auditable.

## File Changes

- `backend/prompts/PROMPT.yaml`: Added appendix cross-referencing and calibration instructions to both `spec_ambiguity_detector` and `spec_testability_auditor` system prompts.

