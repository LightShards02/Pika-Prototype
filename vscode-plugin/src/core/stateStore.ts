import { ExtensionState } from "../types";

const INITIAL_STATE: ExtensionState = {
  rows: [],
  specToCodeMappings: [],
  codexRuntime: {
    status: "missing",
    source: "none",
    message: "Codex executable status is still being resolved.",
  },
  codexValidationRuntime: {
    isValidating: false,
    message: "",
  },
  mappingRuntime: {
    isRunning: false,
    message: "Idle",
  },
};

/**
 * Maintains extension in-memory state for the current VS Code session.
 */
export class StateStore {
  private state: ExtensionState = { ...INITIAL_STATE };

  /**
   * Returns a readonly snapshot of current state.
   */
  public getState(): ExtensionState {
    return {
      importedFilePath: this.state.importedFilePath,
      importedPreviewPath: this.state.importedPreviewPath,
      issueTrackerFilePath: this.state.issueTrackerFilePath,
      testingPlanFilePath: this.state.testingPlanFilePath,
      codeDirectoryPath: this.state.codeDirectoryPath,
      rows: [...this.state.rows],
      specToCodeMappings: [...this.state.specToCodeMappings],
      codexRuntime: { ...this.state.codexRuntime },
      codexValidationRuntime: { ...this.state.codexValidationRuntime },
      mappingRuntime: { ...this.state.mappingRuntime },
    };
  }

  /**
   * Replaces rows and mappings after import/remap.
   * @param update Imported file and derived mapping payload.
   */
  public setImportedData(update: {
    importedFilePath?: string;
    importedPreviewPath?: string;
    rows: ExtensionState["rows"];
    specToCodeMappings: ExtensionState["specToCodeMappings"];
  }): void {
    this.state = {
      importedFilePath: update.importedFilePath,
      importedPreviewPath: update.importedPreviewPath,
      issueTrackerFilePath: this.state.issueTrackerFilePath,
      testingPlanFilePath: this.state.testingPlanFilePath,
      codeDirectoryPath: this.state.codeDirectoryPath,
      rows: [...update.rows],
      specToCodeMappings: [...update.specToCodeMappings],
      codexRuntime: { ...this.state.codexRuntime },
      codexValidationRuntime: { ...this.state.codexValidationRuntime },
      mappingRuntime: { ...this.state.mappingRuntime },
    };
  }

  /**
   * Updates only spec mappings while preserving imported rows and paths.
   * @param specToCodeMappings Remapped spec-to-code payload.
   */
  public setMappings(specToCodeMappings: ExtensionState["specToCodeMappings"]): void {
    this.state = {
      ...this.state,
      specToCodeMappings: [...specToCodeMappings],
    };
  }

  /**
   * Updates imported preview file path after generating a new tab document.
   * @param importedPreviewPath Generated markdown preview path.
   */
  public setImportedPreviewPath(importedPreviewPath?: string): void {
    this.state = {
      ...this.state,
      importedPreviewPath,
    };
  }

  /**
   * Updates imported issue tracking sheet path.
   * @param issueTrackerFilePath Imported issue tracking file path.
   */
  public setIssueTrackerFilePath(issueTrackerFilePath?: string): void {
    this.state = {
      ...this.state,
      issueTrackerFilePath,
    };
  }

  /**
   * Updates imported testing plan document path.
   * @param testingPlanFilePath Imported testing plan file path.
   */
  public setTestingPlanFilePath(testingPlanFilePath?: string): void {
    this.state = {
      ...this.state,
      testingPlanFilePath,
    };
  }

  /**
   * Updates effective code directory path used by mapping links and resolution.
   * @param codeDirectoryPath Effective code directory path.
   */
  public setCodeDirectoryPath(codeDirectoryPath?: string): void {
    this.state = {
      ...this.state,
      codeDirectoryPath,
    };
  }

  /**
   * Updates Codex runtime readiness after auto-detection or manual configuration.
   * @param codexRuntime Latest runtime readiness payload.
   */
  public setCodexRuntime(codexRuntime: ExtensionState["codexRuntime"]): void {
    this.state = {
      ...this.state,
      codexRuntime: { ...codexRuntime },
    };
  }

  /**
   * Updates Codex validation runtime progress shown while handshake is running.
   * @param codexValidationRuntime Validation runtime payload.
   */
  public setCodexValidationRuntime(
    codexValidationRuntime: ExtensionState["codexValidationRuntime"],
  ): void {
    this.state = {
      ...this.state,
      codexValidationRuntime: { ...codexValidationRuntime },
    };
  }

  /**
   * Updates mapping execution runtime state for webview progress rendering.
   * @param mappingRuntime Mapping runtime payload.
   */
  public setMappingRuntime(mappingRuntime: ExtensionState["mappingRuntime"]): void {
    this.state = {
      ...this.state,
      mappingRuntime: { ...mappingRuntime },
    };
  }
}
