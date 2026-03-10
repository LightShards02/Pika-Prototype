import { describe, expect, it } from "vitest";
import { mapCodeToDesignSpecs, mapCursorContextToSpecs, mapDesignSpecsToCode } from "../src/core/mappingService";
import { DesignSpecRow } from "../src/types";

function makeRows(): DesignSpecRow[] {
  return [
    {
      id: "DS-1",
      title: "User Login",
      requirement: "When users submit credentials, auth runs.",
      acceptanceCriteria: "Session token is issued.",
      status: "approved",
      original: {},
    },
    {
      id: "DS-2",
      title: "Export report",
      requirement: "When export is clicked, CSV is generated.",
      acceptanceCriteria: "Download starts.",
      status: "draft",
      original: {},
    },
  ];
}

describe("mapDesignSpecsToCode", () => {
  it("creates deterministic dummy spec-to-code mappings", () => {
    const rows = makeRows();
    const mappings = mapDesignSpecsToCode(rows);
    expect(mappings).toHaveLength(2);
    expect(mappings[0].specId).toBe("DS-1");
    expect(mappings[0].references[0].filePath).toContain("auth");
    expect(mappings[1].references[0].filePath).toContain("export");
    expect(mappings[0].source).toBe("dummy");
  });
});

describe("mapCodeToDesignSpecs", () => {
  it("returns direct matches when file path is known", () => {
    const rows = makeRows();
    const mappings = mapDesignSpecsToCode(rows);
    const codeMapping = mapCodeToDesignSpecs("/tmp/src/auth/login.ts", rows, mappings);
    expect(codeMapping.source).toBe("dummy");
    expect(codeMapping.matchedSpecs[0].specId).toBe("DS-1");
  });

  it("returns fallback placeholder when no direct mapping exists", () => {
    const rows = makeRows();
    const mappings = mapDesignSpecsToCode(rows);
    const codeMapping = mapCodeToDesignSpecs("/tmp/src/unknown/file.ts", rows, mappings);
    expect(codeMapping.source).toBe("placeholder");
    expect(codeMapping.matchedSpecs.length).toBeGreaterThan(0);
  });
});

describe("mapCursorContextToSpecs", () => {
  it("returns context-aware mappings with spec contents", () => {
    const rows = makeRows();
    const mappings = mapDesignSpecsToCode(rows);
    const cursorMapping = mapCursorContextToSpecs(
      "/tmp/src/auth/login.ts",
      "LoginService",
      "class",
      rows,
      mappings,
    );
    expect(cursorMapping.symbolName).toBe("LoginService");
    expect(cursorMapping.matchedSpecs.length).toBeGreaterThan(0);
    expect(cursorMapping.matchedSpecs[0].title).toBeTruthy();
    expect(cursorMapping.matchedSpecs[0].requirement).toBeTruthy();
  });

  it("returns placeholder prompt when symbol is missing", () => {
    const rows = makeRows();
    const mappings = mapDesignSpecsToCode(rows);
    const cursorMapping = mapCursorContextToSpecs(
      "/tmp/src/auth/login.ts",
      "",
      "unknown",
      rows,
      mappings,
    );
    expect(cursorMapping.matchedSpecs).toHaveLength(0);
    expect(cursorMapping.message).toContain("Move cursor");
  });
});
