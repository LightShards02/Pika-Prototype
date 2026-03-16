import * as cp from "child_process";
import * as path from "path";
import { EventEmitter } from "events";
import type * as vscode from "vscode";
import type {
  MapRunOptions,
  ImplementRunOptions,
  ProgressData,
  ManualResolutionItem,
  MapResults,
  ImplementResults,
} from "../types";

// ---------------------------------------------------------------------------
// Event map
// ---------------------------------------------------------------------------
export interface PikaRunnerEvents {
  started: [{ command: string; dryRun?: boolean }];
  stream: [{ text: string; elapsed: number; tokens?: number }];
  progress: [ProgressData];
  runId: [{ runId: string }];
  manualResolution: [{ items: ManualResolutionItem[] }];
  complete: [{ command: string; elapsed: number; exitCode: number }];
  failed: [{ command: string; elapsed: number; exitCode?: number; message?: string }];
  cancelled: [];
}

/**
 * Spawns pika CLI processes and emits typed progress events.
 *
 * Progress is best-effort: we parse well-known log patterns from stdout/stderr.
 * Full structured results are read from run artifacts after completion.
 */
export class PikaRunner extends EventEmitter {
  private proc: cp.ChildProcess | null = null;
  private startTime = 0;
  private _runId: string | null = null;
  private tokenAccum = 0;

  constructor(private readonly outputChannel: vscode.OutputChannel) {
    super();
  }

  get isRunning(): boolean {
    return this.proc !== null;
  }

  get currentRunId(): string | null {
    return this._runId;
  }

  // ---------------------------------------------------------------------------
  // Public run methods
  // ---------------------------------------------------------------------------

  runMap(opts: MapRunOptions, workspaceRoot: string): void {
    const args = buildMapArgs(opts);
    this.startProcess("map", workspaceRoot, args, opts.dryRun);
  }

  runImplement(opts: ImplementRunOptions, workspaceRoot: string): void {
    const args = buildImplementArgs(opts);
    this.startProcess("implement", workspaceRoot, args, opts.dryRun);
  }

  cancel(): void {
    if (!this.proc) return;
    this.proc.kill("SIGTERM");
    this.proc = null;
    this.emit("cancelled");
  }

  // ---------------------------------------------------------------------------
  // Process lifecycle
  // ---------------------------------------------------------------------------

  private startProcess(
    command: string,
    cwd: string,
    extraArgs: string[],
    dryRun?: boolean
  ): void {
    if (this.proc) throw new Error("A PIKA run is already in progress");

    this._runId = null;
    this.tokenAccum = 0;
    this.startTime = Date.now();

    const pikaArgs = ["-m", "pika", ...extraArgs];
    const { spawnCmd, spawnArgs } = buildSpawnArgs(pikaArgs);

    this.outputChannel.appendLine(`\n${"─".repeat(60)}`);
    this.outputChannel.appendLine(`[PIKA] Starting: ${command}${dryRun ? " (dry-run)" : ""}`);
    this.outputChannel.appendLine(`[PIKA] CWD: ${cwd}`);
    this.outputChannel.appendLine(`[PIKA] Cmd: ${spawnCmd} ${spawnArgs.join(" ")}`);
    this.outputChannel.appendLine(`${"─".repeat(60)}`);
    this.outputChannel.show(true);

    this.proc = cp.spawn(spawnCmd, spawnArgs, {
      cwd,
      shell: process.platform === "win32",
      env: { ...process.env },
    });

    this.emit("started", { command, dryRun });

    this.proc.stdout?.on("data", (chunk: Buffer) => {
      const text = chunk.toString();
      this.outputChannel.append(text);
      const elapsed = Math.round((Date.now() - this.startTime) / 1000);
      this.emit("stream", { text, elapsed, tokens: this.tokenAccum || undefined });
      this.parseLine(text);
    });

    this.proc.stderr?.on("data", (chunk: Buffer) => {
      const text = chunk.toString();
      this.outputChannel.append(text);
      const elapsed = Math.round((Date.now() - this.startTime) / 1000);
      this.emit("stream", { text, elapsed });
    });

    this.proc.on("close", (code) => {
      const elapsed = Math.round((Date.now() - this.startTime) / 1000);
      this.proc = null;
      if (code === 0) {
        this.outputChannel.appendLine(`\n[PIKA] ${command} complete (${elapsed}s)`);
        this.emit("complete", { command, elapsed, exitCode: 0 });
      } else {
        this.outputChannel.appendLine(
          `\n[PIKA] ${command} exited with code ${code ?? "?"} (${elapsed}s)`
        );
        this.emit("failed", { command, elapsed, exitCode: code ?? undefined });
      }
    });

    this.proc.on("error", (err) => {
      const elapsed = Math.round((Date.now() - this.startTime) / 1000);
      this.proc = null;
      this.outputChannel.appendLine(`\n[PIKA] Process error: ${err.message}`);
      this.emit("failed", { command, elapsed, message: err.message });
    });
  }

