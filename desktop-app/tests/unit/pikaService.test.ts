import { describe, it, expect } from 'vitest';
import {
  parseStderrLine,
  mapStderrToPhaseUpdates,
  computeProgress,
  transformAgentItems,
  transformImplementItems,
} from '../../src/services/pikaService';
import type { Phase, RawAgentItem, RawDecompositionGateItem } from '../../src/types';
import { stderrLines, mockSpecs, mockAmbiguityItem, mockTestabilityItem } from '../fixtures/testData';

// --- parseStderrLine ---

describe('parseStderrLine', () => {
  it('parses a valid PIKA stderr line', () => {
    const result = parseStderrLine(stderrLines.loadOk);
    expect(result).toEqual({ step: 'Load', status: 'ok', detail: 'Loaded 2 specs' });
  });

  it('parses multi-word step name', () => {
    const result = parseStderrLine(stderrLines.decompRunning);
    expect(result).toEqual({
      step: 'Decomposition',
      status: 'running',
      detail: 'Analyzing spec relationships',
    });
  });

  it('returns null for line without [PIKA] prefix', () => {
    expect(parseStderrLine(stderrLines.invalidLine)).toBeNull();
  });

  it('returns null for empty string', () => {
    expect(parseStderrLine('')).toBeNull();
  });

  it('returns null for malformed PIKA line', () => {
    expect(parseStderrLine(stderrLines.malformed)).toBeNull();
  });

  it('parses all standard stderr lines correctly', () => {
    const validLines = [
      stderrLines.loadOk,
      stderrLines.decompRunning,
      stderrLines.decompDone,
      stderrLines.agentsRunning,
      stderrLines.refineOk,
      stderrLines.refineBlocked,
      stderrLines.loadFailed,
    ];
    for (const line of validLines) {
      expect(parseStderrLine(line)).not.toBeNull();
    }
  });
});

// --- mapStderrToPhaseUpdates ---

