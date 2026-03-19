/**
 * Pure-logic service layer for PIKA CLI ↔ desktop app communication.
 * No React imports — these are standalone utility functions.
 */

import type { PhaseStatus, RawAgentItem, RawAmbiguityItem, ResolutionItem, Spec } from '../types';

// --- Stderr parsing ---

export interface StderrEvent {
  step: string;
  status: string;
  detail: string;
}

/**
 * Parse a PIKA stderr line into a structured event.
 * Format: `[PIKA] Step: status — detail`
 */
export function parseStderrLine(line: string): StderrEvent | null {
  const match = line.match(/^\[PIKA\]\s+(.+?):\s+(\w+)\s+—\s+(.*)$/);
  if (!match) return null;
  return { step: match[1], status: match[2], detail: match[3] };
}

// --- Phase status mapping ---

export interface PhaseUpdate {
  phaseId: string;
  status: PhaseStatus;
}

/**
 * Map a stderr event to phase status updates.
 * Based on `_report_refine_step` calls in handlers/refine/impl.py.
 */
export function mapStderrToPhaseUpdates(event: StderrEvent): PhaseUpdate[] {
  const { step, status } = event;

  switch (step) {
    case 'Load':
      if (status === 'ok') return [{ phaseId: 'R1', status: 'done' }];
      if (status === 'failed') return [{ phaseId: 'R1', status: 'failed' }];
      return [];

    case 'Decomposition':
      if (status === 'running') return [{ phaseId: 'R2', status: 'running' }];
      if (status === 'ok' || status === 'skipped') return [{ phaseId: 'R2', status: 'done' }];
      if (status === 'blocked') return [{ phaseId: 'R2', status: 'blocked' }];
      if (status === 'failed') return [{ phaseId: 'R2', status: 'failed' }];
      return [];

    case 'Agents':
      if (status === 'running') return [
        { phaseId: 'R3', status: 'running' },
        { phaseId: 'R4', status: 'running' },
      ];
      if (status === 'failed') return [
        { phaseId: 'R3', status: 'failed' },
        { phaseId: 'R4', status: 'failed' },
      ];
      return [];

    case 'Refine':
      if (status === 'ok' || status === 'blocked') return [
        { phaseId: 'R3', status: 'done' },
        { phaseId: 'R4', status: 'done' },
      ];
      return [];

    default:
      return [];
  }
}

// --- Progress calculation ---

import type { Phase } from '../types';

/**
 * Compute progress percentage based on refine phase statuses (R1-R4 only).
 * Each completed phase = 25%. Running phase = 12.5%.
 */
export function computeProgress(phases: Phase[]): number {
  const refinePhases = phases.filter((p) => p.group === 'Refine');
  let progress = 0;
  for (const phase of refinePhases) {
    if (phase.status === 'done') progress += 25;
    else if (phase.status === 'running') progress += 12.5;
  }
  return Math.round(progress);
}

// --- Agent item transformation ---

function isAmbiguityItem(item: RawAgentItem): item is RawAmbiguityItem {
  return 'vague_phrases' in item;
}

/**
 * Transform raw agent items (from agent_review.json) into ResolutionItem[] for the UI.
 */
export function transformAgentItems(
  rawItems: RawAgentItem[],
  specs: Spec[],
): ResolutionItem[] {
  const specMap = new Map(specs.map((s) => [s.spec_id, s]));

  return rawItems.map((raw, index) => {
    const spec = specMap.get(raw.spec_id);
    const fieldValue = spec ? (spec as unknown as Record<string, string>)[raw.field] ?? '' : '';

    let type: string;
    let reason: string;

    if (isAmbiguityItem(raw)) {
      type = `Ambiguity: ${raw.title}`;
      reason = raw.vague_phrases.join('; ');
    } else {
      type = `Testability: ${raw.title}`;
      reason = raw.untestable_reason;
    }

    return {
      id: raw.item_id,
      spec_ids: [raw.spec_id],
      type,
      reason,
      currentText: fieldValue,
      suggestedText: raw.suggested_improvement,
      field: raw.field,
      itemIndex: index,
      options: raw.options.map((o) => ({
        id: o.option_id,
        label: o.label,
        description: o.effect,
      })),
    };
  });
}