  // ---------------------------------------------------------------------------
  // Log line parser — best-effort progress extraction
  // ---------------------------------------------------------------------------

  private parseLine(text: string): void {
    // Run ID
    const runIdMatch = text.match(/[Rr]un[\s_]?[Ii][Dd][:\s]+([a-zA-Z0-9_-]{6,})/);
    if (runIdMatch && !this._runId) {
      this._runId = runIdMatch[1].trim();
      this.emit("runId", { runId: this._runId });
    }

    // Token counts  (e.g. "45,200 tokens" or "tokens: 45200")
    const tokenMatch = text.match(/(?:tokens?[:\s]+|using\s+)([\d,]+)\s*tokens?/i);
    if (tokenMatch) {
      const n = parseInt(tokenMatch[1].replace(/,/g, ""), 10);
      if (!isNaN(n) && n > this.tokenAccum) {
        this.tokenAccum = n;
        this.emit("progress", { type: "tokens", total: n } satisfies ProgressData);
      }
    }

    // Phase change  (e.g. "[PIKA] Phase B: Unified Planning")
    const phaseMatch = text.match(/Phase\s+([A-E])[:\s–-]+(.+)/i);
    if (phaseMatch) {
      const idx = phaseMatch[1].toUpperCase().charCodeAt(0) - "A".charCodeAt(0);
      this.emit("progress", {
        type: "phaseChange",
        phase: `${phaseMatch[1].toUpperCase()}: ${phaseMatch[2].trim()}`,
        phaseIndex: idx,
      } satisfies ProgressData);
    }

    // Subunit start  (e.g. "Processing subunit: auth-module (3 specs)")
    const subunitStart = text.match(/[Ss]ubunit[:\s]+([a-zA-Z0-9_-]+)\s*\((\d+)/);
    if (subunitStart) {
      this.emit("progress", {
        type: "subunitStart",
        subunit: subunitStart[1],
        specCount: parseInt(subunitStart[2], 10),
      } satisfies ProgressData);
    }

    // Subunit complete  (e.g. "Subunit auth-module: 3 mapped, 0 partial")
    const subunitDone = text.match(
      /[Ss]ubunit\s+([a-zA-Z0-9_-]+)[:\s]+(\d+)\s+mapped[,\s]+(\d+)\s+partial/
    );
    if (subunitDone) {
      this.emit("progress", {
        type: "subunitComplete",
        subunit: subunitDone[1],
        mapped: parseInt(subunitDone[2], 10),
        partial: parseInt(subunitDone[3], 10),
      } satisfies ProgressData);
    }

    // Batch progress  (e.g. "Batch 2/4" or "Executing batch 2 of 4")
    const batchMatch =
      text.match(/[Bb]atch[:\s]+(\d+)\s*\/\s*(\d+)/) ||
      text.match(/[Bb]atch\s+(\d+)\s+of\s+(\d+)/);
    if (batchMatch) {
      this.emit("progress", {
        type: "batchStart",
        batchId: parseInt(batchMatch[1], 10),
        totalBatches: parseInt(batchMatch[2], 10),
        specIds: [],
      } satisfies ProgressData);
    }
  }
}

// ---------------------------------------------------------------------------
// Arg builders
// ---------------------------------------------------------------------------

function buildMapArgs(opts: MapRunOptions): string[] {
  const args: string[] = ["map"];
  if (opts.designSpecPath) args.push("--design-spec", opts.designSpecPath);
  if (opts.codebaseDir) args.push("--codebase-dir", opts.codebaseDir);
  if (opts.projectContextPath) args.push("--project-context", opts.projectContextPath);
  if (!opts.skipMapped) args.push("--no-skip-mapped");
  if (opts.dryRun) args.push("--dry-run");
  return args;
}

function buildImplementArgs(opts: ImplementRunOptions): string[] {
  const args: string[] = ["implement"];
  if (opts.designSpecPath) args.push("--design-spec", opts.designSpecPath);
  if (opts.codebaseDir) args.push("--codebase-dir", opts.codebaseDir);
  if (opts.projectContextPath) args.push("--project-context", opts.projectContextPath);
  if (opts.dryRun) args.push("--dry-run");
  return args;
}

function buildSpawnArgs(pikaArgs: string[]): {
  spawnCmd: string;
  spawnArgs: string[];
} {
  // Use conda run -n Local python on all platforms
  return {
    spawnCmd: "conda",
    spawnArgs: ["run", "-n", "Local", "python", ...pikaArgs],
  };
}

// ---------------------------------------------------------------------------
// Run artifact readers (used after process exits)
// ---------------------------------------------------------------------------

import * as fs from "fs";

/**
 * Attempts to read map run_summary.jsonl and build a MapResults object.
 * Returns null if the artifacts are not found.
 */
export function readMapResults(
  workspaceRoot: string,
  runId: string,
  elapsedSec: number,
  tokens: number
): MapResults | null {
  const summaryPath = path.join(
    workspaceRoot,
    "out",
    "agent_runs",
    "map",
    runId,
    "run_summary.jsonl"
  );
  if (!fs.existsSync(summaryPath)) return null;

  type SummaryLine = {
    subunit?: string;
    status?: string;
    mappings?: Record<
      string,
      { status?: string; confidence?: number; code_refs?: { path?: string; symbol_name?: string }[] }
    >;
  };

  const lines = fs.readFileSync(summaryPath, "utf-8").split("\n").filter(Boolean);
  const specs: import("../types").MapSpecResult[] = [];
  let subunitCount = 0;

  for (const line of lines) {
    try {
      const entry = JSON.parse(line) as SummaryLine;
      subunitCount++;
      for (const [specId, mapping] of Object.entries(entry.mappings ?? {})) {
        const firstRef = mapping.code_refs?.[0];
        specs.push({
          specId,
          title: "",
          status: (mapping.status as import("../types").MapSpecResult["status"]) ?? "unmapped",
          confidence: mapping.confidence,
          symbols: firstRef
            ? `${firstRef.path ?? ""}::${firstRef.symbol_name ?? ""}`
            : undefined,
        });
      }
    } catch {
      // skip malformed lines
    }
  }

  const mapped = specs.filter((s) => s.status === "mapped").length;
  const partial = specs.filter((s) => s.status === "partial").length;
  const blocked = specs.filter((s) => s.status === "blocked").length;
  const unmapped = specs.filter((s) => s.status === "unmapped").length;

  return {
    runId,
    totalSpecs: specs.length,
    subunitCount,
    elapsedSec,
    tokens,
    mapped,
    partial,
    blocked,
    unmapped,
    specs,
  };
}

/**
 * Attempts to read implement batch_plan.json and unified_plan.json and build
 * an ImplementResults object. Returns null if artifacts are not found.
 */
export function readImplementResults(
  workspaceRoot: string,
  runId: string,
  elapsedSec: number,
  tokens: number
): ImplementResults | null {
  const runDir = path.join(workspaceRoot, "out", "agent_runs", "implement", runId);
  if (!fs.existsSync(runDir)) return null;

  type BatchPlan = {
    batches?: Array<{
      batch_id?: number | string;
      spec_ids?: string[];
      module_tag?: string;
    }>;
  };

  const batchPlanPath = path.join(runDir, "batch_plan.json");
  let batches: import("../types").BatchResult[] = [];

  if (fs.existsSync(batchPlanPath)) {
    try {
      const plan = JSON.parse(fs.readFileSync(batchPlanPath, "utf-8")) as BatchPlan;
      batches = (plan.batches ?? []).map((b, i) => ({
        batchId: typeof b.batch_id === "number" ? b.batch_id : i + 1,
        specIds: b.spec_ids ?? [],
        module: b.module_tag,
        filesChanged: 0,
        testsPassed: undefined,
      }));
    } catch {
      // skip
    }
  }

  // Collect changed files from diff artifacts
  const artifactsDir = path.join(workspaceRoot, "out", "agent_artifacts", "implement", runId);
  const changedFiles: import("../types").ChangedFile[] = [];
  if (fs.existsSync(artifactsDir)) {
    for (const f of fs.readdirSync(artifactsDir)) {
      if (!f.endsWith(".diff")) continue;
      try {
        const diff = fs.readFileSync(path.join(artifactsDir, f), "utf-8");
        const addedLines = (diff.match(/^\+[^+]/gm) ?? []).length;
        const removedLines = (diff.match(/^-[^-]/gm) ?? []).length;
        const fileMatch = diff.match(/^[+]{3}\s+b\/(.+)/m);
        if (fileMatch) {
          changedFiles.push({
            path: fileMatch[1].trim(),
            added: addedLines,
            removed: removedLines,
          });
        }
      } catch {
        // skip
      }
    }
  }

  const totalSpecs = batches.reduce((s, b) => s + b.specIds.length, 0);

  return {
    runId,
    totalSpecs,
    implementedSpecs: totalSpecs,
    failedSpecs: 0,
    elapsedSec,
    tokens,
    batches,
    filesChanged: changedFiles,
  };
}
