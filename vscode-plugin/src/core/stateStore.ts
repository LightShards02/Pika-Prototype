import { ExtensionState } from "../types";

const INITIAL_STATE: ExtensionState = {
  rows: [],
  specToCodeMappings: [],
  codexRuntime: {
    status: "missing",
    source: "none",
    message: "Codex executable status is still being resolved.",
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
      rows: [...this.state.rows],
      specToCodeMappings: [...this.state.specToCodeMappings],
      codexRuntime: { ...this.state.codexRuntime },
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
      rows: [...update.rows],
      specToCodeMappings: [...update.specToCodeMappings],
      codexRuntime: { ...this.state.codexRuntime },
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
   * Updates Codex runtime readiness after auto-detection or manual configuration.
   * @param codexRuntime Latest runtime readiness payload.
   */
  public setCodexRuntime(codexRuntime: ExtensionState["codexRuntime"]): void {
    this.state = {
      ...this.state,
      codexRuntime: { ...codexRuntime },
    };
  }
}