describe('mapStderrToPhaseUpdates', () => {
  it('Load ok -> R1 done', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Load', status: 'ok', detail: '' })).toEqual([
      { phaseId: 'R1', status: 'done' },
    ]);
  });

  it('Load failed -> R1 failed', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Load', status: 'failed', detail: '' })).toEqual([
      { phaseId: 'R1', status: 'failed' },
    ]);
  });

  it('Decomposition running -> R2 running', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Decomposition', status: 'running', detail: '' })).toEqual([
      { phaseId: 'R2', status: 'running' },
    ]);
  });

  it('Decomposition ok -> R2 done', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Decomposition', status: 'ok', detail: '' })).toEqual([
      { phaseId: 'R2', status: 'done' },
    ]);
  });

  it('Decomposition skipped -> R2 done', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Decomposition', status: 'skipped', detail: '' })).toEqual([
      { phaseId: 'R2', status: 'done' },
    ]);
  });

  it('Decomposition blocked -> R2 blocked', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Decomposition', status: 'blocked', detail: '' })).toEqual([
      { phaseId: 'R2', status: 'blocked' },
    ]);
  });

  it('Agents running -> R3+R4 running', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Agents', status: 'running', detail: '' })).toEqual([
      { phaseId: 'R3', status: 'running' },
      { phaseId: 'R4', status: 'running' },
    ]);
  });

  it('Agents failed -> R3+R4 failed', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Agents', status: 'failed', detail: '' })).toEqual([
      { phaseId: 'R3', status: 'failed' },
      { phaseId: 'R4', status: 'failed' },
    ]);
  });

  it('Refine ok -> R3+R4 done', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Refine', status: 'ok', detail: '' })).toEqual([
      { phaseId: 'R3', status: 'done' },
      { phaseId: 'R4', status: 'done' },
    ]);
  });

  it('Refine blocked -> R3+R4 done', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Refine', status: 'blocked', detail: '' })).toEqual([
      { phaseId: 'R3', status: 'done' },
      { phaseId: 'R4', status: 'done' },
    ]);
  });

  it('Unknown step -> empty array', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Unknown', status: 'ok', detail: '' })).toEqual([]);
  });

  it('Known step with unknown status -> empty array', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Load', status: 'running', detail: '' })).toEqual([]);
  });

  // --- Implement command: Load disambiguation ---

  it('Load ok (implement) -> I1 running', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Load', status: 'ok', detail: '' }, 'implement')).toEqual([
      { phaseId: 'I1', status: 'running' },
    ]);
  });

  it('Load failed (implement) -> I1 failed', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Load', status: 'failed', detail: '' }, 'implement')).toEqual([
      { phaseId: 'I1', status: 'failed' },
    ]);
  });

  it('Load ok (no command) -> R1 done (backward compat)', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Load', status: 'ok', detail: '' })).toEqual([
      { phaseId: 'R1', status: 'done' },
    ]);
  });

  // --- Implement steps: I1 (Normalize Config) ---

  it('Workspace ok -> I1 running', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Workspace', status: 'ok', detail: '' })).toEqual([
      { phaseId: 'I1', status: 'running' },
    ]);
  });

  it('Catalog ok -> I1 running', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Catalog', status: 'ok', detail: '' })).toEqual([
      { phaseId: 'I1', status: 'running' },
    ]);
  });

  it('Appendix ok -> I1 done', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Appendix', status: 'ok', detail: '' })).toEqual([
      { phaseId: 'I1', status: 'done' },
    ]);
  });

  it('Appendix failed -> I1 failed', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Appendix', status: 'failed', detail: '' })).toEqual([
      { phaseId: 'I1', status: 'failed' },
    ]);
  });

  // --- Implement steps: I5 (Run Unified Planner) ---

  it('Planner running -> I5 running', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Planner', status: 'running', detail: '' })).toEqual([
      { phaseId: 'I5', status: 'running' },
    ]);
  });

  it('Planner ok -> I5 done', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Planner', status: 'ok', detail: '' })).toEqual([
      { phaseId: 'I5', status: 'done' },
    ]);
  });

  it('Planner failed -> I5 failed', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Planner', status: 'failed', detail: '' })).toEqual([
      { phaseId: 'I5', status: 'failed' },
    ]);
  });

  it('Planner blocked -> I7 blocked', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Planner', status: 'blocked', detail: '' })).toEqual([
      { phaseId: 'I7', status: 'blocked' },
    ]);
  });

  // --- Implement steps: I7 (Gate: Planner Blockers) ---

  it('Plan validation ok -> I7 running', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Plan validation', status: 'ok', detail: '' })).toEqual([
      { phaseId: 'I7', status: 'running' },
    ]);
  });

  it('Plan validation blocked -> I7 blocked', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Plan validation', status: 'blocked', detail: '' })).toEqual([
      { phaseId: 'I7', status: 'blocked' },
    ]);
  });

  it('Required field coverage check ok -> I7 done', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Required field coverage check', status: 'ok', detail: '' })).toEqual([
      { phaseId: 'I7', status: 'done' },
    ]);
  });

  // --- Implement steps: I14 (Construct Batch Plan) ---

  it('Batch plan ok -> I14 running', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Batch plan', status: 'ok', detail: '' })).toEqual([
      { phaseId: 'I14', status: 'running' },
    ]);
  });

  it('Dependency context edge check ok -> I14 done', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Dependency context edge check', status: 'ok', detail: '' })).toEqual([
      { phaseId: 'I14', status: 'done' },
    ]);
  });

  it('Dependency context edge check failed -> I14 failed', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Dependency context edge check', status: 'failed', detail: '' })).toEqual([
      { phaseId: 'I14', status: 'failed' },
    ]);
  });

  // --- Batch step: B-EXEC ---

  it('Execute running -> B-EXEC running', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Execute', status: 'running', detail: '' })).toEqual([
      { phaseId: 'B-EXEC', status: 'running' },
    ]);
  });

  it('Execute ok -> B-EXEC done', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Execute', status: 'ok', detail: '' })).toEqual([
      { phaseId: 'B-EXEC', status: 'done' },
    ]);
  });

  it('Execute failed -> B-EXEC failed', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Execute', status: 'failed', detail: '' })).toEqual([
      { phaseId: 'B-EXEC', status: 'failed' },
    ]);
  });

  it('Execute blocked -> B-EXEC blocked', () => {
    expect(mapStderrToPhaseUpdates({ step: 'Execute', status: 'blocked', detail: '' })).toEqual([
      { phaseId: 'B-EXEC', status: 'blocked' },
    ]);
  });
});

// --- computeProgress ---

