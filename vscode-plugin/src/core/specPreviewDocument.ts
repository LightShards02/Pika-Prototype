import * as path from "path";
import { DesignSpecRow, SpecCodeMapping } from "../types";
import { pathToFileURL } from "url";

function escapeMarkdownTableCell(value: string): string {
  return value.replace(/\|/g, "\\|").replace(/\n/g, " ").trim();
}

function toFileUri(workspaceRoot: string | undefined, relativeOrAbsolutePath: string, lineStart: number): string {
  const resolvedPath = path.isAbsolute(relativeOrAbsolutePath)
    ? relativeOrAbsolutePath
    : workspaceRoot
      ? path.join(workspaceRoot, relativeOrAbsolutePath)
      : relativeOrAbsolutePath;
  const uri = pathToFileURL(resolvedPath);
  uri.hash = `L${lineStart}`;
  return uri.toString();
}

/**
 * Builds a markdown table preview with clickable mapping links.
 * @param rows Imported design spec rows.
 * @param mappings Spec-to-code mappings.
 * @param workspaceRoot Workspace root for resolving code paths.
 */
export function buildSpecPreviewMarkdown(
  rows: DesignSpecRow[],
  mappings: SpecCodeMapping[],
  workspaceRoot?: string,
): string {
  const mappingBySpecId = new Map(mappings.map((mapping) => [mapping.specId, mapping]));
  const lines: string[] = [];
  lines.push("# Imported Design Spec Preview");
  lines.push("");
  lines.push("> Mapping links are placeholders and point to mapped function/class lines.");
  lines.push("");
  lines.push("| Spec ID | Title | Requirement | Status | Mapped Functions/Classes |");
  lines.push("|---|---|---|---|---|");

  for (const row of rows) {
    const mapping = mappingBySpecId.get(row.id);
    const mappingCell =
      mapping && mapping.references.length > 0
        ? mapping.references
            .map((reference) => {
              const uri = toFileUri(workspaceRoot, reference.filePath, reference.lineStart);
              const label = `${path.basename(reference.filePath)}/${reference.symbol}`;
              return `[${escapeMarkdownTableCell(label)}](${uri})`;
            })
            .join("<br/>")
        : "No mapping";

    lines.push(
      [
        escapeMarkdownTableCell(row.id),
        escapeMarkdownTableCell(row.title),
        escapeMarkdownTableCell(row.requirement),
        escapeMarkdownTableCell(row.status),
        mappingCell,
      ].join(" | "),
    );
  }

  lines.push("");
  return lines.join("\n");
}

/**
 * Creates a timestamped markdown preview file path under workspace.
 * @param workspaceRoot Workspace root path.
 */
export function buildPreviewOutputPath(workspaceRoot: string): string {
  const timestamp = new Date()
    .toISOString()
    .replace(/[:.]/g, "-")
    .replace("T", "_")
    .replace("Z", "");
  return path.join(
    workspaceRoot,
    ".design-spec-mapper",
    `imported_design_spec_preview_${timestamp}.md`,
  );
}
