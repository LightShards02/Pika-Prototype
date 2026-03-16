import * as vscode from "vscode";
import { SidebarProvider } from "./providers/sidebarProvider";
import { CommandPanelProvider } from "./providers/commandPanelProvider";
import { StatusBarProvider } from "./providers/statusBarProvider";
import { PikaRunner } from "./core/pikaRunner";

/**
 * VS Code extension activation entrypoint.
 */
export function activate(context: vscode.ExtensionContext): void {
  const workspaceRoot =
    vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? process.cwd();

  // ── Shared infrastructure ──────────────────────────────────────────────────
  const outputChannel = vscode.window.createOutputChannel("PIKA");
  const runner = new PikaRunner(outputChannel);
  const statusBar = new StatusBarProvider();

  // ── Command panel provider ─────────────────────────────────────────────────
  const panelProvider = new CommandPanelProvider(
    context.extensionUri,
    workspaceRoot,
    outputChannel,
    runner,
    (command) => {
      if (command === "map") statusBar.setMapRunning();
      else statusBar.setImplRunning();
      sidebar.setActiveRun(command);
    },
    (command, success) => {
      if (command === "map") statusBar.setMapComplete(success);
      else statusBar.setImplComplete(success);
      sidebar.setActiveRun(null);
      sidebar.pushState(); // refresh spec counts + run history
    }
  );

  // ── Sidebar ────────────────────────────────────────────────────────────────
  const sidebar = new SidebarProvider(
    context.extensionUri,
    workspaceRoot,
    (command, dryRun) => {
      if (command === "map") panelProvider.openMap(dryRun);
      else panelProvider.openImplement(dryRun);
    }
  );

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
