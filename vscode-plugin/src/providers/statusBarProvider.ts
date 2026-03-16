import * as vscode from "vscode";

type CommandStatus = "idle" | "running" | "success" | "failed" | "blocked";

interface LastRunInfo {
  status: CommandStatus;
  /** Seconds since run completed (used to format "Xm ago"). */
  completedAt?: number;
}

/**
 * Manages the PIKA status bar item (bottom-left of the window).
 *
 * Format examples:
 *   $(circuit-board) PIKA: Idle
 *   $(loading~spin) PIKA: Map running…
 *   $(circuit-board) Map ✓ 2m | Impl ✓ 1h
 *   $(warning) Impl ✗ · blocked
 */
export class StatusBarProvider implements vscode.Disposable {
  private readonly item: vscode.StatusBarItem;
  private map: LastRunInfo = { status: "idle" };
  private impl: LastRunInfo = { status: "idle" };
  private intervalHandle: ReturnType<typeof setInterval> | undefined;

  constructor() {
    this.item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    this.item.command = "pika.refreshSidebar";
    this.item.tooltip = "PIKA — click to refresh sidebar";
    this.item.show();

    // Refresh "X min ago" labels every minute
    this.intervalHandle = setInterval(() => this.render(), 60_000);
    this.render();
  }

  setMapRunning(): void {
    this.map = { status: "running" };
    this.render();
  }

  setMapComplete(success: boolean): void {
    this.map = { status: success ? "success" : "failed", completedAt: Date.now() };
    this.render();
  }

  setImplRunning(): void {
    this.impl = { status: "running" };
    this.render();
  }

  setImplComplete(success: boolean): void {
    this.impl = { status: success ? "success" : "failed", completedAt: Date.now() };
    this.render();
  }

  setBlocked(command: "map" | "implement"): void {
    if (command === "map") this.map = { status: "blocked", completedAt: Date.now() };
    else this.impl = { status: "blocked", completedAt: Date.now() };
    this.render();
  }

  private render(): void {
    const mapRunning = this.map.status === "running";
    const implRunning = this.impl.status === "running";

    if (mapRunning || implRunning) {
      const cmd = mapRunning ? "Map" : "Impl";
      this.item.text = `$(loading~spin) PIKA: ${cmd} running…`;
      this.item.backgroundColor = undefined;
      return;
    }

    const mapLabel = formatLabel(this.map);
    const implLabel = formatLabel(this.impl);
    const hasIssue =
      this.map.status === "failed" ||
      this.map.status === "blocked" ||
      this.impl.status === "failed" ||
      this.impl.status === "blocked";

    if (mapLabel === "idle" && implLabel === "idle") {
      this.item.text = "$(circuit-board) PIKA: Idle";
      this.item.backgroundColor = undefined;
    } else {
      const parts: string[] = [];
      if (mapLabel !== "idle") parts.push(`Map ${mapLabel}`);
      if (implLabel !== "idle") parts.push(`Impl ${implLabel}`);
      this.item.text = `${hasIssue ? "$(warning)" : "$(circuit-board)"} ${parts.join(" | ")}`;
      this.item.backgroundColor = hasIssue
        ? new vscode.ThemeColor("statusBarItem.warningBackground")
        : undefined;
    }
  }

  dispose(): void {
    if (this.intervalHandle !== undefined) clearInterval(this.intervalHandle);
    this.item.dispose();
  }
}

function formatLabel(info: LastRunInfo): string {
  switch (info.status) {
    case "idle":
      return "idle";
    case "running":
      return "running…";
    case "success":
      return `✓ ${formatAgo(info.completedAt)}`;
    case "failed":
      return `✗ ${formatAgo(info.completedAt)}`;
    case "blocked":
      return `⚠ blocked`;
  }
}

function formatAgo(ts?: number): string {
  if (!ts) return "";
  const secs = Math.round((Date.now() - ts) / 1000);
  if (secs < 60) return "just now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  return `${Math.floor(mins / 60)}h ago`;
}
