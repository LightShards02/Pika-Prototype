import { create } from 'zustand';
import type { Phase, RunState, Spec, ResolutionItem, Appendix } from './types';

interface AppStore {
  // Run State
  run: RunState;
  setRun: (run: Partial<RunState>) => void;

  // Specs
  specs: Spec[];
  setSpecs: (specs: Spec[]) => void;
  highlightedSpecIds: string[];
  setHighlightedSpecIds: (ids: string[]) => void;

  // Pipeline
  phases: Phase[];
  updatePhase: (id: string, updates: Partial<Phase>) => void;

  // Gate Resolution
  currentGateItems: ResolutionItem[];
  setCurrentGateItems: (items: ResolutionItem[]) => void;
  activeItemIndex: number;
  setActiveItemIndex: (index: number) => void;
  resolveItem: (itemId: string, optionId: string) => void;

  // UI
  view: 'main' | 'settings';
  setView: (view: 'main' | 'settings') => void;
  searchQuery: string;
  setSearchQuery: (query: string) => void;
  activeModuleFilters: string[];
  setActiveModuleFilters: (filters: string[]) => void;
  showHighlightedOnly: boolean;
  setShowHighlightedOnly: (v: boolean) => void;

  // User Inputs (from EntryScreen)
  projectRootPath: string | null;
  setProjectRootPath: (path: string | null) => void;
  designSpecPath: string | null;
  setDesignSpecPath: (path: string | null) => void;
  configPath: string | null;
  setConfigPath: (path: string | null) => void;

  // Appendixes
  appendixes: Appendix[];
  addAppendix: (appendix: Appendix) => void;
  removeAppendix: (id: string) => void;
  updateAppendixModuleTag: (id: string, moduleTag: string) => void;
  clearAppendixes: () => void;
  availableModuleTags: string[];
  setAvailableModuleTags: (tags: string[]) => void;

  // Left panel navigation
  activeLeftTab: string;
  setActiveLeftTab: (tabId: string) => void;

  // Options
  refineEnabled: boolean;
  setRefineEnabled: (v: boolean) => void;
  implementEnabled: boolean;
  setImplementEnabled: (v: boolean) => void;
  decompositionEnabled: boolean;
  setDecompositionEnabled: (v: boolean) => void;

  // Reset for new run
  resetForNewRun: () => void;
}

export const initialPhases: Phase[] = [
  // Refine Group
  { id: 'R1', name: 'Load & Validate Spec', group: 'Refine', status: 'pending', description: 'Checks required columns and basic SADS contract.', isBlocking: false },
  { id: 'R2', name: 'Decomposition Check', group: 'Refine', status: 'pending', description: 'Detects split and merge candidates.', isBlocking: true },
  { id: 'R3', name: 'Ambiguity Detection', group: 'Refine', status: 'pending', description: 'Flags vague or underspecified requirements.', isBlocking: true },
  { id: 'R4', name: 'Testability Audit', group: 'Refine', status: 'pending', description: 'Flags specs that cannot be deterministically tested.', isBlocking: true },

  // Implement Group
  { id: 'I1', name: 'Normalize Config', group: 'Implement', status: 'pending', description: 'Parse roles, policies, and budgets.', isBlocking: false },
  { id: 'I5', name: 'Run Unified Planner', group: 'Implement', status: 'pending', description: 'AI agent produces the full implementation plan.', isBlocking: false },
  { id: 'I7', name: 'Gate: Planner Blockers', group: 'Implement', status: 'pending', description: 'Human judgment needed for planner flags.', isBlocking: true },
  { id: 'I14', name: 'Construct Batch Plan', group: 'Implement', status: 'pending', description: 'Group specs into execution batches.', isBlocking: false },

  // Batch Execution (Placeholder for B1-B9)
  { id: 'B-EXEC', name: 'Batch Execution', group: 'Batch', status: 'pending', description: 'Code generation and verification per batch.', isBlocking: false },
];

export const useStore = create<AppStore>((set) => ({
  run: {
    currentPhaseId: 'R1',
    progress: 0,
    status: 'idle',
  },
  setRun: (run) => set((state) => ({ run: { ...state.run, ...run } })),

  specs: [],
  setSpecs: (specs) => set({ specs }),
  highlightedSpecIds: [],
  setHighlightedSpecIds: (ids) => set({ highlightedSpecIds: ids }),

  phases: initialPhases,
  updatePhase: (id, updates) => set((state) => ({
    phases: state.phases.map((p) => (p.id === id ? { ...p, ...updates } : p)),
  })),

  currentGateItems: [],
  setCurrentGateItems: (items) => set({ currentGateItems: items }),
  activeItemIndex: 0,
  setActiveItemIndex: (index) => set({ activeItemIndex: index }),
  resolveItem: (itemId, optionId) => set((state) => ({
    currentGateItems: state.currentGateItems.map((item) =>
      item.id === itemId ? { ...item, selectedOption: optionId } : item
    ),
  })),

  view: 'main',
  setView: (view) => set({ view }),
  searchQuery: '',
  setSearchQuery: (query) => set({ searchQuery: query }),
  activeModuleFilters: [],
  setActiveModuleFilters: (filters) => set({ activeModuleFilters: filters }),
  showHighlightedOnly: false,
  setShowHighlightedOnly: (v) => set({ showHighlightedOnly: v }),

  // User Inputs
  projectRootPath: null,
  setProjectRootPath: (path) => set({ projectRootPath: path }),
  designSpecPath: null,
  setDesignSpecPath: (path) => set({ designSpecPath: path }),
  configPath: null,
  setConfigPath: (path) => set({ configPath: path }),

  // Appendixes
  appendixes: [],
  addAppendix: (appendix) => set((state) => ({ appendixes: [...state.appendixes, appendix] })),
  removeAppendix: (id) => set((state) => ({
    appendixes: state.appendixes.filter((a) => a.id !== id),
    activeLeftTab: state.activeLeftTab === id ? 'spec' : state.activeLeftTab,
  })),
  updateAppendixModuleTag: (id, moduleTag) => set((state) => ({
    appendixes: state.appendixes.map((a) => a.id === id ? { ...a, moduleTag } : a),
  })),
  clearAppendixes: () => set({ appendixes: [], activeLeftTab: 'spec' }),
  availableModuleTags: [],
  setAvailableModuleTags: (tags) => set({ availableModuleTags: tags }),

  // Left panel navigation
  activeLeftTab: 'spec',
  setActiveLeftTab: (tabId) => set({ activeLeftTab: tabId }),

  // Options
  refineEnabled: true,
  setRefineEnabled: (v) => set({ refineEnabled: v }),
  implementEnabled: true,
  setImplementEnabled: (v) => set({ implementEnabled: v }),
  decompositionEnabled: true,
  setDecompositionEnabled: (v) => set({ decompositionEnabled: v }),

  // Reset for new run
  resetForNewRun: () => set({
    phases: initialPhases.map((p) => ({ ...p, status: 'pending' as const })),
    currentGateItems: [],
    activeItemIndex: 0,
    highlightedSpecIds: [],
    specs: [],
    activeModuleFilters: [],
    showHighlightedOnly: false,
    activeLeftTab: 'spec',
  }),
}));
