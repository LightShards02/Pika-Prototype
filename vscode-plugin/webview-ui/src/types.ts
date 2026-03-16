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

// ---------------------------------------------------------------------------
// Message types
// ---------------------------------------------------------------------------

/** From extension to panel webview. */
export type PanelIncomingMessage =
  | { type: "init"; command: "map" | "implement"; config: PikaConfigSnapshot; workset?: WorksetInfo }
  | { type: "stream"; text: string; elapsed: number; tokens?: number }
  | { type: "progress"; data: ProgressData }
  | { type: "manualResolution"; items: ManualResolutionItem[] }
  | { type: "complete"; results: MapResults | ImplementResults }
  | { type: "failed"; message: string; exitCode?: number }
  | { type: "browse"; field: string; value: string };

/** From panel webview to extension. */
export type PanelOutgoingMessage =
  | { type: "runMap"; options: MapRunOptions }
  | { type: "runImplement"; options: ImplementRunOptions }
  | { type: "cancelRun" }
  | { type: "resolveItems"; resolutions: ManualResolution[] }
  | { type: "openFile"; path: string; line?: number }
  | { type: "browseFile"; field: string }
  | { type: "browseDir"; field: string };

/** From extension to sidebar webview. */
export type SidebarIncomingMessage =
  | { type: "specStats"; data: SpecStats }
  | { type: "runHistory"; entries: RunHistoryEntry[] }
  | { type: "activeRun"; command: "map" | "implement" | null };

/** From sidebar webview to extension. */
export type SidebarOutgoingMessage =
  | { type: "openPanel"; command: "map" | "implement"; dryRun?: boolean }
  | { type: "refresh" };

// Run option shapes
export interface MapRunOptions {
  designSpecPath: string;
  codebaseDir: string;
  projectContextPath?: string;
  skipMapped: boolean;
  maxSpecsPerSubunit: number;
  minConfidenceThreshold: number;
  extraInstructions?: string;
  dryRun?: boolean;
}

export interface ImplementRunOptions {
  designSpecPath: string;
  codebaseDir: string;
  projectContextPath?: string;
  dryRun?: boolean;
}

// Bootstrap object injected into window.__PIKA__
export interface PikaBootstrap {
  view: "sidebar" | "map" | "implement";
}
