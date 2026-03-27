import { describe, it, expect } from 'vitest';
import { useStore, extractPreferences } from '../../src/store';
import { mockPreferences, mockTextAppendix, mockTableAppendix } from '../fixtures/testData';

describe('extractPreferences', () => {
  it('returns correct shape from default store', () => {
    const prefs = extractPreferences(useStore.getState());
    expect(prefs).toEqual({
      version: 1,
      projectRootPath: null,
      designSpecPath: null,
      configPath: null,
      refineEnabled: true,
      implementEnabled: true,
      decompositionEnabled: true,
      appendixRefs: [],
      availableModuleTags: [],
    });
  });

  it('extracts persistable fields after state changes', () => {
    useStore.getState().setProjectRootPath('/my/project');
    useStore.getState().setDesignSpecPath('/my/spec.csv');
    useStore.getState().setConfigPath('/my/config.yaml');
    useStore.getState().setRefineEnabled(false);
    useStore.getState().setAvailableModuleTags(['MOD_A']);

    const prefs = extractPreferences(useStore.getState());
    expect(prefs.projectRootPath).toBe('/my/project');
    expect(prefs.designSpecPath).toBe('/my/spec.csv');
    expect(prefs.configPath).toBe('/my/config.yaml');
    expect(prefs.refineEnabled).toBe(false);
    expect(prefs.availableModuleTags).toEqual(['MOD_A']);
  });

  it('strips content/parsedRows/columns from appendixes', () => {
    useStore.getState().addAppendix(mockTextAppendix);
    useStore.getState().addAppendix(mockTableAppendix);

    const prefs = extractPreferences(useStore.getState());
    expect(prefs.appendixRefs).toHaveLength(2);

    const textRef = prefs.appendixRefs[0];
    expect(textRef.id).toBe('appx-text-001');
    expect(textRef.fileName).toBe('notes.txt');
    expect(textRef.filePath).toBe('/test/notes.txt');
    expect(textRef.type).toBe('text');
    expect(textRef.moduleTag).toBe('AUTH');
    expect(textRef).not.toHaveProperty('content');
    expect(textRef).not.toHaveProperty('parsedRows');
    expect(textRef).not.toHaveProperty('columns');

    const tableRef = prefs.appendixRefs[1];
    expect(tableRef).not.toHaveProperty('content');
    expect(tableRef).not.toHaveProperty('parsedRows');
    expect(tableRef).not.toHaveProperty('columns');
  });
});

describe('hydrateFromPreferences', () => {
  it('sets all persistable fields from preferences', () => {
    useStore.getState().hydrateFromPreferences(mockPreferences);
    const state = useStore.getState();

    expect(state.projectRootPath).toBe('/test/project');
    expect(state.designSpecPath).toBe('/test/spec.csv');
    expect(state.configPath).toBe('/test/config.yaml');
    expect(state.refineEnabled).toBe(true);
    expect(state.implementEnabled).toBe(false);
    expect(state.decompositionEnabled).toBe(true);
    expect(state.availableModuleTags).toEqual(['AUTH', 'EXPORT']);
  });

  it('creates appendix stubs with empty content', () => {
    useStore.getState().hydrateFromPreferences(mockPreferences);
    const state = useStore.getState();

    expect(state.appendixes).toHaveLength(1);
    expect(state.appendixes[0].id).toBe('appx-text-001');
    expect(state.appendixes[0].fileName).toBe('notes.txt');
    expect(state.appendixes[0].content).toBe('');
    expect(state.appendixes[0].parsedRows).toBeUndefined();
    expect(state.appendixes[0].columns).toBeUndefined();
  });

  it('does not touch transient state', () => {
    useStore.getState().setRun({ status: 'running', progress: 42 });
    useStore.getState().setSpecs([{ spec_id: 'X', module_tag: 'M', module_role: 'R', requirement: 'req', acceptance_criteria: 'ac' }]);
    useStore.getState().setView('settings');

    useStore.getState().hydrateFromPreferences(mockPreferences);
    const state = useStore.getState();

    expect(state.run.status).toBe('running');
    expect(state.run.progress).toBe(42);
    expect(state.specs).toHaveLength(1);
    expect(state.view).toBe('settings');
  });
});
