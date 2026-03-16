import * as fs from "fs";
import * as path from "path";
import * as yaml from "js-yaml";
import type { PikaConfigSnapshot } from "../types";

/**
 * Reads pika config.yaml (or config/config.yaml) and extracts values needed
 * to pre-fill the Map and Implement forms.  Never throws — returns {} on any
 * error so the UI can still open with empty defaults.
 */
export function readPikaConfig(workspaceRoot: string): PikaConfigSnapshot {
  const candidates = [
    path.join(workspaceRoot, "config.yaml"),
    path.join(workspaceRoot, "config", "config.yaml"),
    path.join(workspaceRoot, "config", "config.example.yaml"),
  ];

  for (const candidate of candidates) {
    if (!fs.existsSync(candidate)) continue;
    try {
      const text = fs.readFileSync(candidate, "utf-8");
      const cfg = yaml.load(text) as Record<string, unknown>;
      return extractSnapshot(cfg, workspaceRoot);
    } catch {
      // continue to next candidate
    }
  }
  return {};
}

function extractSnapshot(cfg: Record<string, unknown>, root: string): PikaConfigSnapshot {
  const snap: PikaConfigSnapshot = {};
  const project = cfg?.project as Record<string, unknown> | undefined;
  const state = project?.state as Record<string, unknown> | undefined;
  const commands = cfg?.commands as Record<string, unknown> | undefined;
  const mapCfg = commands?.map as Record<string, unknown> | undefined;
  const implCfg = commands?.implement as Record<string, unknown> | undefined;

  const specPath = state?.design_spec_path as string | undefined;
  if (specPath) snap.designSpecPath = path.resolve(root, specPath);

  const rootDir = (project?.root_dir as string) ?? ".";
  snap.codebaseDir = path.resolve(root, rootDir);

  if (mapCfg?.skip_mapped !== undefined) snap.skipMapped = Boolean(mapCfg.skip_mapped);
  if (mapCfg?.max_specs_per_subunit !== undefined)
    snap.maxSpecsPerSubunit = Number(mapCfg.max_specs_per_subunit);

  const minConf =
    (implCfg?.min_confidence_threshold as number | undefined) ??
    ((cfg?.agent as Record<string, unknown> | undefined)?.min_confidence_threshold as number | undefined);
  if (minConf !== undefined) snap.minConfidenceThreshold = minConf;

  const verifyCmds = (implCfg?.verification_commands as string[] | undefined);
  if (Array.isArray(verifyCmds)) snap.verificationCommands = verifyCmds;

  return snap;
}
