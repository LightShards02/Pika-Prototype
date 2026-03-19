import { describe, it, expect } from 'vitest';
import {
  parseStderrLine,
  mapStderrToPhaseUpdates,
  computeProgress,
  transformAgentItems,
} from '../../src/services/pikaService';
import type { Phase } from '../../src/types';
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
});

// --- computeProgress ---

describe('computeProgress', () => {
  const makePhases = (statuses: Record<string, string>): Phase[] => [
    { id: 'R1', name: '', group: 'Refine', status: (statuses.R1 ?? 'pending') as Phase['status'], description: '', isBlocking: false },
    { id: 'R2', name: '', group: 'Refine', status: (statuses.R2 ?? 'pending') as Phase['status'], description: '', isBlocking: false },
    { id: 'R3', name: '', group: 'Refine', status: (statuses.R3 ?? 'pending') as Phase['status'], description: '', isBlocking: false },
    { id: 'R4', name: '', group: 'Refine', status: (statuses.R4 ?? 'pending') as Phase['status'], description: '', isBlocking: false },
    { id: 'I1', name: '', group: 'Implement', status: 'done' as const, description: '', isBlocking: false },
  ];

  it('all pending -> 0%', () => {
    expect(computeProgress(makePhases({}))).toBe(0);
  });

  it('R1 done -> 25%', () => {
    expect(computeProgress(makePhases({ R1: 'done' }))).toBe(25);
  });

  it('R1 done + R2 running -> 38%', () => {
    expect(computeProgress(makePhases({ R1: 'done', R2: 'running' }))).toBe(38);
  });

  it('all done -> 100%', () => {
    expect(computeProgress(makePhases({ R1: 'done', R2: 'done', R3: 'done', R4: 'done' }))).toBe(100);
  });

  it('ignores non-Refine phases', () => {
    // I1 is done but should be ignored
    const phases: Phase[] = [
      { id: 'I1', name: '', group: 'Implement', status: 'done', description: '', isBlocking: false },
    ];
    expect(computeProgress(phases)).toBe(0);
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
});
