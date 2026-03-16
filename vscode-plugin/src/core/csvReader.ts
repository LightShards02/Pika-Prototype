import * as fs from "fs";
import * as Papa from "papaparse";
import type { SpecStats } from "../types";

/**
 * Reads DESIGN-SPEC.csv and returns aggregate spec status counts.
 * Returns all-zero stats if the file doesn't exist or can't be parsed.
 */
export function readSpecStats(csvPath: string): SpecStats {
  const stats: SpecStats = {
    total: 0,
    mapped: 0,
    partial: 0,
    blocked: 0,
    unmapped: 0,
    implemented: 0,
    pending: 0,
  };

  if (!fs.existsSync(csvPath)) return stats;

  let text: string;
  try {
    text = fs.readFileSync(csvPath, "utf-8");
  } catch {
    return stats;
  }

  const result = Papa.parse<Record<string, string>>(text, {
    header: true,
    skipEmptyLines: true,
  });

  for (const row of result.data) {
    stats.total++;

    switch ((row["map_status"] ?? "").toLowerCase().trim()) {
      case "mapped":
        stats.mapped++;
        break;
      case "partial":
        stats.partial++;
        break;
      case "blocked":
        stats.blocked++;
        break;
      default:
        stats.unmapped++;
    }

    if ((row["implementation_status"] ?? "").toLowerCase().trim() === "done") {
      stats.implemented++;
    } else {
      stats.pending++;
    }
  }

  return stats;
}

/**
 * Returns workset information: pending specs and their module breakdown.
 */
export function readWorkset(csvPath: string): {
  total: number;
  byModule: Record<string, number>;
  warnings: string[];
} {
  const warnings: string[] = [];
  const byModule: Record<string, number> = {};
  let total = 0;

  if (!fs.existsSync(csvPath)) return { total, byModule, warnings };

  let text: string;
  try {
    text = fs.readFileSync(csvPath, "utf-8");
  } catch {
    return { total, byModule, warnings };
  }

  const result = Papa.parse<Record<string, string>>(text, {
    header: true,
    skipEmptyLines: true,
  });

  let missingModuleTag = 0;
  for (const row of result.data) {
    if ((row["implementation_status"] ?? "").toLowerCase().trim() === "done") continue;
    total++;
    const mod = (row["module_tag"] ?? "").trim();
    if (!mod) {
      missingModuleTag++;
    } else {
      byModule[mod] = (byModule[mod] ?? 0) + 1;
    }
  }

  if (missingModuleTag > 0) {
    warnings.push(`${missingModuleTag} spec(s) missing module_tag — will be skipped`);
  }

  return { total, byModule, warnings };
}
