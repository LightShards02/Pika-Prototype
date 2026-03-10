export interface DesignSpecRow {
  id: string;
  title: string;
  requirement: string;
  acceptanceCriteria: string;
  status: string;
}

export interface CodeReference {
  filePath: string;
  symbol: string;
  lineStart: number;
  lineEnd: number;
}

export interface SpecCodeMapping {
  specId: string;
  references: CodeReference[];
  confidence: number;
  source: "dummy" | "placeholder";
}

export interface CursorContextMapping {
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

export interface ExtensionStatePayload {
  importedFilePath?: string;
  importedPreviewPath?: string;
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

export interface WebviewIncomingMessage {
  type: "stateUpdated" | "cursorContextUpdated" | "error";
  payload?: ExtensionStatePayload | CursorContextMapping;
  message?: string;
}