describe('computeProgress', () => {
  const makePhases = (statuses: Record<string, string>): Phase[] => [
    { id: 'R1', name: '', group: 'Refine', status: (statuses.R1 ?? 'pending') as Phase['status'], description: '', isBlocking: false },
    { id: 'R2', name: '', group: 'Refine', status: (statuses.R2 ?? 'pending') as Phase['status'], description: '', isBlocking: false },
    { id: 'R3', name: '', group: 'Refine', status: (statuses.R3 ?? 'pending') as Phase['status'], description: '', isBlocking: false },
    { id: 'R4', name: '', group: 'Refine', status: (statuses.R4 ?? 'pending') as Phase['status'], description: '', isBlocking: false },
    { id: 'I1', name: '', group: 'Implement', status: (statuses.I1 ?? 'pending') as Phase['status'], description: '', isBlocking: false },
    { id: 'I5', name: '', group: 'Implement', status: (statuses.I5 ?? 'pending') as Phase['status'], description: '', isBlocking: false },
    { id: 'I7', name: '', group: 'Implement', status: (statuses.I7 ?? 'pending') as Phase['status'], description: '', isBlocking: false },
    { id: 'I14', name: '', group: 'Implement', status: (statuses.I14 ?? 'pending') as Phase['status'], description: '', isBlocking: false },
    { id: 'B-EXEC', name: '', group: 'Batch', status: (statuses['B-EXEC'] ?? 'pending') as Phase['status'], description: '', isBlocking: false },
  ];

  // --- Refine command (default) ---

  it('all pending (refine) -> 0%', () => {
    expect(computeProgress(makePhases({}), 'refine')).toBe(0);
  });

  it('R1 done -> 25%', () => {
    expect(computeProgress(makePhases({ R1: 'done' }), 'refine')).toBe(25);
  });

  it('R1 done + R2 running -> 38%', () => {
    expect(computeProgress(makePhases({ R1: 'done', R2: 'running' }), 'refine')).toBe(38);
  });

  it('all done (refine) -> 100%', () => {
    expect(computeProgress(makePhases({ R1: 'done', R2: 'done', R3: 'done', R4: 'done' }), 'refine')).toBe(100);
  });

  it('defaults to refine when command omitted', () => {
    expect(computeProgress(makePhases({ R1: 'done' }))).toBe(25);
  });

  it('ignores non-scoped phases (refine ignores I1)', () => {
    expect(computeProgress(makePhases({ I1: 'done' }), 'refine')).toBe(0);
  });

  // --- Blocked/failed weighting ---

  it('R1 done + R2 blocked -> 50% (blocked = full weight)', () => {
    expect(computeProgress(makePhases({ R1: 'done', R2: 'blocked' }), 'refine')).toBe(50);
  });

  it('R1 done + R2 failed -> 38% (failed = half weight)', () => {
    expect(computeProgress(makePhases({ R1: 'done', R2: 'failed' }), 'refine')).toBe(38);
  });

  it('blocked phases do not cause backward progress vs running', () => {
    const runningProgress = computeProgress(makePhases({ R1: 'done', R2: 'running' }), 'refine');
    const blockedProgress = computeProgress(makePhases({ R1: 'done', R2: 'blocked' }), 'refine');
    expect(blockedProgress).toBeGreaterThanOrEqual(runningProgress);
  });

  // --- Implement command ---

  it('all done (implement) -> 100%', () => {
    expect(computeProgress(
      makePhases({ I1: 'done', I5: 'done', I7: 'done', I14: 'done', 'B-EXEC': 'done' }),
      'implement',
    )).toBe(100);
  });

  it('I1 done + I5 running (implement) -> 30%', () => {
    expect(computeProgress(makePhases({ I1: 'done', I5: 'running' }), 'implement')).toBe(30);
  });

  it('ignores refine phases in implement scope', () => {
    expect(computeProgress(makePhases({ R1: 'done', R2: 'done', R3: 'done', R4: 'done' }), 'implement')).toBe(0);
  });

  // --- Batch command ---

  it('B-EXEC done (batch) -> 100%', () => {
    expect(computeProgress(makePhases({ 'B-EXEC': 'done' }), 'batch')).toBe(100);
  });

  it('B-EXEC running (batch) -> 50%', () => {
    expect(computeProgress(makePhases({ 'B-EXEC': 'running' }), 'batch')).toBe(50);
  });
});

// --- transformAgentItems ---

