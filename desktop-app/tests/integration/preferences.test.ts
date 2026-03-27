import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useStore, extractPreferences, subscribeToPreferenceChanges } from '../../src/store';
import { mockPreferences } from '../fixtures/testData';
import type { PikaPreferences } from '../../src/types';

describe('preferences integration', () => {
  describe('hydration round-trip', () => {
    it('hydrate then extract produces equivalent preferences', () => {
      useStore.getState().hydrateFromPreferences(mockPreferences);
      const extracted = extractPreferences(useStore.getState());

      expect(extracted.version).toBe(1);
      expect(extracted.projectRootPath).toBe(mockPreferences.projectRootPath);
      expect(extracted.designSpecPath).toBe(mockPreferences.designSpecPath);
      expect(extracted.configPath).toBe(mockPreferences.configPath);
      expect(extracted.refineEnabled).toBe(mockPreferences.refineEnabled);
      expect(extracted.implementEnabled).toBe(mockPreferences.implementEnabled);
      expect(extracted.decompositionEnabled).toBe(mockPreferences.decompositionEnabled);
      expect(extracted.availableModuleTags).toEqual(mockPreferences.availableModuleTags);
      expect(extracted.appendixRefs).toEqual(mockPreferences.appendixRefs);
    });

    it('hydrating empty preferences restores defaults', () => {
      const emptyPrefs: PikaPreferences = {
        version: 1,
        projectRootPath: null,
        designSpecPath: null,
        configPath: null,
        refineEnabled: true,
        implementEnabled: true,
        decompositionEnabled: true,
        appendixRefs: [],
        availableModuleTags: [],
      };
      useStore.getState().hydrateFromPreferences(emptyPrefs);
      const state = useStore.getState();
      expect(state.projectRootPath).toBeNull();
      expect(state.appendixes).toEqual([]);
    });
  });

  describe('subscribeToPreferenceChanges', () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    it('calls savePreferences after a persistable state change', async () => {
      const unsubscribe = subscribeToPreferenceChanges();

      useStore.getState().setProjectRootPath('/new/path');
      vi.advanceTimersByTime(500);

      expect(window.electronAPI.savePreferences).toHaveBeenCalledTimes(1);
      const savedPrefs = (window.electronAPI.savePreferences as ReturnType<typeof vi.fn>).mock.calls[0][0];
      expect(savedPrefs.projectRootPath).toBe('/new/path');

      unsubscribe();
      vi.useRealTimers();
    });

    it('does not call savePreferences for transient state changes', () => {
      const unsubscribe = subscribeToPreferenceChanges();

      // Trigger initial save from subscription setup (first snapshot)
      vi.advanceTimersByTime(500);
      const callsBefore = (window.electronAPI.savePreferences as ReturnType<typeof vi.fn>).mock.calls.length;

      useStore.getState().setRun({ status: 'running' });
      useStore.getState().setSpecs([{ spec_id: 'X', module_tag: 'M', module_role: 'R', requirement: 'r', acceptance_criteria: 'a' }]);
      useStore.getState().setSearchQuery('test');
      vi.advanceTimersByTime(500);

      expect((window.electronAPI.savePreferences as ReturnType<typeof vi.fn>).mock.calls.length).toBe(callsBefore);

      unsubscribe();
      vi.useRealTimers();
    });

    it('debounces rapid changes into a single save', () => {
      const unsubscribe = subscribeToPreferenceChanges();

      useStore.getState().setProjectRootPath('/path1');
      vi.advanceTimersByTime(100);
      useStore.getState().setProjectRootPath('/path2');
      vi.advanceTimersByTime(100);
      useStore.getState().setProjectRootPath('/path3');
      vi.advanceTimersByTime(500);

      // Only one save should have been made (the debounced one)
      expect(window.electronAPI.savePreferences).toHaveBeenCalledTimes(1);
      const savedPrefs = (window.electronAPI.savePreferences as ReturnType<typeof vi.fn>).mock.calls[0][0];
      expect(savedPrefs.projectRootPath).toBe('/path3');

      unsubscribe();
      vi.useRealTimers();
    });

    it('cleanup stops saving', () => {
      const unsubscribe = subscribeToPreferenceChanges();
      unsubscribe();

      useStore.getState().setProjectRootPath('/after-unsub');
      vi.advanceTimersByTime(1000);

      expect(window.electronAPI.savePreferences).not.toHaveBeenCalled();
      vi.useRealTimers();
    });
  });
});
