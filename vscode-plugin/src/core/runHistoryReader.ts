import * as fs from "fs";
import * as path from "path";
import type { RunHistoryEntry } from "../types";

/**
 * Reads run history from out/agent_runs/{map,implement}/ directories.
 * Entries are sorted newest-first.
 */
export function readRunHistory(workspaceRoot: string, limit = 20): RunHistoryEntry[] {
  const agentRunsDir = path.join(workspaceRoot, "out", "agent_runs");
  if (!fs.existsSync(agentRunsDir)) return [];

  const entries: RunHistoryEntry[] = [];

  for (const command of ["map", "implement"] as const) {
    const cmdDir = path.join(agentRunsDir, command);
    if (!fs.existsSync(cmdDir)) continue;

    let runDirs: string[];
    try {
      runDirs = fs
        .readdirSync(cmdDir)
        .filter((d) => fs.statSync(path.join(cmdDir, d)).isDirectory())
        .sort()
        .reverse()
        .slice(0, limit);
    } catch {
      continue;
    }

    for (const runId of runDirs) {
      const runDir = path.join(cmdDir, runId);
      const timestamp = parseTimestampFromRunId(runId);
      const status = inferStatus(runDir);

      entries.push({
        runId,
        command,
        timestamp: timestamp.toISOString(),
        status,
      });
    }
  }

  return entries
    .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
    .slice(0, limit);
}

/** Parse timestamp from run IDs like "20260314_142234" or "run_20260314_142234". */
function parseTimestampFromRunId(runId: string): Date {
  const m = runId.match(/(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/);
  if (!m) return new Date(0);
  return new Date(
    parseInt(m[1]),
    parseInt(m[2]) - 1,
    parseInt(m[3]),
    parseInt(m[4]),
    parseInt(m[5]),
    parseInt(m[6])
  );
}

/** Infer run status from presence of summary/error artifacts. */
function inferStatus(runDir: string): RunHistoryEntry["status"] {
  const hasSummary =
    fs.existsSync(path.join(runDir, "run_summary.jsonl")) ||
    fs.existsSync(path.join(runDir, "unified_plan.json")) ||
    fs.existsSync(path.join(runDir, "batch_plan.json"));
  const hasError = fs.existsSync(path.join(runDir, "error.json"));

  if (hasError) return "failed";
  if (hasSummary) return "success";
  return "unknown";
}