describe('transformAgentItems', () => {
  it('transforms ambiguity item correctly', () => {
    const result = transformAgentItems([mockAmbiguityItem], mockSpecs);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe('AMB-001');
    expect(result[0].type).toContain('Ambiguity');
    expect(result[0].reason).toBe('authenticate users');
    expect(result[0].currentText).toBe('System shall authenticate users via OAuth2');
    expect(result[0].suggestedText).toBe('System shall authenticate users via OAuth2 with PKCE flow');
  });

  it('transforms testability item correctly', () => {
    const result = transformAgentItems([mockTestabilityItem], mockSpecs);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe('TST-001');
    expect(result[0].type).toContain('Testability');
    expect(result[0].reason).toBe('No measurable criterion for "all visible rows"');
    expect(result[0].currentText).toBe('Downloaded file contains all visible rows');
  });

  it('maps options correctly', () => {
    const result = transformAgentItems([mockAmbiguityItem], mockSpecs);
    expect(result[0].options).toEqual([
      { id: 'accept_suggestion', label: 'Accept Suggestion', description: 'Replace with suggested text' },
      { id: 'let_agent_edit', label: 'Let Agent Edit', description: 'Agent will rewrite' },
      { id: 'skip', label: 'Skip', description: 'Keep original' },
    ]);
  });

  it('handles missing spec gracefully', () => {
    const result = transformAgentItems([mockAmbiguityItem], []);
    expect(result[0].currentText).toBe('');
  });

  it('sets itemIndex from array position', () => {
    const result = transformAgentItems([mockAmbiguityItem, mockTestabilityItem], mockSpecs);
    expect(result[0].itemIndex).toBe(0);
    expect(result[1].itemIndex).toBe(1);
  });

  it('transforms v2 single-concern merged item when format_version is omitted (gate JSON)', () => {
    const v2single: RawAgentItem = {
      item_id: 'AMB-001',
      spec_id: 'SPEC-001',
      is_compound: false,
      title: 'Vague authentication requirement',
      concerns: [
        {
          item_id: 'AMB-001',
          agent_type: 'ambiguity',
          title: 'Vague authentication requirement',
          field: 'requirement',
          suggested_improvement: 'System shall authenticate users via OAuth2 with PKCE flow',
          vague_phrases: ['authenticate users'],
        },
      ],
      options: mockAmbiguityItem.options,
    };
    const result = transformAgentItems([v2single], mockSpecs);
    expect(result[0].reason).toBe('authenticate users');
    expect(result[0].currentText).toBe('System shall authenticate users via OAuth2');
    expect(result[0].isCompound).toBe(false);
    expect(result[0].concerns).toHaveLength(1);
  });

  it('transforms decomposition split_candidate rows', () => {
    const decomp: RawDecompositionGateItem = {
      item_id: 'DECOMP-SPLIT-SPEC-001',
      title: 'Spec may have mixed responsibilities: SPEC-001',
      spec_id: 'SPEC-001',
      issue_kind: 'split_candidate',
      reason: 'High topic variance detected.',
      options: [
        { option_id: 'let_agent_edit', label: 'Let agent split', effect: 'Calls spec_editor.' },
        { option_id: 'skip', label: 'Keep as-is', effect: 'Leaves unchanged.' },
      ],
    };
    const result = transformAgentItems([decomp], mockSpecs);
    expect(result[0].spec_ids).toEqual(['SPEC-001']);
    expect(result[0].reason).toBe('High topic variance detected.');
    expect(result[0].options).toHaveLength(2);
    expect(result[0].isCompound).toBe(false);
  });
});

describe('transformImplementItems', () => {
  it('maps evidence_refs to spec_ids for highlighting', () => {
    const result = transformImplementItems([
      {
        item_id: 'issue-1',
        title: 'Dependency gap',
        question: 'Which module owns the DTO?',
        blocking_reason: 'Planner could not infer ownership.',
        options: [{ option_id: 'skip', label: 'Skip', effect: 'Defer' }],
        evidence_refs: ['A1', 'B2'],
      },
    ]);
    expect(result[0].spec_ids).toEqual(['A1', 'B2']);
    expect(result[0].isCompound).toBe(false);
    expect(result[0].concerns).toEqual([]);
  });

  it('tolerates missing or empty options (validation-only items)', () => {
    const result = transformImplementItems([
      {
        item_id: 'val-1',
        title: 'Contract edit required',
        question: 'Fix duplicate field in contract X.',
        blocking_reason: 'Duplicate field name.',
        options: [],
      },
    ]);
    expect(result[0].options).toEqual([]);
  });
});
