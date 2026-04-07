/**
 * Pure-logic service layer for PIKA CLI ↔ desktop app communication.
 * No React imports — these are standalone utility functions.
 */

import type {
  Concern,
  Phase,
  PhaseStatus,
  PikaCommand,
  RawAgentItem,
  RawAmbiguityItem,
  RawCompoundItem,
  RawDecompositionGateItem,
  RawImplementItem,
  ResolutionItem,
  Spec,
} from '../types';

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
      // 'ok' means the planner agent finished but validation checks still follow — stay running.
      if (status === 'ok') return [{ phaseId: 'I5', status: 'running' }];
      // 'skipped' means no validation follows — mark done immediately.
      if (status === 'skipped') return [{ phaseId: 'I5', status: 'done' }];
      if (status === 'failed') return [{ phaseId: 'I5', status: 'failed' }];
      if (status === 'blocked') return [{ phaseId: 'I5', status: 'blocked' }];
      return [];

    // ── Implement steps: planner validation checks (merged into I5) ──

    case 'Plan validation':
      if (status === 'ok') return [{ phaseId: 'I5', status: 'running' }];
      if (status === 'failed') return [{ phaseId: 'I5', status: 'failed' }];
      if (status === 'blocked') return [{ phaseId: 'I5', status: 'blocked' }];
      return [];

    case 'Contract field check':
      if (status === 'ok') return [{ phaseId: 'I5', status: 'running' }];
      if (status === 'blocked') return [{ phaseId: 'I5', status: 'blocked' }];
      return [];

    case 'Required field coverage check':
      if (status === 'ok') return [{ phaseId: 'I5', status: 'done' }];
      if (status === 'blocked') return [{ phaseId: 'I5', status: 'blocked' }];
      return [];

    case 'Spec issue escalation':
      if (status === 'blocked') return [{ phaseId: 'I5', status: 'blocked' }];
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
    ids.push('I1', 'I5', 'I14', 'B-EXEC');
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

function isCompoundItem(item: RawAgentItem): item is RawCompoundItem {
  return 'is_compound' in item && (item as RawCompoundItem).is_compound === true;
}

function isDecompositionGateItem(item: unknown): item is RawDecompositionGateItem {
  if (!item || typeof item !== 'object') return false;
  const rec = item as Record<string, unknown>;
  const kind = rec.issue_kind;
  return kind === 'split_candidate' || kind === 'merge_candidate';
}

function hasV2Concerns(raw: RawAgentItem): raw is RawCompoundItem {
  if (!('concerns' in raw)) return false;
  const c = (raw as RawCompoundItem).concerns;
  return Array.isArray(c) && c.length > 0;
}

/**
 * Transform a v2 compound raw item into a ResolutionItem with concerns.
 */
function transformCompoundItem(
  raw: RawCompoundItem,
  specMap: Map<string, Spec>,
  index: number,
): ResolutionItem {
  const spec = specMap.get(raw.spec_id);
  const specRecord = spec as unknown as Record<string, string> | undefined;

  const concerns: Concern[] = raw.concerns.map((c) => {
    const currentText = specRecord ? specRecord[c.field] ?? '' : '';
    const reason = c.agent_type === 'ambiguity'
      ? (c.vague_phrases ?? []).join('; ')
      : c.untestable_reason ?? '';

    return {
      concernId: c.item_id,
      agentType: c.agent_type,
      field: c.field,
      title: c.title,
      reason,
      currentText,
      suggestedText: c.suggested_improvement,
      suggestedTestType: c.suggested_test_type,
    };
  });

  // Build combined reason and type for the item header
  const reasonParts = concerns.map((c) => `[${c.agentType}] ${c.reason}`);

  return {
    id: raw.item_id,
    spec_ids: [raw.spec_id],
    type: raw.title,
    reason: reasonParts.join(' | '),
    itemIndex: index,
    isCompound: true,
    concerns,
    acceptedConcernIds: [],
    options: raw.options.map((o) => ({
      id: o.option_id,
      label: o.label,
      description: o.effect,
    })),
  };
}

/**
 * Transform raw agent items (from agent_review.json) into ResolutionItem[] for the UI.
 * Supports v1 flat rows, v2 merged rows (concerns + is_compound), and decomposition gate rows.
 *
 * Detection is structural: refine `_write_resolution_block` sets `format_version: 2` but the
 * renderer previously ignored it, so we must not rely on formatVersion alone.
 */
