// ---------------------------------------------------------------------------
// Shared extension-host types
// ---------------------------------------------------------------------------

/** Snapshot of pika config.yaml values used to pre-fill forms. */
export interface PikaConfigSnapshot {
  designSpecPath?: string;
  codebaseDir?: string;
  projectContextPath?: string;
  skipMapped?: boolean;
  maxSpecsPerSubunit?: number;
  minConfidenceThreshold?: number;
  verificationCommands?: string[];
}

/** Spec status counts from reading DESIGN-SPEC.csv. */
export interface SpecStats {
  total: number;
  mapped: number;
  partial: number;
  blocked: number;
  unmapped: number;
  implemented: number;
  pending: number;
}

/** A single entry in the run history sidebar section. */
export interface RunHistoryEntry {
  runId: string;
  command: "map" | "implement";
  /** ISO string */
  timestamp: string;
  status: "success" | "failed" | "unknown";
  elapsedSec?: number;
}

// ---------------------------------------------------------------------------
// Webview message types  (extension ↔ webview)
// ---------------------------------------------------------------------------

/** Messages the extension sends to sidebar webview. */
export type SidebarIncomingMessage =
  | { type: "specStats"; data: SpecStats }
  | { type: "runHistory"; entries: RunHistoryEntry[] }
  | { type: "activeRun"; command: "map" | "implement" | null };

/** Messages the sidebar webview sends to extension. */
export type SidebarOutgoingMessage =
  | { type: "openPanel"; command: "map" | "implement"; dryRun?: boolean }
  | { type: "refresh" };

/** Messages the extension sends to a command panel (map or implement). */
export type PanelIncomingMessage =
  | { type: "init"; command: "map" | "implement"; config: PikaConfigSnapshot; workset?: WorksetInfo }
  | { type: "stream"; text: string; elapsed: number; tokens?: number }
  | { type: "progress"; data: ProgressData }
  | { type: "manualResolution"; items: ManualResolutionItem[] }
  | { type: "complete"; results: MapResults | ImplementResults }
  | { type: "failed"; message: string; exitCode?: number };

/** Messages a command panel sends to extension. */
export type PanelOutgoingMessage =
  | { type: "runMap"; options: MapRunOptions }
  | { type: "runImplement"; options: ImplementRunOptions }
  | { type: "cancelRun" }
  | { type: "resolveItems"; resolutions: ManualResolution[] }
  | { type: "openFile"; path: string; line?: number }
  | { type: "browseFile"; field: string }
  | { type: "browseDir"; field: string };

// ---------------------------------------------------------------------------
// Run options
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Progress & results
// ---------------------------------------------------------------------------

export interface WorksetInfo {
  total: number;
  byModule?: Record<string, number>;
  warnings?: string[];
}

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
