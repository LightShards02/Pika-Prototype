import * as vscode from "vscode";
import * as path from "path";
import { getWebviewHtml } from "../webview/getWebviewHtml";
import { readPikaConfig } from "../core/configReader";
import { readWorkset } from "../core/csvReader";
import { PikaRunner, readMapResults, readImplementResults } from "../core/pikaRunner";
import type {
  PanelIncomingMessage,
  PanelOutgoingMessage,
  MapRunOptions,
  ImplementRunOptions,
} from "../types";

/**
 * Opens and manages a PIKA command panel (Map or Implement) as a VS Code
 * WebviewPanel (editor tab).
 *
 * Only one panel per command is allowed at a time; calling open() while an
 * existing panel is visible just reveals it.
 */
export class CommandPanelProvider implements vscode.Disposable {
  private mapPanel: vscode.WebviewPanel | undefined;
  private implPanel: vscode.WebviewPanel | undefined;
  private readonly disposables: vscode.Disposable[] = [];

  constructor(
    private readonly extUri: vscode.Uri,
    private readonly workspaceRoot: string,
    private readonly outputChannel: vscode.OutputChannel,
    private readonly runner: PikaRunner,
    private readonly onRunStart: (command: "map" | "implement") => void,
    private readonly onRunEnd: (command: "map" | "implement", success: boolean) => void
  ) {}

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  openMap(dryRun = false): void {
    if (this.mapPanel) {
      this.mapPanel.reveal();
      return;
    }
    this.mapPanel = this.createPanel("map", dryRun);
  }

  openImplement(dryRun = false): void {
    if (this.implPanel) {
      this.implPanel.reveal();
      return;
    }
    this.implPanel = this.createPanel("implement", dryRun);
  }

  dispose(): void {
    this.mapPanel?.dispose();
    this.implPanel?.dispose();
    this.disposables.forEach((d) => d.dispose());
  }

  // ---------------------------------------------------------------------------
  // Panel creation
  // ---------------------------------------------------------------------------

  private createPanel(command: "map" | "implement", dryRun: boolean): vscode.WebviewPanel {
    const title = command === "map" ? "PIKA · Map" : "PIKA · Implement";
    const panel = vscode.window.createWebviewPanel(
      `pika.${command}`,
      title,
      vscode.ViewColumn.One,
      {
        enableScripts: true,
        localResourceRoots: [this.extUri],
        retainContextWhenHidden: true,
      }
    );

    panel.webview.html = getWebviewHtml(panel.webview, this.extUri, { view: command });

    // Send init state once the panel is ready (slight delay for React to mount)
    const initTimer = setTimeout(() => {
      this.sendInit(panel, command, dryRun);
    }, 300);

    // Handle messages from the webview
    const msgDisposable = panel.webview.onDidReceiveMessage(
      (msg: PanelOutgoingMessage) => this.handleMessage(panel, command, msg)
    );

    panel.onDidDispose(() => {
      clearTimeout(initTimer);
      msgDisposable.dispose();
      if (command === "map") this.mapPanel = undefined;
      else this.implPanel = undefined;
    });

    return panel;
  }

  // ---------------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------------

  private sendInit(
    panel: vscode.WebviewPanel,
    command: "map" | "implement",
    _dryRun: boolean
  ): void {
    const config = readPikaConfig(this.workspaceRoot);

    const initMsg: PanelIncomingMessage = { type: "init", command, config };

    if (command === "implement" && config.designSpecPath) {
      const { total, byModule, warnings } = readWorkset(config.designSpecPath);
      initMsg.workset = { total, byModule, warnings };
    }

    panel.webview.postMessage(initMsg);
  }

  // ---------------------------------------------------------------------------
  // Webview → Extension message handler
  // ---------------------------------------------------------------------------

  private handleMessage(
    panel: vscode.WebviewPanel,
    command: "map" | "implement",
    msg: PanelOutgoingMessage
  ): void {
    switch (msg.type) {
      case "runMap":
        this.startMapRun(panel, msg.options);
        break;
      case "runImplement":
        this.startImplementRun(panel, msg.options);
        break;
      case "cancelRun":
        this.runner.cancel();
        break;
      case "resolveItems":
        // Resolutions are stored client-side; we just acknowledge and let the
        // user click "Retry" which re-triggers a run with resolutions in opts.
        break;
      case "openFile":
        this.openFileInEditor(msg.path, msg.line);
        break;
      case "browseFile":
        this.browseFile(panel, msg.field);
        break;
      case "browseDir":
        this.browseDir(panel, msg.field);
        break;
    }
  }

  // ---------------------------------------------------------------------------
  // Run orchestration
  // ---------------------------------------------------------------------------

  private startMapRun(panel: vscode.WebviewPanel, opts: MapRunOptions): void {
    if (this.runner.isRunning) {
      vscode.window.showWarningMessage("PIKA: A run is already in progress.");
      return;
    }

    this.onRunStart("map");
    const startTime = Date.now();

    const cleanup = this.attachRunnerListeners(panel, "map", startTime, () => {
      cleanup();
    });

    this.runner.runMap(opts, this.workspaceRoot);
  }

