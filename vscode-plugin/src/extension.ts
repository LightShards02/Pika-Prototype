import * as vscode from "vscode";
import { isPathInsideParent, resolveEffectiveCodeDirectoryPath } from "./core/codeDirectory";
import { detectCodexRuntimeState } from "./core/codexExecutable";
import { validateCodexExecutableHandshake } from "./core/codexValidation";
import { parseDesignSpecCsv } from "./core/csvParser";
import { waitForMockMappingDelay } from "./core/mappingRuntime";
import { mapCursorContextToSpecs, mapDesignSpecsToCode } from "./core/mappingService";
import { buildPreviewOutputPath, buildSpecPreviewMarkdown } from "./core/specPreviewDocument";
import { StateStore } from "./core/stateStore";
import { getWebviewHtml } from "./webview/getWebviewHtml";
import { SpecCodeMapping } from "./types";

interface OpenCodeReferencePayload {
  filePath: string;
  lineStart: number;
  lineEnd: number;
  symbol?: string;
}

type ImportedDocumentType = "designSpec" | "issueTracker" | "testingPlan";

interface OpenImportedDocumentPayload {
  documentType: ImportedDocumentType;
}

interface WebviewMessage {
  type:
    | "chooseDesignSpec"
    | "chooseIssueTracker"
    | "chooseTestingPlan"
    | "requestCodeMapping"
    | "refreshMappings"
    | "openCodeReference"
    | "openImportedDocument"
    | "configureCodexPath"
    | "configureCodeDirectory";
  payload?: OpenCodeReferencePayload | OpenImportedDocumentPayload;
}

const CODEX_PATH_CONFIGURATION_SECTION = "designSpecMapper";
const CODEX_PATH_CONFIGURATION_KEY = "codexPath";
const CODE_DIRECTORY_CONFIGURATION_KEY = "codeDirectory";
const LAST_MAPPED_AT_WORKSPACE_STATE_KEY = "designSpecMapper.lastMappedAt";

function isFunctionOrClassSymbol(kind: vscode.SymbolKind): boolean {
  return (
    kind === vscode.SymbolKind.Function ||
    kind === vscode.SymbolKind.Method ||
    kind === vscode.SymbolKind.Class ||
    kind === vscode.SymbolKind.Constructor
  );
}

function toSymbolKindName(kind: vscode.SymbolKind): "function" | "class" | "method" | "constructor" | "unknown" {
  if (kind === vscode.SymbolKind.Function) {
    return "function";
  }
  if (kind === vscode.SymbolKind.Method) {
    return "method";
  }
  if (kind === vscode.SymbolKind.Class) {
    return "class";
  }
  if (kind === vscode.SymbolKind.Constructor) {
    return "constructor";
  }
  return "unknown";
}

