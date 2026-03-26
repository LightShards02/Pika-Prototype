import { describe, it, expect } from 'vitest';
import { useStore, initialPhases } from '../../src/store';
import { mockSpecs, buildGateItems, mockTextAppendix, mockTableAppendix } from '../fixtures/testData';

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

  describe('appendixes', () => {
    it('has empty appendixes initially', () => {
      const state = useStore.getState();
      expect(state.appendixes).toEqual([]);
      expect(state.availableModuleTags).toEqual([]);
      expect(state.activeLeftTab).toBe('spec');
    });

    it('addAppendix appends to the list', () => {
      useStore.getState().addAppendix(mockTextAppendix);
      expect(useStore.getState().appendixes).toHaveLength(1);
      expect(useStore.getState().appendixes[0].id).toBe('appx-text-001');

      useStore.getState().addAppendix(mockTableAppendix);
      expect(useStore.getState().appendixes).toHaveLength(2);
    });

    it('removeAppendix removes by id', () => {
      useStore.getState().addAppendix(mockTextAppendix);
      useStore.getState().addAppendix(mockTableAppendix);
      useStore.getState().removeAppendix('appx-text-001');

      const appxs = useStore.getState().appendixes;
      expect(appxs).toHaveLength(1);
      expect(appxs[0].id).toBe('appx-table-001');
    });

    it('removeAppendix resets activeLeftTab if removed tab was active', () => {
      useStore.getState().addAppendix(mockTextAppendix);
      useStore.getState().setActiveLeftTab('appx-text-001');
      expect(useStore.getState().activeLeftTab).toBe('appx-text-001');

      useStore.getState().removeAppendix('appx-text-001');
      expect(useStore.getState().activeLeftTab).toBe('spec');
    });

    it('removeAppendix preserves activeLeftTab if a different tab was active', () => {
      useStore.getState().addAppendix(mockTextAppendix);
      useStore.getState().addAppendix(mockTableAppendix);
      useStore.getState().setActiveLeftTab('appx-table-001');

      useStore.getState().removeAppendix('appx-text-001');
      expect(useStore.getState().activeLeftTab).toBe('appx-table-001');
    });

    it('updateAppendixModuleTag updates the correct appendix', () => {
      useStore.getState().addAppendix(mockTextAppendix);
      useStore.getState().addAppendix(mockTableAppendix);
      useStore.getState().updateAppendixModuleTag('appx-text-001', 'EXPORT');

      const appxs = useStore.getState().appendixes;
      expect(appxs.find((a) => a.id === 'appx-text-001')?.moduleTag).toBe('EXPORT');
      expect(appxs.find((a) => a.id === 'appx-table-001')?.moduleTag).toBe('EXPORT'); // unchanged
    });

    it('clearAppendixes clears all and resets tab', () => {
      useStore.getState().addAppendix(mockTextAppendix);
      useStore.getState().addAppendix(mockTableAppendix);
      useStore.getState().setActiveLeftTab('appx-text-001');

      useStore.getState().clearAppendixes();
      expect(useStore.getState().appendixes).toEqual([]);
      expect(useStore.getState().activeLeftTab).toBe('spec');
    });

    it('setAvailableModuleTags stores tags', () => {
      useStore.getState().setAvailableModuleTags(['AUTH', 'EXPORT', 'CORE']);
      expect(useStore.getState().availableModuleTags).toEqual(['AUTH', 'EXPORT', 'CORE']);
    });

    it('setActiveLeftTab switches active tab', () => {
      useStore.getState().setActiveLeftTab('appx-text-001');
      expect(useStore.getState().activeLeftTab).toBe('appx-text-001');
    });

    it('resetForNewRun resets activeLeftTab but preserves appendixes', () => {
      useStore.getState().addAppendix(mockTextAppendix);
      useStore.getState().setActiveLeftTab('appx-text-001');

      useStore.getState().resetForNewRun();
      expect(useStore.getState().activeLeftTab).toBe('spec');
      expect(useStore.getState().appendixes).toHaveLength(1); // preserved
    });
  });
});
