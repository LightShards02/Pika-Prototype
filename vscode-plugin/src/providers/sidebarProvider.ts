import * as vscode from "vscode";
import { getWebviewHtml } from "../webview/getWebviewHtml";
import { readSpecStats } from "../core/csvReader";
import { readRunHistory } from "../core/runHistoryReader";
import type {
  SidebarIncomingMessage,
  SidebarOutgoingMessage,
  SpecStats,
  RunHistoryEntry,
} from "../types";

/**
 * Provides the PIKA activity-bar sidebar webview.
 *
 * The sidebar shows:
 *  - Design spec status counts (mapped / partial / blocked / unmapped)
 *  - Run Map / Run Implement buttons (normal + dry-run)
 *  - Run history list
 *
 * It talks to the extension host via postMessage:
 *   Outgoing (webview → host):  openPanel | refresh
 *   Incoming (host → webview):  specStats | runHistory | activeRun
 */
export class SidebarProvider implements vscode.WebviewViewProvider, vscode.Disposable {
  private view?: vscode.WebviewView;
  private readonly disposables: vscode.Disposable[] = [];

  constructor(
    private readonly extUri: vscode.Uri,
    private readonly workspaceRoot: string,
    private readonly onOpenPanel: (
      command: "map" | "implement",
      dryRun?: boolean
    ) => void
  ) {}

  resolveWebviewView(webviewView: vscode.WebviewView): void {
    this.view = webviewView;

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this.extUri],
    };

    webviewView.webview.html = getWebviewHtml(webviewView.webview, this.extUri, {
      view: "sidebar",
    });

    // Handle messages from the sidebar React app
    this.disposables.push(
      webviewView.webview.onDidReceiveMessage((msg: SidebarOutgoingMessage) => {
        switch (msg.type) {
          case "openPanel":
            this.onOpenPanel(msg.command, msg.dryRun);
            break;
          case "refresh":
            this.pushState();
            break;
        }
      })
    );

    // Send initial state once the view is visible
    this.pushState();
  }

  /** Push current spec stats + run history to the sidebar webview. */
  pushState(): void {
    if (!this.view) return;
    this.postSpecStats();
    this.postRunHistory();
  }

  postSpecStats(): void {
    if (!this.view) return;
    // Derive design spec path from common locations
    const specStats = tryReadSpecStats(this.workspaceRoot);
    this.post({ type: "specStats", data: specStats });
  }

  postRunHistory(): void {
    if (!this.view) return;
    const entries = readRunHistory(this.workspaceRoot);
    this.post({ type: "runHistory", entries });
  }

  setActiveRun(command: "map" | "implement" | null): void {
    this.post({ type: "activeRun", command });
  }

  private post(msg: SidebarIncomingMessage): void {
    this.view?.webview.postMessage(msg);
  }

  dispose(): void {
    this.disposables.forEach((d) => d.dispose());
  }
}

/** Attempt to read spec stats from default locations. */
function tryReadSpecStats(workspaceRoot: string): SpecStats {
  const candidates = [
    require("path").join(workspaceRoot, "out", "state", "DESIGN-SPEC.csv"),
    require("path").join(workspaceRoot, "DESIGN-SPEC.csv"),
  ];
  for (const p of candidates) {
    const stats = readSpecStats(p);
    if (stats.total > 0) return stats;
  }
  return { total: 0, mapped: 0, partial: 0, blocked: 0, unmapped: 0, implemented: 0, pending: 0 };
}
