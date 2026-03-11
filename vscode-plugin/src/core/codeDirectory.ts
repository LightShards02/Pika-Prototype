import * as path from "path";

/**
 * Trims and normalizes configured directory path values.
 * @param configuredPath User-configured directory path.
 */
export function normalizeConfiguredDirectoryPath(configuredPath?: string): string | undefined {
  const trimmed = configuredPath?.trim();
  if (!trimmed) {
    return undefined;
  }
  return path.normalize(trimmed);
}

/**
 * Resolves effective code directory with workspace-root fallback.
 * @param configuredPath User-configured path from settings.
 * @param workspaceRootPath Active workspace root path.
 */
export function resolveEffectiveCodeDirectoryPath(
  configuredPath: string | undefined,
  workspaceRootPath: string | undefined,
): string | undefined {
  const normalizedConfiguredPath = normalizeConfiguredDirectoryPath(configuredPath);
  if (!workspaceRootPath) {
    return normalizedConfiguredPath;
  }

  const normalizedWorkspaceRootPath = path.normalize(workspaceRootPath);
  if (!normalizedConfiguredPath) {
    return normalizedWorkspaceRootPath;
  }

  const absoluteConfiguredPath = path.isAbsolute(normalizedConfiguredPath)
    ? normalizedConfiguredPath
    : path.join(normalizedWorkspaceRootPath, normalizedConfiguredPath);

  if (!isPathInsideParent(normalizedWorkspaceRootPath, absoluteConfiguredPath)) {
    return normalizedWorkspaceRootPath;
  }

  return path.normalize(absoluteConfiguredPath);
}

/**
 * Checks if candidate path is equal to or nested under a parent path.
 * @param parentPath Workspace root path.
 * @param candidatePath Candidate selected path.
 */
export function isPathInsideParent(parentPath: string, candidatePath: string): boolean {
  const relativePath = path.relative(path.normalize(parentPath), path.normalize(candidatePath));
  return relativePath === "" || (!relativePath.startsWith("..") && !path.isAbsolute(relativePath));
}
