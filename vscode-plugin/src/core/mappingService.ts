import { CodeToSpecMapping, CursorSpecContext, DesignSpecRow, SpecCodeMapping } from "../types";

/**
 * Maps spec title keywords to dummy code locations for the MVP.
 * This is intentionally placeholder logic and should be replaced by
 * the real algorithm in a future iteration.
 */
function pickDummyPathFromRow(row: DesignSpecRow, rowIndex: number): string {
  const title = row.title.toLowerCase();
  const requirement = row.requirement.toLowerCase();
  const corpus = `${title} ${requirement}`;

  if (corpus.includes("login") || corpus.includes("auth")) {
    return "src/auth/login.ts";
  }
  if (corpus.includes("history")) {
    return "src/history/historyService.ts";
  }
  if (corpus.includes("export")) {
    return "src/export/exportService.ts";
  }
  if (corpus.includes("api")) {
    return "src/api/routes.ts";
  }
  if (corpus.includes("ui")) {
    return "src/ui/App.tsx";
  }
  return rowIndex % 2 === 0 ? "src/core/domain.ts" : "src/core/application.ts";
}

function pickDummySymbolFromRow(row: DesignSpecRow): string {
  const title = row.title.toLowerCase();
  const requirement = row.requirement.toLowerCase();
  const corpus = `${title} ${requirement}`;

  if (corpus.includes("login") || corpus.includes("auth")) {
    return "authenticateUser";
  }
  if (corpus.includes("history")) {
    return "loadHistory";
  }
  if (corpus.includes("export")) {
    return "exportReport";
  }
  if (corpus.includes("api")) {
    return "handleApiRequest";
  }
  if (corpus.includes("ui")) {
    return "renderPage";
  }
  return "execute";
}

/**
 * Produces deterministic placeholder mappings from specs to code.
 * @param rows Normalized design spec rows.
 */
export function mapDesignSpecsToCode(rows: DesignSpecRow[]): SpecCodeMapping[] {
  return rows.map((row, index) => {
    const filePath = pickDummyPathFromRow(row, index);
    const symbol = pickDummySymbolFromRow(row);
    return {
      specId: row.id,
      references: [
        {
          filePath,
          symbol,
          lineStart: 1,
          lineEnd: 1,
        },
      ],
      confidence: 0.72,
      source: "dummy",
    };
  });
}

/**
 * Produces deterministic placeholder reverse mappings from code to specs.
 * @param filePath Active code file path.
 * @param rows Normalized design spec rows.
 * @param knownMappings Existing spec-to-code mappings.
 */
export function mapCodeToDesignSpecs(
  filePath: string,
  rows: DesignSpecRow[],
  knownMappings: SpecCodeMapping[],
): CodeToSpecMapping {
  const rowById = new Map(rows.map((row) => [row.id, row]));
  const normalizedPath = filePath.toLowerCase();
  const directMatches = knownMappings
    .filter((mapping) =>
      mapping.references.some((reference) => normalizedPath.endsWith(reference.filePath.toLowerCase())),
    )
    .map((mapping) => {
      const row = rowById.get(mapping.specId);
      return {
        specId: mapping.specId,
        title: row?.title,
        requirement: row?.requirement,
        acceptanceCriteria: row?.acceptanceCriteria,
        reason: "Matched from imported placeholder spec->code mapping.",
        confidence: 0.8,
      };
    });

  if (directMatches.length > 0) {
    return {
      filePath,
      matchedSpecs: directMatches,
      source: "dummy",
    };
  }

  const fallbackRows = rows.slice(0, Math.min(rows.length, 3)).map((row, index) => ({
    specId: row.id,
    title: row.title,
    requirement: row.requirement,
    acceptanceCriteria: row.acceptanceCriteria,
    reason: "Fallback placeholder inference (algorithm pending).",
    confidence: Number((0.65 - index * 0.05).toFixed(2)),
  }));

  return {
    filePath,
    matchedSpecs: fallbackRows,
    source: "placeholder",
  };
}

/**
 * Produces deterministic placeholder mappings for current cursor function/class context.
 * @param filePath Active code file path.
 * @param symbolName Function/class symbol at cursor.
 * @param symbolKind Symbol kind for display.
 * @param rows Normalized design spec rows.
 * @param knownMappings Existing spec-to-code mappings.
 */
export function mapCursorContextToSpecs(
  filePath: string,
  symbolName: string,
  symbolKind: CursorSpecContext["symbolKind"],
  rows: DesignSpecRow[],
  knownMappings: SpecCodeMapping[],
): CursorSpecContext {
  if (!symbolName) {
    return {
      filePath,
      symbolName: "",
      symbolKind: "unknown",
      matchedSpecs: [],
      source: "placeholder",
      message: "Move cursor into a function or class to view mapped specs.",
    };
  }

  const codeLevel = mapCodeToDesignSpecs(filePath, rows, knownMappings);
  const symbolTokens = symbolName
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean);

  const scoredMatches = codeLevel.matchedSpecs
    .map((candidate) => {
      const titleTokens = (candidate.title ?? "").toLowerCase();
      const requirement = (candidate.requirement ?? "").toLowerCase();
      const corpus = `${titleTokens} ${requirement}`;
      const tokenScore = symbolTokens.some((token) => corpus.includes(token)) ? 0.12 : 0;
      const confidence = Number(Math.min(0.99, candidate.confidence + tokenScore).toFixed(2));
      return {
        specId: candidate.specId,
        title: candidate.title ?? "Untitled Spec",
        requirement: candidate.requirement ?? "",
        acceptanceCriteria: candidate.acceptanceCriteria ?? "",
        reason: `Cursor is inside ${symbolKind} "${symbolName}" and file-level mapping matched this spec.`,
        confidence,
      };
    })
    .sort((a, b) => b.confidence - a.confidence)
    .slice(0, 5);

  return {
    filePath,
    symbolName,
    symbolKind,
    matchedSpecs: scoredMatches,
    source: codeLevel.source,
    message: scoredMatches.length === 0 ? "No specs mapped for this symbol yet." : undefined,
  };
}
