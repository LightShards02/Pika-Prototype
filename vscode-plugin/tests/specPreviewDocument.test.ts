import { describe, expect, it } from "vitest";
import { buildSpecPreviewMarkdown } from "../src/core/specPreviewDocument";
import { DesignSpecRow, SpecCodeMapping } from "../src/types";

describe("buildSpecPreviewMarkdown", () => {
  it("includes markdown table and hyperlink mappings", () => {
    const rows: DesignSpecRow[] = [
      {
        id: "SPEC-001",
        title: "User Login",
        requirement: "System authenticates user.",
        acceptanceCriteria: "Token issued.",
        status: "in progress",
        original: {},
      },
    ];
    const mappings: SpecCodeMapping[] = [
      {
        specId: "SPEC-001",
        references: [
          {
            filePath: "src/auth/login.ts",
            symbol: "LoginService",
            lineStart: 12,
            lineEnd: 20,
          },
        ],
        confidence: 0.72,
        source: "dummy",
      },
    ];

    const markdown = buildSpecPreviewMarkdown(rows, mappings, "/workspace/test");
    expect(markdown).toContain("| Spec ID | Title | Requirement | Status | Mapped Functions/Classes |");
    expect(markdown).toContain("[login.ts/LoginService](");
    expect(markdown).toContain("file:///workspace/test/src/auth/login.ts#L12");
  });
});
