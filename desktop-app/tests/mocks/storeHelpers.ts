import { useStore, initialPhases } from '../../src/store';

export function resetStore() {
  useStore.setState(
    {
      run: { currentPhaseId: 'R1', progress: 0, status: 'idle' },
      specs: [],
      highlightedSpecIds: [],
      phases: initialPhases.map((p) => ({ ...p, status: 'pending' as const })),
      currentGateItems: [],
      activeItemIndex: 0,
      view: 'main',
      searchQuery: '',
      projectRootPath: null,
      designSpecPath: null,
      configPath: null,
      refineEnabled: true,
      implementEnabled: true,
      decompositionEnabled: true,
    },
  );
}