function rangeLength(range: vscode.Range): number {
  return Math.max(0, range.end.line - range.start.line) * 100000 + Math.max(0, range.end.character - range.start.character);
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Renders the React webview and handles messages between UI and extension host.
 */
class DesignSpecPreviewProvider implements vscode.WebviewViewProvider {
  private readonly webviews = new Set<vscode.Webview>();
  private codexValidationVersion = 0;

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly stateStore: StateStore,
    private readonly workspaceState: vscode.Memento,
  ) {}

  /**
   * Resolves the contributed webview view.
   */
  public resolveWebviewView(webviewView: vscode.WebviewView): void {
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.extensionUri, "dist")],
    };
    webviewView.webview.html = getWebviewHtml(webviewView.webview, this.extensionUri);

    this.webviews.add(webviewView.webview);
    this.refreshCodeDirectoryPath();
    this.postState(webviewView.webview);
    void this.postCursorContextMapping(webviewView.webview);
    void this.refreshCodexRuntimeStatus();

    webviewView.onDidDispose(() => {
      this.webviews.delete(webviewView.webview);
    });

    webviewView.webview.onDidReceiveMessage(async (message: WebviewMessage) => {
      await this.handleMessage(message, webviewView.webview);
    });
  }

  /**
   * Broadcasts current cursor symbol mapping to all open webviews.
   */
  public async broadcastCursorContext(): Promise<void> {
    for (const webview of this.webviews) {
      await this.postCursorContextMapping(webview);
    }
  }

  /**
   * Handles incoming messages from the React webview.
   * @param message Webview message payload.
   * @param webview Destination webview.
   */
  private async handleMessage(message: WebviewMessage, webview: vscode.Webview): Promise<void> {
    if (message.type === "chooseDesignSpec") {
      await this.importDesignSpecFromDialog(webview);
      return;
    }

    if (message.type === "chooseIssueTracker") {
      await this.importIssueTrackerFromDialog(webview);
      return;
    }

    if (message.type === "chooseTestingPlan") {
      await this.importTestingPlanFromDialog(webview);
      return;
    }

    if (message.type === "requestCodeMapping") {
      await this.postCursorContextMapping(webview);
      return;
    }

    if (message.type === "refreshMappings") {
      await this.refreshMappings(webview);
      return;
    }

    if (message.type === "openCodeReference" && message.payload && "filePath" in message.payload) {
      await this.openCodeReference(message.payload);
      return;
    }

    if (message.type === "openImportedDocument" && message.payload && "documentType" in message.payload) {
      await this.quickOpenImportedDocument(message.payload.documentType, webview);
      return;
    }

    if (message.type === "configureCodexPath") {
      await this.configureCodexPathFromDialog(webview);
      return;
    }

    if (message.type === "configureCodeDirectory") {
      await this.configureCodeDirectoryFromDialog(webview);
    }
  }

  /**
   * Refreshes Codex runtime readiness and pushes state to all active webviews.
   */
  public async refreshCodexRuntimeStatus(): Promise<void> {
    const validationVersion = ++this.codexValidationVersion;
    this.setCodexValidationRuntime({
      isValidating: false,
      message: "",
    });

    const configuredPath = this.getConfiguredCodexPath();
    const detectedRuntime = await detectCodexRuntimeState(configuredPath);

    if (validationVersion !== this.codexValidationVersion) {
      return;
    }

    if (!detectedRuntime.effectivePath) {
      this.setCodexRuntime(detectedRuntime);
      return;
    }

    this.setCodexRuntime({
      ...detectedRuntime,
      status: "missing",
      message: "Validating Codex executable...",
    });
    this.setCodexValidationRuntime({
      isValidating: true,
      message: "Starting Codex validation...",
    });

    const validationResult = await validateCodexExecutableHandshake(
      detectedRuntime.effectivePath,
      (message) => {
        if (validationVersion !== this.codexValidationVersion) {
          return;
        }
        this.setCodexValidationRuntime({
          isValidating: true,
          message,
        });
      },
    );

    if (validationVersion !== this.codexValidationVersion) {
      return;
    }

    this.setCodexValidationRuntime({
      isValidating: false,
      message: "",
    });

    if (!validationResult.passed) {
      this.setCodexRuntime({
        ...detectedRuntime,
        status: "missing",
        message: validationResult.message,
      });
      return;
    }

    this.setCodexRuntime({
      ...detectedRuntime,
      status: "ready",
      message: validationResult.message,
    });
  }

  /**
   * Prompts user to import CSV and refreshes webview state.
   * @param webview Source webview.
   */
  private async importDesignSpecFromDialog(webview: vscode.Webview): Promise<void> {
    const selected = await vscode.window.showOpenDialog({
      canSelectMany: false,
      openLabel: "Import Design Spec CSV",
      filters: {
        "CSV Files": ["csv"],
      },
    });

    if (!selected || selected.length === 0) {
      return;
    }

    try {
      await this.runMappingWithRuntime("Importing and mapping design specs...", async () => {
        const fileUri = selected[0];
        const workspaceFolder = this.resolveWorkspaceFolder(fileUri);
        const mappingRootPath = this.resolveMappingRootPath(fileUri);
        const csvBuffer = await vscode.workspace.fs.readFile(fileUri);
        const csvText = Buffer.from(csvBuffer).toString("utf-8");
        const rows = parseDesignSpecCsv(csvText);
        const rawMappings = mapDesignSpecsToCode(rows);
        const mappings = await this.hydrateMappingsWithSymbolLocations(rawMappings, mappingRootPath);
        const previewPath = await this.writePreviewFileAndOpenTab(rows, mappings, workspaceFolder, mappingRootPath);

        this.stateStore.setImportedData({
          importedFilePath: fileUri.fsPath,
          importedPreviewPath: previewPath,
          rows,
          specToCodeMappings: mappings,
        });

        for (const currentWebview of this.webviews) {
          this.postState(currentWebview);
          await this.postCursorContextMapping(currentWebview);
        }

        void vscode.window.showInformationMessage(
          `Imported ${rows.length} design spec rows from ${fileUri.fsPath}.`,
        );
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown import error";
      webview.postMessage({ type: "error", message });
    }
  }

  /**
   * Imports issue tracking sheet path for quick-open and panel display.
   * @param webview Source webview for error messaging.
   */
  private async importIssueTrackerFromDialog(webview: vscode.Webview): Promise<void> {
    const selectedPath = await this.selectDocumentPathFromDialog("Import Issue Tracking Sheet");
    if (!selectedPath) {
      return;
    }
    try {
      this.stateStore.setIssueTrackerFilePath(selectedPath);
      for (const currentWebview of this.webviews) {
        this.postState(currentWebview);
      }
      void vscode.window.showInformationMessage(`Imported issue tracking sheet: ${selectedPath}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown issue tracking import error";
      webview.postMessage({ type: "error", message });
    }
  }

  /**
   * Imports testing plan document path for quick-open and panel display.
   * @param webview Source webview for error messaging.
   */
  private async importTestingPlanFromDialog(webview: vscode.Webview): Promise<void> {
    const selectedPath = await this.selectDocumentPathFromDialog("Import Testing Plan Document");
    if (!selectedPath) {
      return;
    }
    try {
      this.stateStore.setTestingPlanFilePath(selectedPath);
      for (const currentWebview of this.webviews) {
        this.postState(currentWebview);
      }
      void vscode.window.showInformationMessage(`Imported testing plan: ${selectedPath}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown testing plan import error";
      webview.postMessage({ type: "error", message });
    }
  }

  /**
   * Prompts user to choose a document file path for import rows.
   * @param openLabel Dialog action label.
   */
  private async selectDocumentPathFromDialog(openLabel: string): Promise<string | undefined> {
    const selected = await vscode.window.showOpenDialog({
      canSelectMany: false,
      canSelectFiles: true,
      canSelectFolders: false,
      openLabel,
    });
    if (!selected || selected.length === 0) {
      return undefined;
    }
    return selected[0].fsPath;
  }

  /**
   * Refreshes placeholder mappings and preview table tab.
   * @param webview Source webview for error messaging.
   */
  private async refreshMappings(webview: vscode.Webview): Promise<void> {
    const state = this.stateStore.getState();
    if (state.codexRuntime.status !== "ready") {
      void vscode.window.showWarningMessage("Agent is not ready. Configure and validate Codex first.");
      return;
    }

    if (state.rows.length === 0) {
      void vscode.window.showWarningMessage("Import a design spec CSV before refreshing mappings.");
      return;
    }

    try {
      await this.updateLastMappedAtNow();
      await this.runMappingWithRuntime("Running spec-to-code mappings...", async () => {
        const importedUri = state.importedFilePath ? vscode.Uri.file(state.importedFilePath) : undefined;
        const workspaceFolder = this.resolveWorkspaceFolder(importedUri);
        const mappingRootPath = this.resolveMappingRootPath(importedUri);
        const rawMappings = mapDesignSpecsToCode(state.rows);
        const mappings = await this.hydrateMappingsWithSymbolLocations(rawMappings, mappingRootPath);
        this.stateStore.setMappings(mappings);

        const previewPath = await this.writePreviewFileAndOpenTab(
          state.rows,
          mappings,
          workspaceFolder,
          mappingRootPath,
        );
        this.stateStore.setImportedPreviewPath(previewPath);

        for (const currentWebview of this.webviews) {
          this.postState(currentWebview);
          await this.postCursorContextMapping(currentWebview);
        }

        void vscode.window.showInformationMessage("Refreshed placeholder spec mappings.");
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown mapping refresh error";
      webview.postMessage({ type: "error", message });
    }
  }

  /**
   * Stores click-time timestamp for refresh mapping and broadcasts panel state.
   */
  private async updateLastMappedAtNow(): Promise<void> {
    const lastMappedAt = Date.now();
    this.stateStore.setLastMappedAt(lastMappedAt);
    for (const currentWebview of this.webviews) {
      this.postState(currentWebview);
    }
    await this.workspaceState.update(LAST_MAPPED_AT_WORKSPACE_STATE_KEY, lastMappedAt);
  }

  /**
   * Prompts user to choose Codex executable and persists it in extension settings.
   * @param webview Source webview for error messaging.
   */
  private async configureCodexPathFromDialog(webview: vscode.Webview): Promise<void> {
    const selected = await vscode.window.showOpenDialog({
      canSelectMany: false,
      canSelectFiles: true,
      canSelectFolders: false,
      openLabel: "Select Codex Executable",
    });
    if (!selected || selected.length === 0) {
      return;
    }

    try {
      await this.persistConfiguredCodexPath(selected[0].fsPath);
      await this.refreshCodexRuntimeStatus();
      const codexRuntime = this.stateStore.getState().codexRuntime;
      if (codexRuntime.status === "ready") {
        void vscode.window.showInformationMessage("Codex executable configured and ready.");
      } else {
        void vscode.window.showWarningMessage(codexRuntime.message);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to configure Codex executable path.";
      webview.postMessage({ type: "error", message });
    }
  }

  /**
   * Prompts user to choose code directory under workspace root and persists it.
   * @param webview Source webview for error messaging.
   */
  private async configureCodeDirectoryFromDialog(webview: vscode.Webview): Promise<void> {
    const workspaceRootPath = this.resolveWorkspaceRootPath();
    if (!workspaceRootPath) {
      void vscode.window.showWarningMessage("Open a workspace folder before configuring code directory.");
      return;
    }

    const selected = await vscode.window.showOpenDialog({
      canSelectMany: false,
      canSelectFiles: false,
      canSelectFolders: true,
      defaultUri: vscode.Uri.file(workspaceRootPath),
      openLabel: "Select Code Directory",
    });
    if (!selected || selected.length === 0) {
      return;
    }

    const selectedPath = selected[0].fsPath;
    if (!isPathInsideParent(workspaceRootPath, selectedPath)) {
      const message = "Selected directory must be inside the current workspace root.";
      void vscode.window.showErrorMessage(message);
      webview.postMessage({ type: "error", message });
      return;
    }

    try {
      await this.persistConfiguredCodeDirectoryPath(selectedPath);
      this.refreshCodeDirectoryPath();
      void vscode.window.showInformationMessage(`Code directory configured: ${selectedPath}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to configure code directory path.";
      webview.postMessage({ type: "error", message });
    }
  }

  /**
   * Quick-opens imported document from document import column rows.
   * @param documentType Document row type.
   * @param webview Source webview for error messaging.
   */
  private async quickOpenImportedDocument(
    documentType: ImportedDocumentType,
    webview: vscode.Webview,
  ): Promise<void> {
    const state = this.stateStore.getState();
    const documentPath = this.resolveImportedDocumentPath(state, documentType);
    if (!documentPath) {
      void vscode.window.showWarningMessage("Import this document before quick-open.");
      return;
    }
    try {
      const document = await vscode.workspace.openTextDocument(vscode.Uri.file(documentPath));
      await vscode.window.showTextDocument(document, { preview: false });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to quick-open imported document.";
      webview.postMessage({ type: "error", message });
    }
  }

  /**
   * Resolves document path from extension state for quick-open actions.
   * @param state Current extension state snapshot.
   * @param documentType Document row type.
   */
  private resolveImportedDocumentPath(
    state: ReturnType<StateStore["getState"]>,
    documentType: ImportedDocumentType,
  ): string | undefined {
    if (documentType === "designSpec") {
      return state.importedFilePath;
    }
    if (documentType === "issueTracker") {
      return state.issueTrackerFilePath;
    }
    return state.testingPlanFilePath;
  }

  /**
   * Resolves workspace folder based on imported uri or active workspace.
   * @param importedFileUri Imported csv URI.
   */
  private resolveWorkspaceFolder(importedFileUri?: vscode.Uri): vscode.WorkspaceFolder | undefined {
    return (
      (importedFileUri && vscode.workspace.getWorkspaceFolder(importedFileUri)) ??
      vscode.workspace.workspaceFolders?.[0]
    );
  }

  /**
   * Resolves workspace root path for current VS Code workspace.
   */
  private resolveWorkspaceRootPath(): string | undefined {
    return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  }

  /**
   * Resolves root path used to interpret relative mapped file links.
   * @param importedFileUri Imported csv URI.
   */
  private resolveMappingRootPath(importedFileUri?: vscode.Uri): string | undefined {
    const configuredCodeDirectoryPath = this.stateStore.getState().codeDirectoryPath;
    if (configuredCodeDirectoryPath) {
      return configuredCodeDirectoryPath;
    }

    const workspaceFolder = this.resolveWorkspaceFolder(importedFileUri);
    if (workspaceFolder && importedFileUri && vscode.workspace.getWorkspaceFolder(importedFileUri)) {
      return workspaceFolder.uri.fsPath;
    }
    if (importedFileUri) {
      return path.dirname(importedFileUri.fsPath);
    }
    return workspaceFolder?.uri.fsPath;
  }

  /**
   * Finds first symbol declaration line in a code file.
   * @param codeText Full source text.
   * @param symbol Symbol/function/class name.
   */
  private findSymbolStartLine(codeText: string, symbol: string): number {
    const escaped = escapeRegex(symbol);
    const lines = codeText.split(/\r?\n/);
    const declarationPatterns = [
      new RegExp(`\\bfunction\\s+${escaped}\\b`),
      new RegExp(`\\bclass\\s+${escaped}\\b`),
      new RegExp(`\\b${escaped}\\s*\\(`),
      new RegExp(`\\b${escaped}\\s*[:=]\\s*(?:async\\s*)?\\(`),
    ];
    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index];
      if (declarationPatterns.some((pattern) => pattern.test(line))) {
        return index + 1;
      }
    }
    return 1;
  }

  /**
   * Resolves placeholder mapping references to concrete file paths and symbol lines.
   * @param mappings Raw placeholder mappings.
   * @param workspaceFolder Workspace folder used for relative path resolution.
   */
  private async hydrateMappingsWithSymbolLocations(
    mappings: SpecCodeMapping[],
    mappingRootPath?: string,
  ): Promise<SpecCodeMapping[]> {
    const hydratedMappings: SpecCodeMapping[] = [];

    for (const mapping of mappings) {
      const references = [];
      for (const reference of mapping.references) {
        const absolutePath = path.isAbsolute(reference.filePath)
          ? reference.filePath
          : mappingRootPath
            ? path.join(mappingRootPath, reference.filePath)
            : reference.filePath;
        const targetUri = vscode.Uri.file(absolutePath);
        let lineStart = Math.max(1, reference.lineStart || 1);
        try {
          const text = await readFileFromFs(targetUri.fsPath, "utf8");
          lineStart = this.findSymbolStartLine(text, reference.symbol);
        } catch {
          // Keep placeholder line when file is unavailable.
        }

        references.push({
          ...reference,
          filePath: mappingRootPath
            ? path.relative(mappingRootPath, absolutePath).replace(/\\/g, "/")
            : reference.filePath,
          lineStart,
          lineEnd: lineStart,
        });
      }

      hydratedMappings.push({
        ...mapping,
        references,
      });
    }

    return hydratedMappings;
  }

  /**
   * Posts imported state to one webview.
   * @param webview Target webview.
   */
  private postState(webview: vscode.Webview): void {
    webview.postMessage({
      type: "stateUpdated",
      payload: this.stateStore.getState(),
    });
  }

  /**
   * Refreshes effective code directory path from config with workspace-root fallback.
   */
  public refreshCodeDirectoryPath(): void {
    const effectiveCodeDirectoryPath = resolveEffectiveCodeDirectoryPath(
      this.getConfiguredCodeDirectoryPath(),
      this.resolveWorkspaceRootPath(),
    );
    this.stateStore.setCodeDirectoryPath(effectiveCodeDirectoryPath);
    for (const currentWebview of this.webviews) {
      this.postState(currentWebview);
    }
  }

  /**
   * Updates Codex runtime state and broadcasts to all open webviews.
   * @param codexRuntime Runtime readiness payload.
   */
  private setCodexRuntime(
    codexRuntime: ReturnType<StateStore["getState"]>["codexRuntime"],
  ): void {
    this.stateStore.setCodexRuntime(codexRuntime);
    for (const currentWebview of this.webviews) {
      this.postState(currentWebview);
    }
  }

  /**
   * Updates Codex validation runtime progress and broadcasts panel updates.
   * @param codexValidationRuntime Validation progress payload.
   */
  private setCodexValidationRuntime(
    codexValidationRuntime: ReturnType<StateStore["getState"]>["codexValidationRuntime"],
  ): void {
    this.stateStore.setCodexValidationRuntime(codexValidationRuntime);
    for (const currentWebview of this.webviews) {
      this.postState(currentWebview);
    }
  }

  /**
   * Executes mapping work with runtime progress updates and fixed async delay.
   * @param runningMessage Panel message while mapping executes.
   * @param action Mapping action.
   */
  private async runMappingWithRuntime<T>(runningMessage: string, action: () => Promise<T>): Promise<T> {
    this.setMappingRuntime({
      isRunning: true,
      message: runningMessage,
      lastStartedAt: Date.now(),
    });
    try {
      await waitForMockMappingDelay();
      return await action();
    } finally {
      this.setMappingRuntime({
        isRunning: false,
        message: "Idle",
      });
    }
  }

  /**
   * Updates mapping runtime status and broadcasts state to all open webviews.
   * @param mappingRuntime Mapping runtime payload.
   */
  private setMappingRuntime(
    mappingRuntime: ReturnType<StateStore["getState"]>["mappingRuntime"],
  ): void {
    this.stateStore.setMappingRuntime(mappingRuntime);
    for (const currentWebview of this.webviews) {
      this.postState(currentWebview);
    }
  }

  /**
   * Reads user-configured Codex executable path from VS Code settings.
   */
  private getConfiguredCodexPath(): string | undefined {
    return vscode.workspace
      .getConfiguration(CODEX_PATH_CONFIGURATION_SECTION)
      .get<string>(CODEX_PATH_CONFIGURATION_KEY);
  }

  /**
   * Reads user-configured code directory path from VS Code settings.
   */
  private getConfiguredCodeDirectoryPath(): string | undefined {
    return vscode.workspace
      .getConfiguration(CODEX_PATH_CONFIGURATION_SECTION)
      .get<string>(CODE_DIRECTORY_CONFIGURATION_KEY);
  }

  /**
   * Persists user-selected Codex executable path into VS Code settings.
   * @param codexPath Selected path from file picker.
   */
  private async persistConfiguredCodexPath(codexPath: string): Promise<void> {
    const hasWorkspaceFolder = (vscode.workspace.workspaceFolders?.length ?? 0) > 0;
    const target = hasWorkspaceFolder
      ? vscode.ConfigurationTarget.Workspace
      : vscode.ConfigurationTarget.Global;
    await vscode.workspace
      .getConfiguration(CODEX_PATH_CONFIGURATION_SECTION)
      .update(CODEX_PATH_CONFIGURATION_KEY, codexPath, target);
  }

  /**
   * Persists user-selected code directory path into VS Code settings.
   * @param codeDirectoryPath Selected directory path from folder picker.
   */
  private async persistConfiguredCodeDirectoryPath(codeDirectoryPath: string): Promise<void> {
    const hasWorkspaceFolder = (vscode.workspace.workspaceFolders?.length ?? 0) > 0;
    const target = hasWorkspaceFolder
      ? vscode.ConfigurationTarget.Workspace
      : vscode.ConfigurationTarget.Global;
    await vscode.workspace
      .getConfiguration(CODEX_PATH_CONFIGURATION_SECTION)
      .update(CODE_DIRECTORY_CONFIGURATION_KEY, codeDirectoryPath, target);
  }

  /**
   * Opens a mapped code location from webview hyperlink click.
   * @param payload Code reference payload.
   */
  private async openCodeReference(payload: OpenCodeReferencePayload): Promise<void> {
    const state = this.stateStore.getState();
    const mappingRootPath = this.resolveMappingRootPath(
      state.importedFilePath ? vscode.Uri.file(state.importedFilePath) : undefined,
    );
    const targetPath = path.isAbsolute(payload.filePath)
      ? payload.filePath
      : mappingRootPath
        ? path.join(mappingRootPath, payload.filePath)
        : payload.filePath;
    const targetUri = vscode.Uri.file(targetPath);
    const document = await vscode.workspace.openTextDocument(targetUri);
    const editor = await vscode.window.showTextDocument(document, { preview: false });
    const line = Math.max(0, payload.lineStart - 1);
    const position = new vscode.Position(line, 0);
    editor.selection = new vscode.Selection(position, position);
    editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);
  }

  /**
   * Writes imported spec table markdown and opens rendered markdown preview tab.
   * @param rows Imported rows.
   * @param mappings Hydrated placeholder mappings.
   * @param workspaceFolder Workspace folder for output.
   */
  private async writePreviewFileAndOpenTab(
    rows: ReturnType<StateStore["getState"]>["rows"],
    mappings: ReturnType<StateStore["getState"]>["specToCodeMappings"],
    workspaceFolder?: vscode.WorkspaceFolder,
    mappingRootPath?: string,
  ): Promise<string | undefined> {
    const markdown = buildSpecPreviewMarkdown(rows, mappings, mappingRootPath ?? workspaceFolder?.uri.fsPath);

    if (!workspaceFolder) {
      const doc = await vscode.workspace.openTextDocument({
        language: "markdown",
        content: markdown,
      });
      await vscode.window.showTextDocument(doc, { preview: false, viewColumn: vscode.ViewColumn.Beside });
      await vscode.commands.executeCommand("markdown.showPreviewToSide", doc.uri);
      return doc.uri.toString();
    }

    const outputBasePath = workspaceFolder.uri.fsPath;
    const outputUri = vscode.Uri.file(buildPreviewOutputPath(outputBasePath));
    await vscode.workspace.fs.createDirectory(
      vscode.Uri.file(path.join(outputBasePath, ".design-spec-mapper")),
    );
    await vscode.workspace.fs.writeFile(outputUri, Buffer.from(markdown, "utf8"));
    await vscode.workspace.openTextDocument(outputUri);
    await vscode.commands.executeCommand("markdown.showPreviewToSide", outputUri);
    return outputUri.fsPath;
  }

  /**
   * Resolves and posts cursor-function/class scoped mapping to webview.
   * @param webview Target webview.
   */
  private async postCursorContextMapping(webview: vscode.Webview): Promise<void> {
    const state = this.stateStore.getState();
    const editor = vscode.window.activeTextEditor;

    if (!editor) {
      webview.postMessage({
        type: "cursorContextUpdated",
        payload: {
          filePath: "",
          symbolName: "",
          symbolKind: "unknown",
          matchedSpecs: [],
          source: "placeholder",
          message: "Open a code file and place cursor in a function/class.",
        },
      });
      return;
    }

    const symbolInfo = await this.getCurrentFunctionOrClassAtCursor(editor);
    if (!symbolInfo) {
      webview.postMessage({
        type: "cursorContextUpdated",
        payload: {
          filePath: editor.document.uri.fsPath,
          symbolName: "",
          symbolKind: "unknown",
          matchedSpecs: [],
          source: "placeholder",
          message: "Move cursor into a function or class to view mapped specs.",
        },
      });
      return;
    }

    const mapping = mapCursorContextToSpecs(
      editor.document.uri.fsPath,
      symbolInfo.symbolName,
      symbolInfo.symbolKind,
      state.rows,
      state.specToCodeMappings,
    );
    webview.postMessage({
      type: "cursorContextUpdated",
      payload: mapping,
    });
  }

  /**
   * Finds nearest function/class symbol that contains current cursor.
   * @param editor Active text editor.
   */
  private async getCurrentFunctionOrClassAtCursor(
    editor: vscode.TextEditor,
  ): Promise<{ symbolName: string; symbolKind: "function" | "class" | "method" | "constructor" | "unknown" } | undefined> {
    const symbolResults = await vscode.commands.executeCommand<
      Array<vscode.DocumentSymbol | vscode.SymbolInformation> | undefined
    >("vscode.executeDocumentSymbolProvider", editor.document.uri);
    if (!symbolResults || symbolResults.length === 0) {
      return undefined;
    }

    const cursor = editor.selection.active;
    const docSymbols = symbolResults.filter(
      (symbol): symbol is vscode.DocumentSymbol => "selectionRange" in symbol,
    );

    if (docSymbols.length > 0) {
      const candidates: vscode.DocumentSymbol[] = [];
      const walk = (symbols: vscode.DocumentSymbol[]): void => {
        for (const symbol of symbols) {
          if (symbol.range.contains(cursor) && isFunctionOrClassSymbol(symbol.kind)) {
            candidates.push(symbol);
          }
          if (symbol.children.length > 0) {
            walk(symbol.children);
          }
        }
      };
      walk(docSymbols);
      if (candidates.length > 0) {
        candidates.sort((left, right) => rangeLength(left.range) - rangeLength(right.range));
        const best = candidates[0];
        return {
          symbolName: best.name,
          symbolKind: toSymbolKindName(best.kind),
        };
      }
    }

    const infoSymbols = symbolResults.filter(
      (symbol): symbol is vscode.SymbolInformation => "location" in symbol,
    );
    const infoMatch = infoSymbols.find(
      (symbol) => symbol.location.uri.toString() === editor.document.uri.toString() && symbol.location.range.contains(cursor),
    );
    if (!infoMatch || !isFunctionOrClassSymbol(infoMatch.kind)) {
      return undefined;
    }
    return {
      symbolName: infoMatch.name,
      symbolKind: toSymbolKindName(infoMatch.kind),
    };
  }
}

/**
 * VS Code activation entrypoint.
 * @param context Extension context.
 */
export function activate(context: vscode.ExtensionContext): void {
  const lastMappedAt = context.workspaceState.get<number>(LAST_MAPPED_AT_WORKSPACE_STATE_KEY);
  const stateStore = new StateStore({ lastMappedAt });
  const previewProvider = new DesignSpecPreviewProvider(context.extensionUri, stateStore, context.workspaceState);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("designSpecMapper.previewView", previewProvider),
    vscode.window.onDidChangeActiveTextEditor(() => {
      void previewProvider.broadcastCursorContext();
    }),
    vscode.window.onDidChangeTextEditorSelection((event) => {
      if (event.textEditor === vscode.window.activeTextEditor) {
        void previewProvider.broadcastCursorContext();
      }
    }),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration(`${CODEX_PATH_CONFIGURATION_SECTION}.${CODEX_PATH_CONFIGURATION_KEY}`)) {
        void previewProvider.refreshCodexRuntimeStatus();
      }
      if (event.affectsConfiguration(`${CODEX_PATH_CONFIGURATION_SECTION}.${CODE_DIRECTORY_CONFIGURATION_KEY}`)) {
        previewProvider.refreshCodeDirectoryPath();
      }
    }),
  );

  previewProvider.refreshCodeDirectoryPath();
  void previewProvider.refreshCodexRuntimeStatus();

  context.subscriptions.push(
    outputChannel,
    runner,
    statusBar,
    panelProvider,
    sidebar,
    vscode.window.registerWebviewViewProvider("pika.sidebar", sidebar, {
      webviewOptions: { retainContextWhenHidden: true },
    }),

    // Command palette entries
    vscode.commands.registerCommand("pika.openMap", () => panelProvider.openMap()),
    vscode.commands.registerCommand("pika.openImplement", () => panelProvider.openImplement()),
    vscode.commands.registerCommand("pika.refreshSidebar", () => sidebar.pushState()),
  );
}

/** VS Code deactivation entrypoint. */
export function deactivate(): void {
  // Resources are cleaned up via context.subscriptions.
}