  private startImplementRun(panel: vscode.WebviewPanel, opts: ImplementRunOptions): void {
    if (this.runner.isRunning) {
      vscode.window.showWarningMessage("PIKA: A run is already in progress.");
      return;
    }

    this.onRunStart("implement");
    const startTime = Date.now();

    const cleanup = this.attachRunnerListeners(panel, "implement", startTime, () => {
      cleanup();
    });

    this.runner.runImplement(opts, this.workspaceRoot);
  }

  /**
   * Attaches runner event listeners that forward progress/stream events to the
   * webview panel.  Returns a cleanup function that removes all listeners.
   */
  private attachRunnerListeners(
    panel: vscode.WebviewPanel,
    command: "map" | "implement",
    startTime: number,
    onCleanup: () => void
  ): () => void {
    let tokenCount = 0;

    const post = (msg: PanelIncomingMessage) => {
      if (!panel.visible) return;
      panel.webview.postMessage(msg);
    };

    const onStream = ({ text, elapsed, tokens }: { text: string; elapsed: number; tokens?: number }) => {
      if (tokens) tokenCount = tokens;
      post({ type: "stream", text, elapsed, tokens });
    };

    const onProgress = (data: Parameters<typeof post>[0] extends { type: "progress" } ? never : unknown) => {
      post({ type: "progress", data: data as PanelIncomingMessage extends { type: "progress"; data: infer D } ? D : never });
    };

    const onComplete = ({ elapsed }: { elapsed: number }) => {
      const runId = this.runner.currentRunId ?? "unknown";
      const results =
        command === "map"
          ? readMapResults(this.workspaceRoot, runId, elapsed, tokenCount)
          : readImplementResults(this.workspaceRoot, runId, elapsed, tokenCount);

      if (results) {
        post({ type: "complete", results });
      } else {
        // No artifacts found — show a generic success message
        post({
          type: "complete",
          results:
            command === "map"
              ? {
                  runId,
                  totalSpecs: 0,
                  subunitCount: 0,
                  elapsedSec: elapsed,
                  tokens: tokenCount,
                  mapped: 0,
                  partial: 0,
                  blocked: 0,
                  unmapped: 0,
                  specs: [],
                }
              : {
                  runId,
                  totalSpecs: 0,
                  implementedSpecs: 0,
                  failedSpecs: 0,
                  elapsedSec: elapsed,
                  tokens: tokenCount,
                  batches: [],
                  filesChanged: [],
                },
        });
      }

      this.onRunEnd(command, true);
      vscode.window.showInformationMessage(`PIKA: ${command} complete`, "View Results").then(
        (sel) => sel === "View Results" && panel.reveal()
      );
      onCleanup();
    };

    const onFailed = ({ elapsed, message }: { elapsed: number; message?: string; exitCode?: number }) => {
      post({
        type: "failed",
        message: message ?? `Process exited with a non-zero code after ${elapsed}s`,
      });
      this.onRunEnd(command, false);
      vscode.window.showErrorMessage(`PIKA: ${command} failed`, "View Logs").then(
        (sel) => sel === "View Logs" && this.outputChannel.show()
      );
      onCleanup();
    };

    this.runner.on("stream", onStream);
    this.runner.on("progress", onProgress);
    this.runner.on("complete", onComplete);
    this.runner.on("failed", onFailed);
    this.runner.on("cancelled", onCleanup);

    return () => {
      this.runner.off("stream", onStream);
      this.runner.off("progress", onProgress);
      this.runner.off("complete", onComplete);
      this.runner.off("failed", onFailed);
      this.runner.off("cancelled", onCleanup);
    };
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  private openFileInEditor(filePath: string, line?: number): void {
    const uri = vscode.Uri.file(
      path.isAbsolute(filePath) ? filePath : path.join(this.workspaceRoot, filePath)
    );
    vscode.window.showTextDocument(uri, { preview: false }).then((editor) => {
      if (line) {
        const pos = new vscode.Position(Math.max(0, line - 1), 0);
        editor.selection = new vscode.Selection(pos, pos);
        editor.revealRange(new vscode.Range(pos, pos));
      }
    });
  }

  private browseFile(panel: vscode.WebviewPanel, field: string): void {
    vscode.window.showOpenDialog({ canSelectFiles: true, canSelectMany: false }).then((uris) => {
      if (uris?.[0]) {
        panel.webview.postMessage({ type: "browse", field, value: uris[0].fsPath });
      }
    });
  }

  private browseDir(panel: vscode.WebviewPanel, field: string): void {
    vscode.window
      .showOpenDialog({ canSelectFolders: true, canSelectFiles: false, canSelectMany: false })
      .then((uris) => {
        if (uris?.[0]) {
          panel.webview.postMessage({ type: "browse", field, value: uris[0].fsPath });
        }
      });
  }
}
