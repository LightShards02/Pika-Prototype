import * as fs from "fs/promises";
import * as os from "os";
import * as path from "path";
import { afterEach, describe, expect, it } from "vitest";
import {
  buildExecutableCandidates,
  detectCodexRuntimeState,
  isCodexExecutableFile,
  isExecutableFile,
  normalizeConfiguredPath,
} from "../src/core/codexExecutable";

const createdDirectories: string[] = [];

/**
 * Creates a temporary executable file used for runtime detection tests.
 * @param fileName Executable file name.
 */
async function createExecutableFile(fileName = "codex"): Promise<string> {
  const tmpDirectory = await fs.mkdtemp(path.join(os.tmpdir(), "codex-detect-test-"));
  createdDirectories.push(tmpDirectory);
  const filePath = path.join(tmpDirectory, fileName);
  await fs.writeFile(filePath, "#!/usr/bin/env bash\necho codex\n", "utf8");
  await fs.chmod(filePath, 0o755);
  return filePath;
}

afterEach(async () => {
  while (createdDirectories.length > 0) {
    const directory = createdDirectories.pop();
    if (!directory) {
      continue;
    }
    await fs.rm(directory, { recursive: true, force: true });
  }
});

describe("normalizeConfiguredPath", () => {
  it("trims whitespace and drops empty values", () => {
    expect(normalizeConfiguredPath("  /tmp/codex  ")).toBe("/tmp/codex");
    expect(normalizeConfiguredPath("")).toBeUndefined();
    expect(normalizeConfiguredPath("   ")).toBeUndefined();
    expect(normalizeConfiguredPath(undefined)).toBeUndefined();
  });
});

describe("buildExecutableCandidates", () => {
  it("generates deterministic candidates from PATH entries", () => {
    const candidates = buildExecutableCandidates(["/first/bin", "/second/bin"].join(path.delimiter));
    expect(candidates.some((entry) => entry.endsWith(path.join("first", "bin", "codex")))).toBe(true);
    expect(candidates.some((entry) => entry.endsWith(path.join("second", "bin", "codex")))).toBe(true);
  });
});

describe("isExecutableFile", () => {
  it("returns true for executable files and false for directories", async () => {
    const executablePath = await createExecutableFile();
    const directoryPath = path.dirname(executablePath);
    expect(await isExecutableFile(executablePath)).toBe(true);
    expect(await isExecutableFile(directoryPath)).toBe(false);
  });
});

describe("isCodexExecutableFile", () => {
  it("requires codex-prefixed executable filenames", async () => {
    const codexExecutablePath = await createExecutableFile("codex");
    const genericExecutablePath = await createExecutableFile("python");
    expect(await isCodexExecutableFile(codexExecutablePath)).toBe(true);
    expect(await isCodexExecutableFile(genericExecutablePath)).toBe(false);
  });
});

describe("detectCodexRuntimeState", () => {
  it("uses configured executable when valid", async () => {
    const configuredExecutablePath = await createExecutableFile();
    const result = await detectCodexRuntimeState(configuredExecutablePath, "");
    expect(result.status).toBe("ready");
    expect(result.source).toBe("configured");
    expect(result.effectivePath).toBe(configuredExecutablePath);
  });

  it("falls back to auto-detected executable when configured path is invalid", async () => {
    const autoExecutablePath = await createExecutableFile();
    const autoDirectoryPath = path.dirname(autoExecutablePath);
    const result = await detectCodexRuntimeState("/invalid/codex", autoDirectoryPath);
    expect(result.status).toBe("ready");
    expect(result.source).toBe("auto");
    expect(result.effectivePath).toBe(autoExecutablePath);
  });

  it("returns missing when executable cannot be resolved", async () => {
    const result = await detectCodexRuntimeState(undefined, "/definitely/missing/path");
    expect(result.status).toBe("missing");
    expect(result.source).toBe("none");
    expect(result.effectivePath).toBeUndefined();
  });

  it("rejects configured executables that are not codex-named", async () => {
    const genericExecutablePath = await createExecutableFile("python");
    const result = await detectCodexRuntimeState(genericExecutablePath, "");
    expect(result.status).toBe("missing");
    expect(result.source).toBe("none");
  });
});
