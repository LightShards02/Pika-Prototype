// ---------------------------------------------------------------------------
// Shared types for the webview React app  (mirroring src/types.ts)
// ---------------------------------------------------------------------------

export interface PikaConfigSnapshot {
  designSpecPath?: string;
  codebaseDir?: string;
  projectContextPath?: string;
  skipMapped?: boolean;
  maxSpecsPerSubunit?: number;
  minConfidenceThreshold?: number;
  verificationCommands?: string[];
}

export interface SpecStats {
  total: number;
  mapped: number;
  partial: number;
  blocked: number;
  unmapped: number;
  implemented: number;
  pending: number;
}

export interface RunHistoryEntry {
  runId: string;
  command: "map" | "implement";
  timestamp: string;
  status: "success" | "failed" | "unknown";
  elapsedSec?: number;
}

export interface WorksetInfo {
  total: number;
  byModule?: Record<string, number>;
  warnings?: string[];
}

// Progress events
export type ProgressData =
  | { type: "subunitStart"; subunit: string; specCount: number }
  | { type: "subunitComplete"; subunit: string; mapped: number; partial: number }
  | { type: "phaseChange"; phase: string; phaseIndex: number }
  | { type: "batchStart"; batchId: number; totalBatches: number; specIds: string[]; module?: string }
  | { type: "batchComplete"; batchId: number; filesChanged: number; testsPassed?: boolean }
  | { type: "tokens"; total: number };

export interface ManualResolutionItem {
  id: string;
  entityType: string;
  entityId: string;
  reason: string;
  details?: string;
  suggestions?: string[];
}

export interface ManualResolution {
  id: string;
  note: string;
  suggestedValue?: string;
}

// Map results
export interface MapSpecResult {
  specId: string;
  title: string;
  status: "mapped" | "partial" | "unmapped" | "blocked";
  confidence?: number;
  symbols?: string;
  problems?: string;
}

export interface MapResults {
  runId: string;
  totalSpecs: number;
  subunitCount: number;
  elapsedSec: number;
  tokens: number;
  mapped: number;
  partial: number;
  blocked: number;
  unmapped: number;
  specs: MapSpecResult[];
}

// Implement results
export interface BatchResult {
  batchId: number;
  specIds: string[];
  module?: string;
  filesChanged: number;
  testsPassed?: boolean;
  testOutput?: string;
}

export interface ChangedFile {
  path: string;
  added: number;
  removed: number;
}

export interface ImplementResults {
  runId: string;
  totalSpecs: number;
  implementedSpecs: number;
  failedSpecs: number;
  elapsedSec: number;
  tokens: number;
  batches: BatchResult[];
  filesChanged: ChangedFile[];
  moduleBreakdown?: Record<string, number>;
}

export interface ExtensionStatePayload {
  importedFilePath?: string;
  importedPreviewPath?: string;
<<<<<<< HEAD
  issueTrackerFilePath?: string;
  testingPlanFilePath?: string;
  codeDirectoryPath?: string;
  lastMappedAt?: number;
  rows: DesignSpecRow[];
  specToCodeMappings: SpecCodeMapping[];
  codexRuntime: CodexRuntimePayload;
  codexValidationRuntime: CodexValidationRuntimePayload;
  mappingRuntime: MappingRuntimePayload;
}

export interface CodexRuntimePayload {
  status: "ready" | "missing";
  source: "configured" | "auto" | "none";
  configuredPath?: string;
  effectivePath?: string;
  message: string;
}

export interface MappingRuntimePayload {
  isRunning: boolean;
  message: string;
  lastStartedAt?: number;
}

export interface CodexValidationRuntimePayload {
  isValidating: boolean;
  message: string;
}

export interface ImportedDocumentOpenPayload {
  documentType: "designSpec" | "issueTracker" | "testingPlan";
=======
  rows: DesignSpecRow[];
  specToCodeMappings: SpecCodeMapping[];
>>>>>>> origin/cursor/plugin-design-spec-mapping-51a2
}

export interface WebviewIncomingMessage {
  type: "stateUpdated" | "cursorContextUpdated" | "error";
  payload?: ExtensionStatePayload | CursorContextMapping;
  message?: string;
}
