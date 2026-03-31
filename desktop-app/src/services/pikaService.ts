/**
 * Pure-logic service layer for PIKA CLI ↔ desktop app communication.
 * No React imports — these are standalone utility functions.
 */

import type { Phase, PhaseStatus, PikaCommand, RawAgentItem, RawAmbiguityItem, RawImplementItem, ResolutionItem, Spec } from '../types';

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
 *
 * Refine steps come from `_report_refine_step` in handlers/refine/impl.py.
 * Implement/batch steps come from `_report_implement_phase` in handlers/implement/helpers.py.
 *
 * The `command` parameter disambiguates overlapping step names (e.g., "Load"
 * is emitted by both refine and implement).
 */
export function mapStderrToPhaseUpdates(
  event: StderrEvent,
  command?: PikaCommand,
): PhaseUpdate[] {
  const { step, status } = event;

  switch (step) {
    // ── Refine steps ──

    case 'Load':
      if (command === 'implement') {
        if (status === 'ok' || status === 'warning') return [{ phaseId: 'I1', status: 'running' }];
        if (status === 'failed') return [{ phaseId: 'I1', status: 'failed' }];
        return [];
      }
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

    // ── Implement steps: I1 (Normalize Config) ──

    case 'Workspace':
      if (status === 'ok') return [{ phaseId: 'I1', status: 'running' }];
      return [];

    case 'Catalog':
      if (status === 'ok' || status === 'warning') return [{ phaseId: 'I1', status: 'running' }];
      return [];

    case 'Appendix':
      if (status === 'ok' || status === 'warning') return [{ phaseId: 'I1', status: 'done' }];
      if (status === 'failed') return [{ phaseId: 'I1', status: 'failed' }];
      return [];

    // ── Implement steps: I5 (Run Unified Planner) ──

    case 'Planner':
      if (status === 'running') return [{ phaseId: 'I5', status: 'running' }];
      if (status === 'ok' || status === 'skipped') return [{ phaseId: 'I5', status: 'done' }];
      if (status === 'failed') return [{ phaseId: 'I5', status: 'failed' }];
      if (status === 'blocked') return [{ phaseId: 'I7', status: 'blocked' }];
      return [];

    // ── Implement steps: I7 (Gate: Planner Blockers) ──

    case 'Plan validation':
      if (status === 'ok') return [{ phaseId: 'I7', status: 'running' }];
      if (status === 'failed') return [{ phaseId: 'I7', status: 'failed' }];
      if (status === 'blocked') return [{ phaseId: 'I7', status: 'blocked' }];
      return [];

    case 'Contract field check':
      if (status === 'ok') return [{ phaseId: 'I7', status: 'running' }];
      if (status === 'blocked') return [{ phaseId: 'I7', status: 'blocked' }];
      return [];

    case 'Required field coverage check':
      if (status === 'ok') return [{ phaseId: 'I7', status: 'done' }];
      if (status === 'blocked') return [{ phaseId: 'I7', status: 'blocked' }];
      return [];

    case 'Spec issue escalation':
      if (status === 'blocked') return [{ phaseId: 'I7', status: 'blocked' }];
      return [];

    // ── Implement steps: I14 (Construct Batch Plan) ──

    case 'Batch plan':
      if (status === 'ok') return [{ phaseId: 'I14', status: 'running' }];
      if (status === 'failed') return [{ phaseId: 'I14', status: 'failed' }];
      return [];

    case 'Briefs':
      if (status === 'ok') return [{ phaseId: 'I14', status: 'running' }];
      return [];

    case 'Brief validation':
      if (status === 'ok') return [{ phaseId: 'I14', status: 'running' }];
      if (status === 'failed') return [{ phaseId: 'I14', status: 'failed' }];
      return [];

    case 'Dependency context edge check':
      if (status === 'ok') return [{ phaseId: 'I14', status: 'done' }];
      if (status === 'failed') return [{ phaseId: 'I14', status: 'failed' }];
      return [];

    // ── Batch step: B-EXEC (Batch Execution) ──

    case 'Execute':
      if (status === 'running') return [{ phaseId: 'B-EXEC', status: 'running' }];
      if (status === 'ok' || status === 'skipped') return [{ phaseId: 'B-EXEC', status: 'done' }];
      if (status === 'failed') return [{ phaseId: 'B-EXEC', status: 'failed' }];
      if (status === 'blocked') return [{ phaseId: 'B-EXEC', status: 'blocked' }];
      return [];

    default:
      return [];
  }
}

// --- Progress calculation ---

/**
 * Return the ordered list of phase IDs that will be active for this run,
 * based on the options the user selected on the home page.
 */
export function getEnabledPhaseIds(
  refineEnabled: boolean,
  implementEnabled: boolean,
  decompositionEnabled: boolean,
): string[] {
  const ids: string[] = [];
  if (refineEnabled) {
    ids.push('R1');
    if (decompositionEnabled) ids.push('R2');
    ids.push('R3', 'R4');
  }
  if (implementEnabled) {
    ids.push('I1', 'I5', 'I7', 'I14', 'B-EXEC');
  }
  return ids;
}

/**
 * Compute progress percentage across all enabled phases in the pipeline.
 *
 * Each phase in `enabledPhaseIds` carries equal weight.
 * Status weights:
 *   done / blocked → 100%  (blocked = work done, waiting for user)
 *   running / failed → 50% (work in progress or attempted)
 *   pending → 0%
 */
export function computeProgress(
  phases: Phase[],
  enabledPhaseIds: string[],
): number {
  const targetPhases = phases.filter((p) => enabledPhaseIds.includes(p.id));
  if (targetPhases.length === 0) return 0;

  const phaseWeight = 100 / targetPhases.length;
  let progress = 0;

  for (const phase of targetPhases) {
    if (phase.status === 'done' || phase.status === 'blocked') {
      progress += phaseWeight;
    } else if (phase.status === 'running' || phase.status === 'failed') {
      progress += phaseWeight * 0.5;
    }
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

/**
 * Transform raw implement gate items (from unified_planner.json etc.) into ResolutionItem[].
 * Implement items have a different schema from refine items: no spec_id/field,
 * but have title, question, blocking_reason, and options.
 */
export function transformImplementItems(
  rawItems: RawImplementItem[],
): ResolutionItem[] {
  return rawItems.map((raw, index) => ({
    id: raw.item_id,
    spec_ids: [],
    type: raw.title,
    reason: raw.blocking_reason,
    currentText: raw.question,
    suggestedText: undefined,
    itemIndex: index,
    options: raw.options.map((o) => ({
      id: o.option_id,
      label: o.label,
      description: o.effect,
    })),
  }));
}
