export interface Spec {
  spec_id: string;
  module_tag: string;
  module_role: string;
  requirement: string;
  acceptance_criteria: string;
  status?: string;
}

export type AppendixType = 'text' | 'table';

export interface Appendix {
  id: string;
  fileName: string;
  filePath: string;
  type: AppendixType;
  moduleTag: string;
  content: string;
  parsedRows?: Record<string, string>[];
  columns?: string[];
}

export interface AppendixRef {
  id: string;
  fileName: string;
  filePath: string;
  type: AppendixType;
  moduleTag: string;
}

export interface PikaPreferences {
  version: 1;
  projectRootPath: string | null;
  designSpecPath: string | null;
  configPath: string | null;
  refineEnabled: boolean;
  implementEnabled: boolean;
  decompositionEnabled: boolean;
  appendixRefs: AppendixRef[];
  availableModuleTags: string[];
}

export type PhaseStatus = 'pending' | 'running' | 'done' | 'failed' | 'blocked' | 'waiting';

export interface Phase {
  id: string;
  name: string;
  group: 'Refine' | 'Implement' | 'Batch';
  status: PhaseStatus;
  description: string;
  isBlocking: boolean;
  issuesCount?: number;
}

export interface ResolutionOption {
  id: string;
  label: string;
  description?: string;
}

export interface ResolutionItem {
  id: string;
  spec_ids: string[];
  type: string;
  reason: string;
  currentText?: string;
  suggestedText?: string;
  options: ResolutionOption[];
  selectedOption?: string;
  field?: string;
  itemIndex?: number;
}

export interface RunState {
  currentPhaseId: string;
  progress: number;
  status: 'idle' | 'running' | 'paused' | 'completed' | 'failed';
  runId?: string;
  specPath?: string;
  projectRoot?: string;
  runDir?: string;
}

// --- Raw agent output types (from PIKA CLI agent_review.json) ---

export interface RawAgentOption {
  option_id: string;
  label: string;
  effect: string;
}

export interface RawAmbiguityItem {
  item_id: string;
  title: string;
  spec_id: string;
  field: 'requirement' | 'acceptance_criteria';
  vague_phrases: string[];
  suggested_improvement: string;
  options: RawAgentOption[];
}

export interface RawTestabilityItem {
  item_id: string;
  title: string;
  spec_id: string;
  field: 'acceptance_criteria';
  untestable_reason: string;
  suggested_improvement: string;
  suggested_test_type: string;
  options: RawAgentOption[];
}

export type RawAgentItem = RawAmbiguityItem | RawTestabilityItem;

// --- Electron API ---

export interface DialogFilter {
  name: string;
  extensions: string[];
}

export interface PikaExitData {
  code: number;
  summary: Record<string, unknown> | null;
}

export interface ElectronAPI {
  // Existing file I/O
  readFile: (filePath: string) => Promise<string>;
  writeFile: (filePath: string, content: string) => Promise<boolean>;
  listDirectory: (dirPath: string) => Promise<string[]>;

  // File/folder dialogs
  openFileDialog: (options?: { filters?: DialogFilter[] }) => Promise<string | null>;
  openDirDialog: () => Promise<string | null>;
  saveFileDialog: (options?: { filters?: DialogFilter[]; defaultPath?: string }) => Promise<string | null>;

  // PIKA root path
  getPikaRoot: () => Promise<string>;

  // PIKA CLI process lifecycle
  startRefine: (args: { projectRoot: string; configPath?: string; designSpecPath?: string }) => Promise<void>;
  cancelPika: () => Promise<void>;

  // Gate I/O
  readGateOutput: (args: { runDir: string }) => Promise<{ stage: string; items: RawAgentItem[] }>;
  writeResolution: (args: { runDir: string; resolutions: { itemIndex: number; chosenOptionId: string }[] }) => Promise<void>;

  // Resolve + Resume
  applyResolutions: (args: { projectRoot: string; runId: string; configPath?: string }) => Promise<void>;
  resumeRefine: (args: { projectRoot: string; runId: string; configPath?: string }) => Promise<void>;

  // Preferences persistence
  loadPreferences: () => Promise<PikaPreferences | null>;
  savePreferences: (prefs: PikaPreferences) => Promise<boolean>;
  pathExists: (targetPath: string) => Promise<boolean>;

  // Event listeners (main → renderer)
  onPikaStderr: (callback: (line: string) => void) => () => void;
  onPikaExit: (callback: (data: PikaExitData) => void) => () => void;
}

declare global {
  interface Window {
    electronAPI: ElectronAPI;
  }
}
