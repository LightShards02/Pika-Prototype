import { create } from 'zustand';
import type { Phase, RunState, Spec, ResolutionItem } from './types';

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
  searchQuery: string;
  setSearchQuery: (query: string) => void;
}

const initialPhases: Phase[] = [
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
  
  searchQuery: '',
  setSearchQuery: (query) => set({ searchQuery: query }),
}));