export function transformAgentItems(
  rawItems: RawAgentItem[],
  specs: Spec[],
  formatVersion?: number,
): ResolutionItem[] {
  const specMap = new Map(specs.map((s) => [s.spec_id, s]));
  const useV2Shapes = formatVersion === undefined || formatVersion === 2;

  return rawItems.map((raw, index) => {
    if (isDecompositionGateItem(raw)) {
      const specIds =
        raw.spec_ids && raw.spec_ids.length > 0
          ? raw.spec_ids
          : raw.spec_id
            ? [raw.spec_id]
            : [];
      return {
        id: raw.item_id,
        spec_ids: specIds,
        type: raw.title,
        reason: raw.reason,
        itemIndex: index,
        isCompound: false,
        concerns: [],
        options: raw.options.map((o) => ({
          id: o.option_id,
          label: o.label,
          description: o.effect,
        })),
      };
    }

    // V2 compound items (merged ambiguity + testability for one spec)
    if (useV2Shapes && isCompoundItem(raw)) {
      return transformCompoundItem(raw, specMap, index);
    }

    // V2 single-concern items (is_compound: false) — unwrap the concern
    if (useV2Shapes && hasV2Concerns(raw)) {
      const v2 = raw as RawCompoundItem;
      const concern = v2.concerns[0];
      const spec = specMap.get(v2.spec_id);
      const fieldValue = spec ? (spec as unknown as Record<string, string>)[concern.field] ?? '' : '';
      const isAmb = concern.agent_type === 'ambiguity';

      return {
        id: v2.item_id,
        spec_ids: [v2.spec_id],
        type: isAmb ? `Ambiguity: ${concern.title}` : `Testability: ${concern.title}`,
        reason: isAmb ? (concern.vague_phrases ?? []).join('; ') : concern.untestable_reason ?? '',
        currentText: fieldValue,
        suggestedText: concern.suggested_improvement,
        field: concern.field,
        itemIndex: index,
        isCompound: false,
        concerns: [{
          concernId: concern.item_id,
          agentType: concern.agent_type,
          field: concern.field,
          title: concern.title,
          reason: isAmb ? (concern.vague_phrases ?? []).join('; ') : concern.untestable_reason ?? '',
          currentText: fieldValue,
          suggestedText: concern.suggested_improvement,
          suggestedTestType: concern.suggested_test_type,
        }],
        options: v2.options.map((o) => ({
          id: o.option_id,
          label: o.label,
          description: o.effect,
        })),
      };
    }

    // V1 flat items (backward compat)
    const v1 = raw as RawAmbiguityItem | import('../types').RawTestabilityItem;
    const spec = specMap.get(v1.spec_id);
    const fieldValue = spec ? (spec as unknown as Record<string, string>)[v1.field] ?? '' : '';

    let type: string;
    let reason: string;

    if (isAmbiguityItem(v1)) {
      type = `Ambiguity: ${v1.title}`;
      reason = v1.vague_phrases.join('; ');
    } else {
      type = `Testability: ${v1.title}`;
      reason = (v1 as import('../types').RawTestabilityItem).untestable_reason;
    }

    return {
      id: v1.item_id,
      spec_ids: [v1.spec_id],
      type,
      reason,
      currentText: fieldValue,
      suggestedText: v1.suggested_improvement,
      field: v1.field,
      itemIndex: index,
      isCompound: false,
      concerns: [{
        concernId: v1.item_id,
        agentType: isAmbiguityItem(v1) ? 'ambiguity' : 'testability',
        field: v1.field,
        title: v1.title,
        reason,
        currentText: fieldValue,
        suggestedText: v1.suggested_improvement,
      }],
      options: v1.options.map((o) => ({
        id: o.option_id,
        label: o.label,
        description: o.effect,
      })),
    };
  });
}

/**
 * Transform raw implement gate items (from unified_planner.json etc.) into ResolutionItem[].
 * Implement items use title, question, blocking_reason, and options; validation may add
 * `evidence_refs` (spec ids) and items with empty `options` (manual YAML resolution).
 */
export function transformImplementItems(
  rawItems: RawImplementItem[],
): ResolutionItem[] {
  return rawItems.map((raw, index) => {
    const evidence = raw.evidence_refs;
    const specIds = Array.isArray(evidence)
      ? evidence.map((s) => String(s).trim()).filter(Boolean)
      : [];
    const opts = Array.isArray(raw.options) ? raw.options : [];
    return {
      id: String(raw.item_id ?? `item-${index}`),
      spec_ids: specIds,
      type: raw.title,
      reason: raw.blocking_reason,
      currentText: raw.question,
      suggestedText: undefined,
      itemIndex: index,
      isCompound: false,
      concerns: [],
      options: opts.map((o) => ({
        id: o.option_id,
        label: o.label,
        description: o.effect,
      })),
    };
  });
}
