import { describe, it, expect } from 'vitest';
import { useStore, initialPhases } from '../../src/store';
import { mockSpecs, buildGateItems } from '../fixtures/testData';

describe('Zustand store', () => {
  it('has correct initial state', () => {
    const state = useStore.getState();
    expect(state.run.status).toBe('idle');
    expect(state.run.progress).toBe(0);
    expect(state.specs).toEqual([]);
    expect(state.phases).toHaveLength(initialPhases.length);
    expect(state.view).toBe('main');
    expect(state.projectRootPath).toBeNull();
    expect(state.designSpecPath).toBeNull();
    expect(state.configPath).toBeNull();
    expect(state.refineEnabled).toBe(true);
    expect(state.implementEnabled).toBe(true);
    expect(state.decompositionEnabled).toBe(true);
  });

  describe('setRun', () => {
    it('merges partial update', () => {
      useStore.getState().setRun({ status: 'running' });
      const state = useStore.getState();
      expect(state.run.status).toBe('running');
      expect(state.run.progress).toBe(0); // preserved
    });

    it('updates multiple fields at once', () => {
      useStore.getState().setRun({ status: 'paused', progress: 50, runId: 'run-1' });
      const state = useStore.getState();
      expect(state.run.status).toBe('paused');
      expect(state.run.progress).toBe(50);
      expect(state.run.runId).toBe('run-1');
    });
  });

  describe('setSpecs', () => {
    it('sets and retrieves specs', () => {
      useStore.getState().setSpecs(mockSpecs);
      expect(useStore.getState().specs).toEqual(mockSpecs);
    });
  });

  describe('updatePhase', () => {
    it('updates specific phase status', () => {
      useStore.getState().updatePhase('R1', { status: 'done' });
      const phases = useStore.getState().phases;
      expect(phases.find((p) => p.id === 'R1')?.status).toBe('done');
      expect(phases.find((p) => p.id === 'R2')?.status).toBe('pending');
    });

    it('handles non-existent phase gracefully', () => {
      const before = useStore.getState().phases;
      useStore.getState().updatePhase('NONEXISTENT', { status: 'done' });
      expect(useStore.getState().phases).toEqual(before);
    });
  });

  describe('resolveItem', () => {
    it('sets selectedOption on correct gate item', () => {
      const gateItems = buildGateItems();
      useStore.getState().setCurrentGateItems(gateItems);
      useStore.getState().resolveItem('AMB-001', 'accept_suggestion');
      const items = useStore.getState().currentGateItems;
      expect(items.find((i) => i.id === 'AMB-001')?.selectedOption).toBe('accept_suggestion');
      expect(items.find((i) => i.id === 'TST-001')?.selectedOption).toBeUndefined();
    });

    it('handles non-existent item gracefully', () => {
      const gateItems = buildGateItems();
      useStore.getState().setCurrentGateItems(gateItems);
      useStore.getState().resolveItem('NONEXISTENT', 'skip');
      // No crash, items unchanged
      expect(useStore.getState().currentGateItems).toHaveLength(2);
    });
  });

  describe('setView', () => {
    it('toggles between main and settings', () => {
      expect(useStore.getState().view).toBe('main');
      useStore.getState().setView('settings');
      expect(useStore.getState().view).toBe('settings');
      useStore.getState().setView('main');
      expect(useStore.getState().view).toBe('main');
    });
  });

  describe('resetForNewRun', () => {
    it('resets phases, specs, gate items to initial', () => {
      // Set some non-initial state
      useStore.getState().setSpecs(mockSpecs);
      useStore.getState().updatePhase('R1', { status: 'done' });
      useStore.getState().setCurrentGateItems(buildGateItems());
      useStore.getState().setActiveItemIndex(1);
      useStore.getState().setHighlightedSpecIds(['SPEC-001']);

      useStore.getState().resetForNewRun();
      const state = useStore.getState();
      expect(state.specs).toEqual([]);
      expect(state.currentGateItems).toEqual([]);
      expect(state.activeItemIndex).toBe(0);
      expect(state.highlightedSpecIds).toEqual([]);
      expect(state.phases.every((p) => p.status === 'pending')).toBe(true);
    });
  });

  describe('setHighlightedSpecIds', () => {
    it('sets highlighted spec IDs', () => {
      useStore.getState().setHighlightedSpecIds(['SPEC-001', 'SPEC-002']);
      expect(useStore.getState().highlightedSpecIds).toEqual(['SPEC-001', 'SPEC-002']);
    });
  });
});
