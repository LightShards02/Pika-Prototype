/**
 * Represents one row from the imported design specification table.
 */
export interface DesignSpecRow {
  id: string;
  title: string;
  requirement: string;
  acceptanceCriteria: string;
  status: string;
  original: Record<string, string>;
}

/**
 * Represents a code location associated with a design specification.
 */
export interface CodeReference {
  filePath: string;
  symbol: string;
  lineStart: number;
  lineEnd: number;
}

/**
 * Represents spec-to-code mapping output.
 */
export interface SpecCodeMapping {
  specId: string;
  references: CodeReference[];
  confidence: number;
  source: "dummy" | "placeholder";
}

/**
 * Represents code-to-spec mapping output for a single file.
 */
export interface CodeToSpecMapping {
  filePath: string;
  matchedSpecs: Array<{
    specId: string;
    title?: string;
    requirement?: string;
    acceptanceCriteria?: string;
    reason: string;
    confidence: number;
  }>;
  source: "dummy" | "placeholder";
}

/**
 * Represents current cursor symbol context with mapped spec details.
 */
export interface CursorSpecContext {
  filePath: string;
  symbolName: string;
  symbolKind: "function" | "class" | "method" | "constructor" | "unknown";
  matchedSpecs: Array<{
    specId: string;
    title: string;
    requirement: string;
    acceptanceCriteria: string;
    reason: string;
    confidence: number;
  }>;
  source: "dummy" | "placeholder";
  message?: string;
}

/**
 * Represents Codex executable runtime readiness in the VS Code extension.
 */
export interface CodexRuntimeState {
  status: "ready" | "missing";
  source: "configured" | "auto" | "none";
  configuredPath?: string;
  effectivePath?: string;
  message: string;
}

/**
 * Represents mapping execution progress for panel feedback.
 */
export interface MappingRuntimeState {
  isRunning: boolean;
  message: string;
  lastStartedAt?: number;
}

/**
 * Represents Codex executable validation runtime progress.
 */
export interface CodexValidationRuntimeState {
  isValidating: boolean;
  message: string;
}

/**
 * Represents extension-managed in-memory state for imported data and mappings.
 */
export interface ExtensionState {
  importedFilePath?: string;
  importedPreviewPath?: string;
  rows: DesignSpecRow[];
  specToCodeMappings: SpecCodeMapping[];
  codexRuntime: CodexRuntimeState;
  codexValidationRuntime: CodexValidationRuntimeState;
  mappingRuntime: MappingRuntimeState;
}
