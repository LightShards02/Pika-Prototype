import React from "react";
import { FileField, Section } from "../components/InputSection";
import { ImplementProgress } from "../components/ProgressSection";
import { ManualResolutionBlock } from "../components/ManualResolutionBlock";
import { ImplementResultsView } from "../components/ResultsSection";
import type {
  PikaConfigSnapshot,
  PanelIncomingMessage,
  PanelOutgoingMessage,
  ImplementResults,
  ManualResolutionItem,
  ManualResolution,
  ProgressData,
  WorksetInfo,
  BatchItem,
} from "../types";

import type { BatchItem as _BI } from "../components/ProgressSection";

type PanelState = "idle" | "running" | "blocked" | "complete" | "failed";

interface Props {
  postMessage: (msg: PanelOutgoingMessage) => void;
}

export function ImplementPanel({ postMessage }: Props) {
  // Form state
  const [designSpec, setDesignSpec] = React.useState("");
  const [codebaseDir, setCodebaseDir] = React.useState(".");
  const [projectContext, setProjectContext] = React.useState("");
  const [workset, setWorkset] = React.useState<WorksetInfo | null>(null);

  // Run state
  const [panelState, setPanelState] = React.useState<PanelState>("idle");
  const [errorMsg, setErrorMsg] = React.useState("");
  const [elapsed, setElapsed] = React.useState(0);
  const [tokens, setTokens] = React.useState(0);
  const [streamLines, setStreamLines] = React.useState<string[]>([]);
  const [currentPhaseIndex, setCurrentPhaseIndex] = React.useState(0);
  const [currentPhaseLabel, setCurrentPhaseLabel] = React.useState("A: Preprocess");
  const [batches, setBatches] = React.useState<_BI[]>([]);
  const [manualItems, setManualItems] = React.useState<ManualResolutionItem[]>([]);
  const [results, setResults] = React.useState<ImplementResults | null>(null);

  // Listen for messages from extension host
  React.useEffect(() => {
    const handler = (event: MessageEvent) => {
      const msg = event.data as PanelIncomingMessage | { type: "browse"; field: string; value: string };
      handleMessage(msg);
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  });

  const handleMessage = (
    msg: PanelIncomingMessage | { type: "browse"; field: string; value: string }
  ) => {
    if (msg.type === "init") {
      applyConfig(msg.config);
      if (msg.workset) setWorkset(msg.workset);
      return;
    }
    if (msg.type === "browse") {
      if (msg.field === "designSpec") setDesignSpec(msg.value);
      if (msg.field === "codebaseDir") setCodebaseDir(msg.value);
      if (msg.field === "projectContext") setProjectContext(msg.value);
      return;
    }
    if (msg.type === "stream") {
      setElapsed(msg.elapsed);
      if (msg.tokens) setTokens(msg.tokens);
      const newLines = msg.text.split(/\r?\n/);
      setStreamLines((prev) => [...prev, ...newLines].slice(-500));
      return;
    }
    if (msg.type === "progress") {
      handleProgress(msg.data);
      return;
    }
    if (msg.type === "manualResolution") {
      setManualItems(msg.items);
      setPanelState("blocked");
      return;
    }
    if (msg.type === "complete" && "batches" in msg.results) {
      setResults(msg.results as ImplementResults);
      setPanelState("complete");
      return;
    }
    if (msg.type === "failed") {
      setErrorMsg(msg.message);
      setPanelState("failed");
      return;
    }
  };

  const applyConfig = (cfg: PikaConfigSnapshot) => {
    if (cfg.designSpecPath) setDesignSpec(cfg.designSpecPath);
    if (cfg.codebaseDir) setCodebaseDir(cfg.codebaseDir);
  };

  const handleProgress = (data: ProgressData) => {
    if (data.type === "phaseChange") {
      setCurrentPhaseIndex(data.phaseIndex);
      setCurrentPhaseLabel(data.phase);
    }
    if (data.type === "batchStart") {
      setBatches((prev) => {
        const found = prev.find((b) => b.batchId === data.batchId);
        if (found) {
          return prev.map((b) =>
            b.batchId === data.batchId ? { ...b, status: "running" as const } : b
          );
        }
        const newBatch: _BI = {
          batchId: data.batchId,
          specIds: data.specIds,
          module: data.module,
          status: "running",
          streamLines: [],
        };
        // Pre-populate pending batches up to totalBatches
        const pending: _BI[] = [];
        for (let i = data.batchId + 1; i <= data.totalBatches; i++) {
          if (!prev.find((b) => b.batchId === i)) {
            pending.push({ batchId: i, specIds: [], status: "pending", filesChanged: 0 });
          }
        }
        return [...prev.filter((b) => b.batchId !== data.batchId), newBatch, ...pending].sort(
          (a, b) => a.batchId - b.batchId
        );
      });
    }
    if (data.type === "batchComplete") {
      setBatches((prev) =>
        prev.map((b) =>
          b.batchId === data.batchId
            ? {
                ...b,
                status: (data.testsPassed === false ? "failed" : "done") as _BI["status"],
                filesChanged: data.filesChanged,
                testsPassed: data.testsPassed,
              }
            : b
        )
      );
    }
    if (data.type === "tokens") {
      setTokens(data.total);
    }
  };

  const handleRun = (dryRun = false) => {
    setPanelState("running");
    setStreamLines([]);
    setBatches([]);
    setElapsed(0);
    setTokens(0);
    setCurrentPhaseIndex(0);
    setCurrentPhaseLabel("A: Preprocess");
    setErrorMsg("");
    setResults(null);
    postMessage({
      type: "runImplement",
      options: {
        designSpecPath: designSpec,
        codebaseDir,
        projectContextPath: projectContext || undefined,
        dryRun,
      },
    });
  };

  const handleCancel = () => {
    postMessage({ type: "cancelRun" });
    setPanelState("idle");
  };

  const handleRetry = (resolutions: ManualResolution[]) => {
    postMessage({ type: "resolveItems", resolutions });
    handleRun();
  };

  const browse = (field: string, isDir: boolean) => {
    postMessage(isDir ? { type: "browseDir", field } : { type: "browseFile", field });
  };

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="panel">
      <div className="panel-header">
        <h2 className="panel-title">PIKA · Implement Command</h2>
        {panelState !== "idle" && (
          <span className={`panel-badge panel-badge--${panelState}`}>
            {panelState === "running" ? "Running…" : panelState}
          </span>
        )}
      </div>

      <Section title="Inputs">
        <FileField
          label="Design Spec"
          value={designSpec}
          field="designSpec"
          onChange={setDesignSpec}
          onBrowse={browse}
        />
        <FileField
          label="Codebase Dir"
          value={codebaseDir}
          field="codebaseDir"
          isDir
          onChange={setCodebaseDir}
          onBrowse={browse}
        />
        <FileField
          label="Project Context"
          value={projectContext}
          field="projectContext"
          optional
          onChange={setProjectContext}
          onBrowse={browse}
        />
      </Section>

      {/* Workset preview */}
      {workset && (
        <div className="workset-preview">
          <div className="workset-row">
            <strong>{workset.total}</strong> specs pending implementation
          </div>
          {workset.byModule && Object.keys(workset.byModule).length > 0 && (
            <div className="module-grid">
              {Object.entries(workset.byModule).map(([mod, count]) => (
                <div key={mod} className="module-chip">
                  <span className="module-name">{mod}</span>
                  <span className="module-count">{count}</span>
                </div>
              ))}
            </div>
          )}
          {workset.warnings?.map((w) => (
            <div key={w} className="workset-warning">⚠ {w}</div>
          ))}
        </div>
      )}

      {/* Action buttons */}
      {(panelState === "idle" || panelState === "complete" || panelState === "failed") && (
        <div className="action-row">
          <button
            className="btn btn--primary"
            onClick={() => handleRun(false)}
            disabled={!designSpec}
          >
            ▶ Run Implement
          </button>
          <button
            className="btn btn--secondary"
            onClick={() => handleRun(true)}
            disabled={!designSpec}
          >
            ⊡ Dry Run
          </button>
        </div>
      )}

      {/* Error banner */}
      {panelState === "failed" && (
        <div className="error-banner">✗ {errorMsg}</div>
      )}

      {/* Progress */}
      {panelState === "running" && (
        <ImplementProgress
          currentPhaseIndex={currentPhaseIndex}
          currentPhaseLabel={currentPhaseLabel}
          batches={batches}
          streamLines={streamLines}
          elapsed={elapsed}
          tokens={tokens}
          onCancel={handleCancel}
        />
      )}

      {/* Manual resolution */}
      {panelState === "blocked" && (
        <ManualResolutionBlock items={manualItems} onRetry={handleRetry} />
      )}

      {/* Results */}
      {panelState === "complete" && results && (
        <ImplementResultsView
          results={results}
          onOpenFile={(p) => postMessage({ type: "openFile", path: p })}
          onRetryFailed={() => handleRun(false)}
        />
      )}
    </div>
  );
}
