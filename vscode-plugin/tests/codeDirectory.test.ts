import { describe, expect, it } from "vitest";
import {
  isPathInsideParent,
  normalizeConfiguredDirectoryPath,
  resolveEffectiveCodeDirectoryPath,
} from "../src/core/codeDirectory";

describe("normalizeConfiguredDirectoryPath", () => {
  it("trims values and drops empty strings", () => {
    expect(normalizeConfiguredDirectoryPath("  /workspace/src  ")).toBe("/workspace/src");
    expect(normalizeConfiguredDirectoryPath("")).toBeUndefined();
    expect(normalizeConfiguredDirectoryPath("   ")).toBeUndefined();
    expect(normalizeConfiguredDirectoryPath(undefined)).toBeUndefined();
  });
});

describe("isPathInsideParent", () => {
  it("accepts nested paths and rejects outside paths", () => {
    expect(isPathInsideParent("/workspace", "/workspace/src")).toBe(true);
    expect(isPathInsideParent("/workspace", "/workspace")).toBe(true);
    expect(isPathInsideParent("/workspace", "/tmp/outside")).toBe(false);
  });
});

describe("resolveEffectiveCodeDirectoryPath", () => {
  it("defaults to workspace root when configured value is empty", () => {
    expect(resolveEffectiveCodeDirectoryPath(undefined, "/workspace")).toBe("/workspace");
  });

  it("keeps configured path when inside workspace root", () => {
    expect(resolveEffectiveCodeDirectoryPath("/workspace/vscode-plugin/src", "/workspace")).toBe(
      "/workspace/vscode-plugin/src",
    );
  });

  it("falls back to workspace root when configured path is outside workspace root", () => {
    expect(resolveEffectiveCodeDirectoryPath("/tmp", "/workspace")).toBe("/workspace");
  });
});
