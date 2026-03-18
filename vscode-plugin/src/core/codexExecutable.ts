import * as fs from "fs/promises";
import * as os from "os";
import * as path from "path";
import { CodexRuntimeState } from "../types";

/**
 * Resolves Codex executable runtime readiness from configured path and local disk scan.
 * @param configuredPath User-configured executable path from extension settings.
 * @param pathEnv PATH-style environment value used for auto-detection.
 */
export async function detectCodexRuntimeState(
  configuredPath?: string,
  pathEnv: string | undefined = process.env.PATH,
): Promise<CodexRuntimeState> {
  const normalizedConfiguredPath = normalizeConfiguredPath(configuredPath);
  const autoDetectedPath = await findCodexExecutable(pathEnv);

  if (normalizedConfiguredPath) {
    if (await isCodexExecutableFile(normalizedConfiguredPath)) {
      return {
        status: "ready",
        source: "configured",
        configuredPath: normalizedConfiguredPath,
        effectivePath: normalizedConfiguredPath,
        message: "Configured Codex executable is available.",
      };
    }

    if (autoDetectedPath) {
      return {
        status: "ready",
        source: "auto",
        configuredPath: normalizedConfiguredPath,
        effectivePath: autoDetectedPath,
        message: "Configured Codex path is invalid; auto-detected executable is available.",
      };
    }

    return {
      status: "missing",
      source: "none",
      configuredPath: normalizedConfiguredPath,
      message: "Configured Codex path is invalid and no executable was auto-detected.",
    };
  }

  if (autoDetectedPath) {
    return {
      status: "ready",
      source: "auto",
      effectivePath: autoDetectedPath,
      message: "Codex executable auto-detected.",
    };
  }

  return {
    status: "missing",
    source: "none",
    message: "Codex executable was not found. Configure the path to enable the agent.",
  };
}

/**
 * Returns first discovered Codex executable path from PATH and common install locations.
 * @param pathEnv PATH-style environment value.
 */
export async function findCodexExecutable(pathEnv: string | undefined): Promise<string | undefined> {
  const candidates = buildExecutableCandidates(pathEnv);
  for (const candidate of candidates) {
    if (await isExecutableFile(candidate)) {
      return candidate;
    }
  }
  return undefined;
}

/**
 * Produces deterministic candidate paths where the Codex executable can exist.
 * @param pathEnv PATH-style environment value.
 */
export function buildExecutableCandidates(pathEnv: string | undefined): string[] {
  const executableNames = getCodexExecutableNames();
  const pathDirectories = (pathEnv ?? "")
    .split(path.delimiter)
    .map((value) => value.trim())
    .filter((value) => value.length > 0);
  const commonDirectories = getCommonInstallDirectories();
  const allDirectories = [...pathDirectories, ...commonDirectories];
  const uniqueDirectories = uniqueNormalizedPaths(allDirectories);
  const candidates: string[] = [];

  for (const directory of uniqueDirectories) {
    for (const executableName of executableNames) {
      candidates.push(path.join(directory, executableName));
    }
  }

  return uniqueNormalizedPaths(candidates);
}

/**
 * Returns executable names by operating system.
 */
export function getCodexExecutableNames(): string[] {
  if (process.platform === "win32") {
    return ["codex.exe", "codex.cmd", "codex.bat", "codex"];
  }
  return ["codex"];
}

/**
 * Returns common installation directories in deterministic order.
 */
export function getCommonInstallDirectories(): string[] {
  const homeDirectory = os.homedir();
  if (process.platform === "win32") {
    return [
      path.join(process.env.ProgramFiles ?? "C:\\Program Files", "Codex"),
      path.join(process.env["ProgramFiles(x86)"] ?? "C:\\Program Files (x86)", "Codex"),
      path.join(homeDirectory, "AppData", "Local", "Programs", "Codex"),
      path.join(homeDirectory, "AppData", "Local", "Microsoft", "WindowsApps"),
    ];
  }
  return ["/usr/local/bin", "/opt/homebrew/bin", "/usr/bin", "/bin", path.join(homeDirectory, ".local", "bin")];
}

/**
 * Ensures configured path is a non-empty trimmed string.
 * @param configuredPath User-provided setting value.
 */
export function normalizeConfiguredPath(configuredPath?: string): string | undefined {
  const trimmed = configuredPath?.trim();
  return trimmed ? trimmed : undefined;
}

/**
 * Checks that a path exists, is a file, and is executable on this platform.
 * @param filePath Candidate file path.
 */
export async function isExecutableFile(filePath: string): Promise<boolean> {
  try {
    const stat = await fs.stat(filePath);
    if (!stat.isFile()) {
      return false;
    }
    if (process.platform === "win32") {
      return true;
    }
    await fs.access(filePath, fs.constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

/**
 * Checks whether file is executable and follows Codex executable naming.
 * @param filePath Candidate configured file path.
 */
export async function isCodexExecutableFile(filePath: string): Promise<boolean> {
  const baseName = path.basename(filePath).toLowerCase();
  if (!baseName.startsWith("codex")) {
    return false;
  }
  return isExecutableFile(filePath);
}

/**
 * De-duplicates and normalizes path values while preserving first-seen order.
 * @param values Path values to normalize.
 */
function uniqueNormalizedPaths(values: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const value of values) {
    const normalized = path.normalize(value);
    if (!seen.has(normalized)) {
      seen.add(normalized);
      result.push(normalized);
    }
  }
  return result;
}
