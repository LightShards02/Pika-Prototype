import Papa from "papaparse";
import { DesignSpecRow } from "../types";

const ID_KEYS = ["spec_id", "id", "specId", "Spec ID"];
const TITLE_KEYS = ["title", "name", "Title"];
const REQUIREMENT_KEYS = ["requirement", "Requirement"];
const ACCEPTANCE_KEYS = ["acceptance_criteria", "acceptanceCriteria", "Acceptance Criteria"];
const STATUS_KEYS = ["status", "Status"];

/**
 * Resolves the first defined value from a prioritized list of keys.
 * @param row Parsed CSV object row.
 * @param keys Candidate keys in preferred order.
 * @param fallback Fallback when no key has a value.
 */
function pickValue(row: Record<string, string>, keys: string[], fallback = ""): string {
  for (const key of keys) {
    const candidate = row[key];
    if (typeof candidate === "string" && candidate.trim().length > 0) {
      return candidate.trim();
    }
  }
  return fallback;
}

/**
 * Parses raw CSV content into normalized design spec rows.
 * @param csvText Raw CSV file contents.
 */
export function parseDesignSpecCsv(csvText: string): DesignSpecRow[] {
  const result = Papa.parse<Record<string, string>>(csvText, {
    header: true,
    skipEmptyLines: true,
    transformHeader: (header: string) => header.trim(),
  });

  if (result.errors.length > 0) {
    throw new Error(`CSV parse error: ${result.errors[0]?.message ?? "unknown parse error"}`);
  }

  return result.data.map((row: Record<string, string>, index: number) => {
    const normalizedRow: Record<string, string> = {};
    for (const [key, value] of Object.entries(row)) {
      if (key) {
        normalizedRow[key] = String(value ?? "").trim();
      }
    }

    const fallbackId = `ROW_${index + 1}`;
    return {
      id: pickValue(normalizedRow, ID_KEYS, fallbackId),
      title: pickValue(normalizedRow, TITLE_KEYS, `Untitled Row ${index + 1}`),
      requirement: pickValue(normalizedRow, REQUIREMENT_KEYS, ""),
      acceptanceCriteria: pickValue(normalizedRow, ACCEPTANCE_KEYS, ""),
      status: pickValue(normalizedRow, STATUS_KEYS, "draft"),
      original: normalizedRow,
    };
  });
}
